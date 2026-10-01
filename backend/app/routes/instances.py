"""IRIS instances: list, test, register, change, check, (de)activate, delete.

Reads and the connection test are direct. Changes (create, update, activate,
deactivate, delete) are registered operations run through the executor, so
they need the caller's IRIS privilege and confirmed=true, and are verified
and traced like every other operation; they always return 200 with an
OperationResult. A saved check (POST /instances/{id}/check) stores its result
as the instance's last_check; the connection test stores nothing.

Passwords are accepted only in request bodies and are never returned.
"""

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator

from app.config import Settings, get_settings
from app.dependencies import get_caller_privileges, get_credential_store, get_instance_registry
from app.execution.executor import OperationExecutor
from app.execution.instance_handlers import (
    InstanceCreateHandler,
    InstanceDeleteHandler,
    InstanceSetActiveHandler,
    InstanceUpdateHandler,
)
from app.execution.models import ExecutionContext, OperationRequest, OperationResult
from app.instances.credentials import WalletCredentialStore
from app.instances.handshake import check_connection, check_instance
from app.instances.models import InstanceCheck, InstanceView, normalize_base_url
from app.instances.registry import InstancePersistenceError, InstanceRegistry

router = APIRouter(prefix="/api/iris", tags=["instances"])


class InstancesResponse(BaseModel):
    instances: list[InstanceView]


class InstanceTestRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    base_url: str
    username: str = Field(min_length=1, max_length=160)
    password: SecretStr
    namespace: str = Field(default="USER", min_length=1, max_length=64)

    @field_validator("base_url")
    @classmethod
    def _url(cls, value: str) -> str:
        return normalize_base_url(value)


class InstanceCreateRequest(BaseModel):
    """confirmed=true is required; there's no force/skip field."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str
    base_url: str
    username: str
    password: SecretStr
    namespace: str = "USER"
    confirmed: bool = False
    dry_run: bool = False


class InstanceUpdateRequest(BaseModel):
    """Only the fields given are changed; a blank password keeps the stored one."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str | None = None
    base_url: str | None = None
    username: str | None = None
    namespace: str | None = None
    password: SecretStr | None = None
    confirmed: bool = False
    dry_run: bool = False


