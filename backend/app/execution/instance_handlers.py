"""Handlers for instance.create / instance.update / instance.set_active /
instance.delete (registered in app/authorization/operations.py).

They run through the existing OperationExecutor, so authorization and
explicit confirmation happen before any change, and verify() reads the result
back. Every change that makes or keeps an instance active requires a passing
live compatibility check (app/instances/handshake.py) first; dry_run() runs
the same validation and check but changes nothing.

Passwords travel only as SecretStr inside the request parameters, which are
never returned or traced; results carry InstanceView/InstanceCheck data only.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, SecretStr, StrictBool, ValidationError, field_validator

from app.config import Settings
from app.execution.handler import OperationHandler
from app.execution.models import (
    ExecutionContext,
    HandlerExecutionResult,
    HandlerOutcome,
    OperationRequest,
    PostActionVerificationResult,
    PostActionVerificationStatus,
)
from app.instances.credentials import (
    CredentialStoreError,
    WalletCredentialStore,
    add_instance,
    credential_ref_for,
    delete_instance,
    resolve_password,
    update_instance,
)
from app.instances.handshake import check_connection, check_instance
from app.instances.models import (
    InstanceCheck,
    InstanceCheckStatus,
    InstanceDefinition,
    InstanceView,
    normalize_base_url,
)
from app.instances.registry import InstancePersistenceError, InstanceRegistry, InstanceRegistryError

_CONNECTION_FIELDS = ("base_url", "username", "namespace")


def _failure(detail: str, **data: Any) -> HandlerExecutionResult:
    return HandlerExecutionResult(outcome=HandlerOutcome.FAILURE, detail=detail, data=data)


def _verified(detail: str) -> PostActionVerificationResult:
    return PostActionVerificationResult(status=PostActionVerificationStatus.VERIFIED, detail=detail)


def _not_verified(detail: str) -> PostActionVerificationResult:
    return PostActionVerificationResult(status=PostActionVerificationStatus.VERIFICATION_FAILED, detail=detail)


def _invalid(exc: ValidationError) -> HandlerExecutionResult:
    # Field names only: values (which may include the password) are never echoed.
    fields = sorted({".".join(str(part) for part in error["loc"]) or "request" for error in exc.errors()})
    return _failure(f"Invalid instance request ({', '.join(fields)}).")


def _check_data(check: InstanceCheck) -> dict[str, Any]:
    return {"check": check.model_dump(mode="json")}


def _incompatible(check: InstanceCheck) -> HandlerExecutionResult:
    return _failure(
        f"The instance is not compatible ({check.status.value}: {check.detail or check.failure}). Nothing was changed.",
        **_check_data(check),
    )


class _InstanceHandler(OperationHandler):
    def __init__(self, registry: InstanceRegistry, store: WalletCredentialStore, settings: Settings):
        self._registry = registry
        self._store = store
        self._settings = settings

    def _user_defined(self, instance_id: str) -> InstanceDefinition | HandlerExecutionResult:
        instance = self._registry.get(instance_id)
        if instance is None:
            return _failure(f"No instance with id {instance_id!r}.")
        if instance.primary:
            return _failure("The Primary instance comes from the environment and can't be changed.")
        return instance


# --- instance.create ---


class InstanceCreateParameters(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(min_length=1, max_length=80)
    base_url: str
    username: str = Field(min_length=1, max_length=160)
    namespace: str = "USER"
    password: SecretStr

    @field_validator("base_url")
    @classmethod
    def _url(cls, value: str) -> str:
        return normalize_base_url(value)


class InstanceCreateHandler(_InstanceHandler):
    async def _prepare(self, request: OperationRequest) -> tuple[InstanceCreateParameters, InstanceCheck] | HandlerExecutionResult:
        try:
            params = InstanceCreateParameters.model_validate(request.parameters)
        except ValidationError as exc:
            return _invalid(exc)
        if not params.password.get_secret_value().strip():
            return _failure("A password is required.")
        try:  # the same rules the saved definition must satisfy
            now = datetime.now(timezone.utc)
            InstanceDefinition(
                id="iris-000000000000", name=params.name, base_url=params.base_url, username=params.username,
                namespace=params.namespace, created_at=now, updated_at=now,
            )
        except ValidationError as exc:
            return _invalid(exc)
        if self._registry.url_in_use(params.base_url):
            return _failure("An instance with this URL is already registered.")
        check = await check_connection(
            base_url=params.base_url, username=params.username, password=params.password,
            namespace=params.namespace, settings=self._settings,
        )
        if check.status is not InstanceCheckStatus.COMPATIBLE:
            return _incompatible(check)
        return params, check

    async def dry_run(self, request: OperationRequest, context: ExecutionContext) -> HandlerExecutionResult:
        prepared = await self._prepare(request)
        if isinstance(prepared, HandlerExecutionResult):
            return prepared
        params, check = prepared
        return HandlerExecutionResult(
            outcome=HandlerOutcome.SUCCESS,
            detail=f"Dry run: {params.base_url} is compatible and would be registered as {params.name!r}. Nothing was saved.",
            data=_check_data(check),
        )

    async def execute(self, request: OperationRequest, context: ExecutionContext) -> HandlerExecutionResult:
        prepared = await self._prepare(request)
        if isinstance(prepared, HandlerExecutionResult):
            return prepared
        params, check = prepared
        try:
            instance = await add_instance(
                self._registry, self._store, name=params.name, base_url=params.base_url,
                username=params.username, password=params.password, namespace=params.namespace,
            )
        except (InstanceRegistryError, InstancePersistenceError, CredentialStoreError, ValidationError) as exc:
            return _failure(f"The instance was not registered: {_safe_reason(exc)}", **_check_data(check))
        return HandlerExecutionResult(
            outcome=HandlerOutcome.SUCCESS,
            detail=f"Instance {instance.name!r} registered and active.",
            data={"instance": InstanceView.of(instance).model_dump(mode="json"), **_check_data(check)},
        )

    async def verify(self, request, context, execution_result) -> PostActionVerificationResult:
        instance_id = execution_result.data["instance"]["id"]
        instance = self._registry.get(instance_id)
        if instance is None or instance.credential_ref is None:
            return _not_verified("The registered instance could not be read back.")
        if not await self._store.exists(instance.credential_ref):
            return _not_verified("The instance's credential is not in the IRIS Wallet.")
        return _verified(f"Instance {instance.name!r} is registered with its credential in the IRIS Wallet.")


# --- instance.update ---


class InstanceUpdateParameters(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    instance_id: str
    name: str | None = Field(default=None, min_length=1, max_length=80)
    base_url: str | None = None
    username: str | None = Field(default=None, min_length=1, max_length=160)
    namespace: str | None = None
    password: SecretStr | None = None

    @field_validator("base_url")
    @classmethod
    def _url(cls, value: str | None) -> str | None:
        return None if value is None else normalize_base_url(value)


class InstanceUpdateHandler(_InstanceHandler):
    async def _prepare(
        self, request: OperationRequest
    ) -> tuple[InstanceUpdateParameters, dict[str, Any], InstanceCheck | None] | HandlerExecutionResult:
        try:
            params = InstanceUpdateParameters.model_validate(request.parameters)
        except ValidationError as exc:
            return _invalid(exc)
        current = self._user_defined(params.instance_id)
        if isinstance(current, HandlerExecutionResult):
            return current
        changes = {
            field: getattr(params, field)
            for field in ("name", *_CONNECTION_FIELDS)
            if getattr(params, field) is not None and getattr(params, field) != getattr(current, field)
        }
        try:
            merged = InstanceDefinition.model_validate({**current.model_dump(), **changes})
        except ValidationError as exc:
            return _invalid(exc)
        if "base_url" in changes and self._registry.url_in_use(merged.base_url, ignore=current.id):
            return _failure("An instance with this URL is already registered.")
        new_password = params.password if params.password and params.password.get_secret_value().strip() else None
        connection_changed = new_password is not None or any(f in changes for f in _CONNECTION_FIELDS)
        check = None
        if current.active and connection_changed:
            try:
                password = new_password or await asyncio.to_thread(
                    resolve_password, current, self._settings, self._store
                )
            except CredentialStoreError:
                return _failure("The stored credential could not be read; provide the password to re-check.")
            check = await check_connection(
                base_url=merged.base_url, username=merged.username, password=password,
                namespace=merged.namespace, settings=self._settings,
            )
            if check.status is not InstanceCheckStatus.COMPATIBLE:
                return _incompatible(check)
        return params, changes, check

    async def dry_run(self, request: OperationRequest, context: ExecutionContext) -> HandlerExecutionResult:
        prepared = await self._prepare(request)
        if isinstance(prepared, HandlerExecutionResult):
            return prepared
        params, changes, check = prepared
        password_note = " and replace the stored password" if params.password and params.password.get_secret_value().strip() else ""
        return HandlerExecutionResult(
            outcome=HandlerOutcome.SUCCESS,
            detail=f"Dry run: would change {', '.join(sorted(changes)) or 'nothing'}{password_note}. Nothing was saved.",
            data=_check_data(check) if check else {},
        )

    async def execute(self, request: OperationRequest, context: ExecutionContext) -> HandlerExecutionResult:
        prepared = await self._prepare(request)
        if isinstance(prepared, HandlerExecutionResult):
            return prepared
        params, changes, check = prepared
        try:
            instance = await update_instance(
                self._registry, self._store, params.instance_id, password=params.password, **changes
            )
        except (InstanceRegistryError, InstancePersistenceError, CredentialStoreError, ValidationError) as exc:
            return _failure(f"The instance was not updated: {_safe_reason(exc)}")
        return HandlerExecutionResult(
            outcome=HandlerOutcome.SUCCESS,
            detail=f"Instance {instance.name!r} updated.",
            data={"instance": InstanceView.of(instance).model_dump(mode="json"),
                  "changed": sorted(changes), **(_check_data(check) if check else {})},
        )

    async def verify(self, request, context, execution_result) -> PostActionVerificationResult:
        expected = execution_result.data["instance"]
        instance = self._registry.get(expected["id"])
        if instance is None:
            return _not_verified("The updated instance could not be read back.")
        mismatched = [f for f in ("name", *_CONNECTION_FIELDS) if getattr(instance, f) != expected[f]]
        if mismatched:
            return _not_verified(f"The instance does not match the update: {', '.join(mismatched)}.")
        return _verified(f"Instance {instance.name!r} reads back as updated.")


# --- instance.set_active ---


class InstanceSetActiveParameters(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    instance_id: str
    active: StrictBool


class InstanceSetActiveHandler(_InstanceHandler):
    async def _prepare(
        self, request: OperationRequest
    ) -> tuple[InstanceSetActiveParameters, InstanceCheck | None] | HandlerExecutionResult:
        try:
            params = InstanceSetActiveParameters.model_validate(request.parameters)
        except ValidationError as exc:
            return _invalid(exc)
        current = self._registry.get(params.instance_id)
        if current is None:
            return _failure(f"No instance with id {params.instance_id!r}.")
        if current.primary and not params.active:
            return _failure("The Primary instance can't be deactivated.")
        check = None
        if params.active and not current.active:
            check = await check_instance(current, self._settings, self._store)
            if check.status is not InstanceCheckStatus.COMPATIBLE:
                return _incompatible(check)
        return params, check

    async def dry_run(self, request: OperationRequest, context: ExecutionContext) -> HandlerExecutionResult:
        prepared = await self._prepare(request)
        if isinstance(prepared, HandlerExecutionResult):
            return prepared
        params, check = prepared
        state = "activated" if params.active else "deactivated"
        return HandlerExecutionResult(
            outcome=HandlerOutcome.SUCCESS,
            detail=f"Dry run: the instance would be {state}. Nothing was saved.",
            data=_check_data(check) if check else {},
        )

    async def execute(self, request: OperationRequest, context: ExecutionContext) -> HandlerExecutionResult:
        prepared = await self._prepare(request)
        if isinstance(prepared, HandlerExecutionResult):
            return prepared
        params, check = prepared
        try:
            instance = await asyncio.to_thread(self._registry.set_active, params.instance_id, params.active)
        except (InstanceRegistryError, InstancePersistenceError) as exc:
            return _failure(f"The instance was not changed: {_safe_reason(exc)}")
        return HandlerExecutionResult(
            outcome=HandlerOutcome.SUCCESS,
            detail=f"Instance {instance.name!r} is {'active' if instance.active else 'inactive'}.",
            data={"instance": InstanceView.of(instance).model_dump(mode="json"),
                  **(_check_data(check) if check else {})},
        )

    async def verify(self, request, context, execution_result) -> PostActionVerificationResult:
        expected = execution_result.data["instance"]
        instance = self._registry.get(expected["id"])
        if instance is None or instance.active is not expected["active"]:
            return _not_verified("The instance's active state does not read back as requested.")
        return _verified(f"Instance {instance.name!r} reads back as {'active' if instance.active else 'inactive'}.")


# --- instance.delete ---


class InstanceDeleteParameters(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    instance_id: str


class InstanceDeleteHandler(_InstanceHandler):
    def _prepare(self, request: OperationRequest) -> InstanceDefinition | HandlerExecutionResult:
        try:
            params = InstanceDeleteParameters.model_validate(request.parameters)
        except ValidationError as exc:
            return _invalid(exc)
        return self._user_defined(params.instance_id)

    async def dry_run(self, request: OperationRequest, context: ExecutionContext) -> HandlerExecutionResult:
        current = self._prepare(request)
        if isinstance(current, HandlerExecutionResult):
            return current
        return HandlerExecutionResult(
            outcome=HandlerOutcome.SUCCESS,
            detail=f"Dry run: instance {current.name!r} and its stored credential would be removed. Nothing was changed.",
            data={"instance": InstanceView.of(current).model_dump(mode="json")},
        )

    async def execute(self, request: OperationRequest, context: ExecutionContext) -> HandlerExecutionResult:
        current = self._prepare(request)
        if isinstance(current, HandlerExecutionResult):
            return current
        try:
            await delete_instance(self._registry, self._store, current.id)
        except (InstanceRegistryError, InstancePersistenceError, CredentialStoreError) as exc:
            return _failure(f"The instance was not deleted: {_safe_reason(exc)}")
        return HandlerExecutionResult(
            outcome=HandlerOutcome.SUCCESS,
            detail=f"Instance {current.name!r} and its stored credential were removed.",
            data={"instance": InstanceView.of(current).model_dump(mode="json")},
        )

    async def verify(self, request, context, execution_result) -> PostActionVerificationResult:
        expected = execution_result.data["instance"]
        if self._registry.get(expected["id"]) is not None:
            return _not_verified("The instance is still registered.")
        if expected["has_credential"] and await self._store.exists(credential_ref_for(expected["id"])):
            return _not_verified("The instance's credential is still in the IRIS Wallet.")
        return _verified(f"Instance {expected['name']!r} and its credential are gone.")


def _safe_reason(exc: Exception) -> str:
    """Registry/credential errors carry fixed text only; anything else is generic."""
    if isinstance(exc, (InstanceRegistryError, InstancePersistenceError, CredentialStoreError)):
        return str(exc)
    return "invalid instance definition."