class InstanceActionRequest(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    confirmed: bool = False
    dry_run: bool = False


async def _run(
    operation_name: str,
    handler,
    parameters: dict,
    privileges: frozenset[str],
    confirmed: bool,
    dry_run: bool,
) -> OperationResult:
    executor = OperationExecutor({operation_name: handler})
    return await executor.execute(
        OperationRequest(operation_name=operation_name, parameters=parameters),
        ExecutionContext(available_privileges=privileges, confirmation_received=confirmed, dry_run=dry_run),
    )


@router.get("/instances", response_model=InstancesResponse)
async def list_instances(registry: InstanceRegistry = Depends(get_instance_registry)) -> InstancesResponse:
    return InstancesResponse(instances=[InstanceView.of(i) for i in registry.list()])


@router.get("/instances/{instance_id}", response_model=InstanceView)
async def get_instance(
    instance_id: str, registry: InstanceRegistry = Depends(get_instance_registry)
) -> InstanceView:
    instance = registry.get(instance_id)
    if instance is None:
        raise HTTPException(status_code=404, detail="No instance with this id.")
    return InstanceView.of(instance)


@router.post("/instances/test", response_model=InstanceCheck)
async def test_instance_connection(
    body: InstanceTestRequest, settings: Settings = Depends(get_settings)
) -> InstanceCheck:
    """Live compatibility check of an unsaved definition. Nothing is stored."""
    return await check_connection(
        base_url=body.base_url, username=body.username, password=body.password,
        namespace=body.namespace, settings=settings,
    )


@router.post("/instances", response_model=OperationResult)
async def create_instance(
    body: InstanceCreateRequest,
    registry: InstanceRegistry = Depends(get_instance_registry),
    store: WalletCredentialStore = Depends(get_credential_store),
    settings: Settings = Depends(get_settings),
    privileges: frozenset[str] = Depends(get_caller_privileges),
) -> OperationResult:
    parameters = body.model_dump(exclude={"confirmed", "dry_run", "password"}) | {"password": body.password}
    return await _run(
        "instance.create", InstanceCreateHandler(registry, store, settings),
        parameters, privileges, body.confirmed, body.dry_run,
    )


@router.put("/instances/{instance_id}", response_model=OperationResult)
async def update_instance(
    instance_id: str,
    body: InstanceUpdateRequest,
    registry: InstanceRegistry = Depends(get_instance_registry),
    store: WalletCredentialStore = Depends(get_credential_store),
    settings: Settings = Depends(get_settings),
    privileges: frozenset[str] = Depends(get_caller_privileges),
) -> OperationResult:
    fields = body.model_dump(exclude={"confirmed", "dry_run", "password"}, exclude_none=True)
    parameters = {"instance_id": instance_id, **fields, "password": body.password}
    return await _run(
        "instance.update", InstanceUpdateHandler(registry, store, settings),
        parameters, privileges, body.confirmed, body.dry_run,
    )


@router.post("/instances/{instance_id}/check", response_model=InstanceView)
async def check_saved_instance(
    instance_id: str,
    registry: InstanceRegistry = Depends(get_instance_registry),
    store: WalletCredentialStore = Depends(get_credential_store),
    settings: Settings = Depends(get_settings),
) -> InstanceView:
    """Live check of a registered instance; the result is stored as its last_check."""
    instance = registry.get(instance_id)
    if instance is None:
        raise HTTPException(status_code=404, detail="No instance with this id.")
    check = await check_instance(instance, settings, store)
    try:
        return InstanceView.of(registry.record_check(instance_id, check))
    except InstancePersistenceError:
        raise HTTPException(status_code=502, detail="The check result could not be saved to IRIS.") from None


async def _set_active(instance_id, active, body, registry, store, settings, privileges) -> OperationResult:
    return await _run(
        "instance.set_active", InstanceSetActiveHandler(registry, store, settings),
        {"instance_id": instance_id, "active": active}, privileges, body.confirmed, body.dry_run,
    )


@router.post("/instances/{instance_id}/activate", response_model=OperationResult)
async def activate_instance(
    instance_id: str,
    body: InstanceActionRequest,
    registry: InstanceRegistry = Depends(get_instance_registry),
    store: WalletCredentialStore = Depends(get_credential_store),
    settings: Settings = Depends(get_settings),
    privileges: frozenset[str] = Depends(get_caller_privileges),
) -> OperationResult:
    return await _set_active(instance_id, True, body, registry, store, settings, privileges)


@router.post("/instances/{instance_id}/deactivate", response_model=OperationResult)
async def deactivate_instance(
    instance_id: str,
    body: InstanceActionRequest,
    registry: InstanceRegistry = Depends(get_instance_registry),
    store: WalletCredentialStore = Depends(get_credential_store),
    settings: Settings = Depends(get_settings),
    privileges: frozenset[str] = Depends(get_caller_privileges),
) -> OperationResult:
    return await _set_active(instance_id, False, body, registry, store, settings, privileges)


@router.delete("/instances/{instance_id}", response_model=OperationResult)
async def delete_instance(
    instance_id: str,
    body: InstanceActionRequest,
    registry: InstanceRegistry = Depends(get_instance_registry),
    store: WalletCredentialStore = Depends(get_credential_store),
    settings: Settings = Depends(get_settings),
    privileges: frozenset[str] = Depends(get_caller_privileges),
) -> OperationResult:
    return await _run(
        "instance.delete", InstanceDeleteHandler(registry, store, settings),
        {"instance_id": instance_id}, privileges, body.confirmed, body.dry_run,
    )
