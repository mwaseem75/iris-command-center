"""Tests for namespace.create. Everything runs against a mocked IRISClient."""

from typing import Any
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from app.execution.executor import OperationExecutor
from app.execution.models import (
    ExecutionContext,
    HandlerOutcome,
    OperationRequest,
    OperationResultStatus,
    PostActionVerificationStatus,
)
from app.execution.namespace_create_handler import (
    NamespaceCreateHandler,
    NamespaceCreateParameters,
)
from app.iris_client.exceptions import IRISAsyncTaskError, IRISConnectionError, IRISResponseError

_OPERATION_NAME = "namespace.create"


def _namespaces_body(entries: list[dict[str, Any]]) -> dict[str, Any]:
    """GET /v2/namespaces response listing the given namespaces."""
    return {
        "status": {"errors": [], "summary": ""},
        "console": [],
        "result": [
            {
                "Name": entry["Name"],
                "Globals": entry.get("Globals", "USER"),
                "Routines": entry.get("Routines", "USER"),
                "SysGlobals": "IRISSYS",
                "SysRoutines": "IRISSYS",
                "Library": "IRISLIB",
                "TempGlobals": entry.get("TempGlobals", "IRISTEMP"),
            }
            for entry in entries
        ],
    }


def _databases_body(names: list[str]) -> dict[str, Any]:
    """GET /v2/databases response listing the given databases."""
    return {
        "status": {"errors": [], "summary": ""},
        "console": [],
        "result": [
            {
                "Name": name,
                "Directory": f"/usr/irissys/mgr/{name.lower()}/",
                "Server": "",
                "ClusterMountMode": False,
                "MountRequired": True,
                "MountAtStartup": True,
                "StreamLocation": "",
                "Status": "Mounted/RW",
            }
            for name in names
        ],
    }


_DEFAULT_EXISTING_NAMESPACES = _namespaces_body(
    [{"Name": "%SYS", "Globals": "IRISSYS", "Routines": "IRISSYS"}, {"Name": "USER", "Globals": "USER", "Routines": "USER"}]
)
_DEFAULT_EXISTING_DATABASES = _databases_body(["USER", "IRISTEMP", "IRISLIB", "IRISSYS"])


@pytest.fixture
def fake_iris_client() -> AsyncMock:
    """Fake client: GET lists %SYS and USER plus four databases; PUT and the
    enable-interop task succeed. Tests override as needed.
    """
    client = AsyncMock()
    client.get.side_effect = [_DEFAULT_EXISTING_NAMESPACES, _DEFAULT_EXISTING_DATABASES]
    client.put.return_value = {
        "status": {"errors": [], "summary": ""},
        "console": [],
        "result": {"Globals": "USER", "Routines": "USER", "TempGlobals": "IRISTEMP"},
    }
    client.post_async_task.return_value = "task-123"
    client.wait_for_async_task.return_value = {"State": "Finished"}
    return client


@pytest.fixture
def executor(fake_iris_client: AsyncMock) -> OperationExecutor:
    handler = NamespaceCreateHandler(fake_iris_client)
    return OperationExecutor({_OPERATION_NAME: handler})


def _request(
    *,
    name: str = "NEWAPP",
    globals_db: str = "USER",
    routines_db: str = "USER",
    temp_globals: str | None = None,
    interop: bool = False,
) -> OperationRequest:
    params: dict[str, Any] = {"Name": name, "Globals": globals_db, "Routines": routines_db, "Interop": interop}
    if temp_globals is not None:
        params["TempGlobals"] = temp_globals
    return OperationRequest(operation_name=_OPERATION_NAME, parameters=params)


def _context(
    *, privileges: frozenset[str], confirmed: bool = False, dry_run: bool = False
) -> ExecutionContext:
    return ExecutionContext(
        available_privileges=privileges, confirmation_received=confirmed, dry_run=dry_run
    )


# --- authorization ---


@pytest.mark.asyncio
async def test_no_privilege_is_denied(
    executor: OperationExecutor, fake_iris_client: AsyncMock
) -> None:
    result = await executor.execute(_request(), _context(privileges=frozenset()))

    assert result.status is OperationResultStatus.UNAUTHORIZED
    fake_iris_client.get.assert_not_awaited()
    fake_iris_client.put.assert_not_awaited()


@pytest.mark.asyncio
async def test_manage_privilege_is_authorized(executor: OperationExecutor) -> None:
    result = await executor.execute(
        _request(), _context(privileges=frozenset({"Manage"}), confirmed=True, dry_run=True)
    )

    assert result.authorization is not None
    assert result.authorization.authorized is True
    assert result.status is OperationResultStatus.DRY_RUN


@pytest.mark.asyncio
async def test_unrelated_privilege_is_denied(
    executor: OperationExecutor, fake_iris_client: AsyncMock
) -> None:
    result = await executor.execute(
        _request(), _context(privileges=frozenset({"Operate", "Journal"}), confirmed=True)
    )

    assert result.status is OperationResultStatus.UNAUTHORIZED
    fake_iris_client.put.assert_not_awaited()


# --- confirmation ---


@pytest.mark.asyncio
async def test_no_confirmation_blocks_before_any_iris_call(
    executor: OperationExecutor, fake_iris_client: AsyncMock
) -> None:
    result = await executor.execute(
        _request(), _context(privileges=frozenset({"Manage"}), confirmed=False, dry_run=False)
    )

    assert result.status is OperationResultStatus.CONFIRMATION_REQUIRED
    fake_iris_client.get.assert_not_awaited()
    fake_iris_client.put.assert_not_awaited()


# --- dry-run ---


@pytest.mark.asyncio
async def test_confirmation_and_dry_run_never_calls_put_or_enable_interop(
    fake_iris_client: AsyncMock,
) -> None:
    handler = NamespaceCreateHandler(fake_iris_client)
    executor = OperationExecutor({_OPERATION_NAME: handler})

    result = await executor.execute(
        _request(interop=True),
        _context(privileges=frozenset({"Manage"}), confirmed=True, dry_run=True),
    )

    assert result.status is OperationResultStatus.DRY_RUN
    fake_iris_client.put.assert_not_awaited()
    fake_iris_client.post_async_task.assert_not_awaited()
    fake_iris_client.wait_for_async_task.assert_not_awaited()
    assert fake_iris_client.get.await_count == 2  # namespaces + databases validation reads only
    assert result.handler_result is not None
    assert result.handler_result.outcome is HandlerOutcome.SUCCESS
    assert result.handler_result.data["interop_requested"] is True
    assert result.verification is None


# --- successful execution ---


@pytest.mark.asyncio
async def test_confirmation_and_execution_calls_put_with_correct_body(
    fake_iris_client: AsyncMock,
) -> None:
    # A real run does three GETs: namespaces + databases to validate, then
    # namespaces again to verify.
    fake_iris_client.get.side_effect = [
        _DEFAULT_EXISTING_NAMESPACES,
        _DEFAULT_EXISTING_DATABASES,
        _namespaces_body(
            [
                {"Name": "%SYS", "Globals": "IRISSYS", "Routines": "IRISSYS"},
                {"Name": "USER", "Globals": "USER", "Routines": "USER"},
                {"Name": "NEWAPP", "Globals": "USER", "Routines": "USER", "TempGlobals": "IRISTEMP"},
            ]
        ),
    ]
    handler = NamespaceCreateHandler(fake_iris_client)
    executor = OperationExecutor({_OPERATION_NAME: handler})

    result = await executor.execute(
        _request(name="NEWAPP", globals_db="USER", routines_db="USER"),
        _context(privileges=frozenset({"Manage"}), confirmed=True, dry_run=False),
    )

    assert result.status is OperationResultStatus.SUCCESS
    fake_iris_client.put.assert_awaited_once_with(
        "/v2/namespace?name=NEWAPP", json={"Globals": "USER", "Routines": "USER"}
    )
    fake_iris_client.post_async_task.assert_not_awaited()  # Interop defaults to False


@pytest.mark.asyncio
async def test_temp_globals_included_in_put_body_when_provided(
    fake_iris_client: AsyncMock,
) -> None:
    fake_iris_client.get.side_effect = [
        _DEFAULT_EXISTING_NAMESPACES,
        _DEFAULT_EXISTING_DATABASES,
        _namespaces_body(
            [{"Name": "NEWAPP", "Globals": "USER", "Routines": "USER", "TempGlobals": "IRISTEMP"}]
        ),
    ]
    handler = NamespaceCreateHandler(fake_iris_client)
    executor = OperationExecutor({_OPERATION_NAME: handler})

    await executor.execute(
        _request(name="NEWAPP", temp_globals="IRISTEMP"),
        _context(privileges=frozenset({"Manage"}), confirmed=True, dry_run=False),
    )

    fake_iris_client.put.assert_awaited_once_with(
        "/v2/namespace?name=NEWAPP",
        json={"Globals": "USER", "Routines": "USER", "TempGlobals": "IRISTEMP"},
    )


# --- post-action verification ---


@pytest.mark.asyncio
async def test_verification_succeeds_when_namespace_appears_with_matching_fields(
    fake_iris_client: AsyncMock,
) -> None:
    fake_iris_client.get.side_effect = [
        _DEFAULT_EXISTING_NAMESPACES,
        _DEFAULT_EXISTING_DATABASES,
        _namespaces_body(
            [{"Name": "%SYS"}, {"Name": "USER"}, {"Name": "NEWAPP", "Globals": "USER", "Routines": "USER"}]
        ),
    ]
    handler = NamespaceCreateHandler(fake_iris_client)
    executor = OperationExecutor({_OPERATION_NAME: handler})

    result = await executor.execute(
        _request(name="NEWAPP"),
        _context(privileges=frozenset({"Manage"}), confirmed=True, dry_run=False),
    )

    assert result.status is OperationResultStatus.SUCCESS
    assert result.verification is not None
    assert result.verification.status is PostActionVerificationStatus.VERIFIED


@pytest.mark.asyncio
async def test_verification_fails_when_namespace_not_found_after_creation(
    fake_iris_client: AsyncMock,
) -> None:
    """NEWAPP missing on every retry (1 + 3 = 4 GETs) must fail, not pass."""
    fake_iris_client.get.side_effect = [
        _DEFAULT_EXISTING_NAMESPACES,
        _DEFAULT_EXISTING_DATABASES,
        _DEFAULT_EXISTING_NAMESPACES,  # attempt 1: missing
        _DEFAULT_EXISTING_NAMESPACES,  # attempt 2: missing
        _DEFAULT_EXISTING_NAMESPACES,  # attempt 3: missing
        _DEFAULT_EXISTING_NAMESPACES,  # attempt 4: missing
    ]
    # Zero delays so the test doesn't actually sleep; the retry count is the same.
    handler = NamespaceCreateHandler(fake_iris_client, verify_retry_delays_seconds=(0.0, 0.0, 0.0))
    executor = OperationExecutor({_OPERATION_NAME: handler})

    result = await executor.execute(
        _request(name="NEWAPP"),
        _context(privileges=frozenset({"Manage"}), confirmed=True, dry_run=False),
    )

    assert result.status is OperationResultStatus.VERIFICATION_FAILED
    assert result.status is not OperationResultStatus.EXECUTION_FAILED
    assert result.verification is not None
    assert result.verification.status is PostActionVerificationStatus.VERIFICATION_FAILED
    assert "4 attempts" in result.verification.detail
    # 2 GETs from _validate() + 4 from verify, no more.
    assert fake_iris_client.get.await_count == 6


@pytest.mark.asyncio
async def test_verification_fails_when_fields_do_not_match_request(
    fake_iris_client: AsyncMock,
) -> None:
    fake_iris_client.get.side_effect = [
        _DEFAULT_EXISTING_NAMESPACES,
        _DEFAULT_EXISTING_DATABASES,
        # NEWAPP exists but with the wrong Routines database
        _namespaces_body([{"Name": "NEWAPP", "Globals": "USER", "Routines": "IRISLIB"}]),
    ]
    handler = NamespaceCreateHandler(fake_iris_client)
    executor = OperationExecutor({_OPERATION_NAME: handler})

    result = await executor.execute(
        _request(name="NEWAPP", globals_db="USER", routines_db="USER"),
        _context(privileges=frozenset({"Manage"}), confirmed=True, dry_run=False),
    )

    assert result.status is OperationResultStatus.VERIFICATION_FAILED
    assert "Routines" in result.verification.detail


@pytest.mark.asyncio
async def test_verification_succeeds_when_iris_returns_a_different_casing(
    fake_iris_client: AsyncMock,
) -> None:
    """IRIS stores "tttt" as "TTTT" (seen on a real instance). verify() used to
    compare case-sensitively and fail here; it should pass.
    """
    fake_iris_client.get.side_effect = [
        _DEFAULT_EXISTING_NAMESPACES,
        _DEFAULT_EXISTING_DATABASES,
        _namespaces_body(
            [{"Name": "%SYS"}, {"Name": "USER"}, {"Name": "TTTT", "Globals": "USER", "Routines": "USER"}]
        ),
    ]
    handler = NamespaceCreateHandler(fake_iris_client)
    executor = OperationExecutor({_OPERATION_NAME: handler})

    result = await executor.execute(
        _request(name="tttt"),
        _context(privileges=frozenset({"Manage"}), confirmed=True, dry_run=False),
    )

    assert result.status is OperationResultStatus.SUCCESS
    assert result.verification is not None
    assert result.verification.status is PostActionVerificationStatus.VERIFIED
    # The detail shows the name as IRIS returned it, not the input casing.
    assert "TTTT" in result.verification.detail


@pytest.mark.asyncio
async def test_verification_still_fails_when_namespace_genuinely_absent_under_any_casing(
    fake_iris_client: AsyncMock,
) -> None:
    """Case-insensitive matching must not make verify always pass: a
    namespace that never appears still fails.
    """
    fake_iris_client.get.side_effect = [
        _DEFAULT_EXISTING_NAMESPACES,
        _DEFAULT_EXISTING_DATABASES,
        _DEFAULT_EXISTING_NAMESPACES,  # attempt 1: missing
        _DEFAULT_EXISTING_NAMESPACES,  # attempt 2
        _DEFAULT_EXISTING_NAMESPACES,  # attempt 3
        _DEFAULT_EXISTING_NAMESPACES,  # attempt 4
    ]
    handler = NamespaceCreateHandler(fake_iris_client, verify_retry_delays_seconds=(0.0, 0.0, 0.0))
    executor = OperationExecutor({_OPERATION_NAME: handler})

    result = await executor.execute(
        _request(name="NEWAPP"),
        _context(privileges=frozenset({"Manage"}), confirmed=True, dry_run=False),
    )

    assert result.status is OperationResultStatus.VERIFICATION_FAILED
    assert result.verification is not None
    assert result.verification.status is PostActionVerificationStatus.VERIFICATION_FAILED


@pytest.mark.asyncio
async def test_verification_succeeds_when_namespace_appears_on_a_later_retry(
    fake_iris_client: AsyncMock,
) -> None:
    """Namespace only shows up on the third check (IRIS can be slow to list a
    new namespace). verify() should keep trying and pass.
    """
    fake_iris_client.get.side_effect = [
        _DEFAULT_EXISTING_NAMESPACES,
        _DEFAULT_EXISTING_DATABASES,
        _DEFAULT_EXISTING_NAMESPACES,  # attempt 1: not there yet
        _DEFAULT_EXISTING_NAMESPACES,  # attempt 2: not there yet
        _namespaces_body(  # attempt 3: found
            [{"Name": "%SYS"}, {"Name": "USER"}, {"Name": "NEWAPP", "Globals": "USER", "Routines": "USER"}]
        ),
    ]
    handler = NamespaceCreateHandler(fake_iris_client, verify_retry_delays_seconds=(0.0, 0.0, 0.0))
    executor = OperationExecutor({_OPERATION_NAME: handler})

    result = await executor.execute(
        _request(name="NEWAPP"),
        _context(privileges=frozenset({"Manage"}), confirmed=True, dry_run=False),
    )

    assert result.status is OperationResultStatus.SUCCESS
    assert result.verification is not None
    assert result.verification.status is PostActionVerificationStatus.VERIFIED
    assert "3 attempts" in result.verification.detail
    # Stopped as soon as it was found; the 4th response was never used.
    assert fake_iris_client.get.await_count == 5


@pytest.mark.asyncio
async def test_verification_retries_perform_no_mutation(fake_iris_client: AsyncMock) -> None:
    """Retries only re-read; the PUT and the enable-interop task still run
    exactly once.
    """
    fake_iris_client.get.side_effect = [
        _DEFAULT_EXISTING_NAMESPACES,
        _DEFAULT_EXISTING_DATABASES,
        _DEFAULT_EXISTING_NAMESPACES,  # attempt 1 — absent
        _DEFAULT_EXISTING_NAMESPACES,  # attempt 2 — absent
        _DEFAULT_EXISTING_NAMESPACES,  # attempt 3 — absent
        _DEFAULT_EXISTING_NAMESPACES,  # absent (out of retries)
    ]
    handler = NamespaceCreateHandler(fake_iris_client, verify_retry_delays_seconds=(0.0, 0.0, 0.0))
    executor = OperationExecutor({_OPERATION_NAME: handler})

    result = await executor.execute(
        _request(name="NEWAPP", interop=True),
        _context(privileges=frozenset({"Manage"}), confirmed=True, dry_run=False),
    )

    assert result.status is OperationResultStatus.VERIFICATION_FAILED
    fake_iris_client.put.assert_awaited_once()
    fake_iris_client.post_async_task.assert_awaited_once()
    fake_iris_client.wait_for_async_task.assert_awaited_once()
    # 2 (validate) + 4 (verify) GETs, and no extra PUT/POST.
    assert fake_iris_client.get.await_count == 6


# --- validation: required fields / format / system-namespace rejection ---


@pytest.mark.parametrize("missing_field", ["Name", "Globals", "Routines"])
def test_missing_required_field_is_rejected_by_parameters_model(missing_field: str) -> None:
    params = {"Name": "NEWAPP", "Globals": "USER", "Routines": "USER"}
    del params[missing_field]

    with pytest.raises(ValidationError):
        NamespaceCreateParameters.model_validate(params)


def test_empty_required_field_is_rejected() -> None:
    with pytest.raises(ValidationError):
        NamespaceCreateParameters.model_validate({"Name": "NEWAPP", "Globals": "", "Routines": "USER"})


@pytest.mark.parametrize("bad_name", ["%CUSTOM", "%SYS"])
def test_system_prefixed_name_is_rejected(bad_name: str) -> None:
    with pytest.raises(ValidationError, match="System-namespace"):
        NamespaceCreateParameters.model_validate({"Name": bad_name, "Globals": "USER", "Routines": "USER"})


@pytest.mark.parametrize("bad_name", ["", "1STARTSWITHDIGIT", "has space", "has-dash", "has.dot", "a" * 32])
def test_invalid_name_format_is_rejected(bad_name: str) -> None:
    with pytest.raises(ValidationError):
        NamespaceCreateParameters.model_validate({"Name": bad_name, "Globals": "USER", "Routines": "USER"})


def test_valid_name_format_is_accepted() -> None:
    params = NamespaceCreateParameters.model_validate(
        {"Name": "My_App2", "Globals": "USER", "Routines": "USER"}
    )
    assert params.Name == "My_App2"


@pytest.mark.asyncio
async def test_missing_field_never_reaches_iris(
    executor: OperationExecutor, fake_iris_client: AsyncMock
) -> None:
    request = OperationRequest(
        operation_name=_OPERATION_NAME, parameters={"Name": "NEWAPP", "Globals": "USER"}
    )

    result = await executor.execute(
        request, _context(privileges=frozenset({"Manage"}), confirmed=True, dry_run=True)
    )

    assert result.status is OperationResultStatus.DRY_RUN
    assert result.handler_result is not None
    assert result.handler_result.outcome is HandlerOutcome.FAILURE
    fake_iris_client.get.assert_not_awaited()
    fake_iris_client.put.assert_not_awaited()


# --- validation against live data: existing namespace, databases ---


@pytest.mark.asyncio
async def test_existing_namespace_name_is_rejected(
    executor: OperationExecutor, fake_iris_client: AsyncMock
) -> None:
    result = await executor.execute(
        _request(name="USER"),  # already exists
        _context(privileges=frozenset({"Manage"}), confirmed=True, dry_run=True),
    )

    assert result.handler_result is not None
    assert result.handler_result.outcome is HandlerOutcome.FAILURE
    assert "already exists" in result.handler_result.detail
    fake_iris_client.put.assert_not_awaited()


@pytest.mark.asyncio
async def test_existing_namespace_name_is_rejected_regardless_of_casing(
    executor: OperationExecutor, fake_iris_client: AsyncMock
) -> None:
    """"user" collides with the existing "USER", since names are
    case-insensitive.
    """
    result = await executor.execute(
        _request(name="user"),
        _context(privileges=frozenset({"Manage"}), confirmed=True, dry_run=True),
    )

    assert result.handler_result is not None
    assert result.handler_result.outcome is HandlerOutcome.FAILURE
    assert "already exists" in result.handler_result.detail
    fake_iris_client.put.assert_not_awaited()


@pytest.mark.asyncio
async def test_nonexistent_globals_database_is_rejected(
    executor: OperationExecutor, fake_iris_client: AsyncMock
) -> None:
    result = await executor.execute(
        _request(globals_db="DOES_NOT_EXIST"),
        _context(privileges=frozenset({"Manage"}), confirmed=True, dry_run=True),
    )

    assert result.handler_result is not None
    assert result.handler_result.outcome is HandlerOutcome.FAILURE
    assert "Globals database" in result.handler_result.detail
    fake_iris_client.put.assert_not_awaited()


@pytest.mark.asyncio
async def test_nonexistent_routines_database_is_rejected(
    executor: OperationExecutor, fake_iris_client: AsyncMock
) -> None:
    result = await executor.execute(
        _request(routines_db="DOES_NOT_EXIST"),
        _context(privileges=frozenset({"Manage"}), confirmed=True, dry_run=True),
    )

    assert result.handler_result is not None
    assert result.handler_result.outcome is HandlerOutcome.FAILURE
    assert "Routines database" in result.handler_result.detail


@pytest.mark.asyncio
async def test_nonexistent_temp_globals_database_is_rejected(
    executor: OperationExecutor, fake_iris_client: AsyncMock
) -> None:
    result = await executor.execute(
        _request(temp_globals="DOES_NOT_EXIST"),
        _context(privileges=frozenset({"Manage"}), confirmed=True, dry_run=True),
    )

    assert result.handler_result is not None
    assert result.handler_result.outcome is HandlerOutcome.FAILURE
    assert "TempGlobals database" in result.handler_result.detail


# --- Interop follow-up ---


@pytest.mark.asyncio
async def test_interop_flag_calls_enable_interop_after_create(
    fake_iris_client: AsyncMock,
) -> None:
    fake_iris_client.get.side_effect = [
        _DEFAULT_EXISTING_NAMESPACES,
        _DEFAULT_EXISTING_DATABASES,
        _namespaces_body([{"Name": "NEWAPP", "Globals": "USER", "Routines": "USER"}]),
    ]
    handler = NamespaceCreateHandler(fake_iris_client)
    executor = OperationExecutor({_OPERATION_NAME: handler})

    result = await executor.execute(
        _request(name="NEWAPP", interop=True),
        _context(privileges=frozenset({"Manage"}), confirmed=True, dry_run=False),
    )

    assert result.status is OperationResultStatus.SUCCESS
    fake_iris_client.post_async_task.assert_awaited_once_with("/v2/namespace/enable-interop?name=NEWAPP")
    fake_iris_client.wait_for_async_task.assert_awaited_once_with("task-123")
    assert result.handler_result.data["interop_enabled"] is True


@pytest.mark.asyncio
async def test_interop_failure_does_not_fail_the_overall_creation(
    fake_iris_client: AsyncMock,
) -> None:
    fake_iris_client.get.side_effect = [
        _DEFAULT_EXISTING_NAMESPACES,
        _DEFAULT_EXISTING_DATABASES,
        _namespaces_body([{"Name": "NEWAPP", "Globals": "USER", "Routines": "USER"}]),
    ]
    fake_iris_client.wait_for_async_task.side_effect = IRISAsyncTaskError(
        "simulated async task failure", state="Failed"
    )
    handler = NamespaceCreateHandler(fake_iris_client)
    executor = OperationExecutor({_OPERATION_NAME: handler})

    result = await executor.execute(
        _request(name="NEWAPP", interop=True),
        _context(privileges=frozenset({"Manage"}), confirmed=True, dry_run=False),
    )

    assert result.status is OperationResultStatus.SUCCESS  # namespace creation itself succeeded
    assert result.handler_result.data["interop_enabled"] is False
    assert "enabling interoperability failed" in result.handler_result.detail


# --- unexpected IRIS failures ---


@pytest.mark.asyncio
async def test_put_raising_becomes_structured_execution_failure(
    fake_iris_client: AsyncMock,
) -> None:
    fake_iris_client.put.side_effect = IRISResponseError(500)
    handler = NamespaceCreateHandler(fake_iris_client)
    executor = OperationExecutor({_OPERATION_NAME: handler})

    result = await executor.execute(
        _request(),
        _context(privileges=frozenset({"Manage"}), confirmed=True, dry_run=False),
    )

    assert result.status is OperationResultStatus.EXECUTION_FAILED
    assert "credential" not in result.detail.lower()
    assert "password" not in result.detail.lower()


@pytest.mark.asyncio
async def test_dry_run_get_failure_becomes_structured_failure_not_a_crash(
    fake_iris_client: AsyncMock,
) -> None:
    fake_iris_client.get.side_effect = IRISConnectionError("simulated — no real network involved")
    handler = NamespaceCreateHandler(fake_iris_client)
    executor = OperationExecutor({_OPERATION_NAME: handler})

    result = await executor.execute(
        _request(),
        _context(privileges=frozenset({"Manage"}), confirmed=True, dry_run=True),
    )

    assert result.status is OperationResultStatus.EXECUTION_FAILED
    fake_iris_client.put.assert_not_awaited()


# --- unknown operation / extra fields ---


@pytest.mark.asyncio
async def test_unknown_operation_is_still_denied(fake_iris_client: AsyncMock) -> None:
    handler = NamespaceCreateHandler(fake_iris_client)
    executor = OperationExecutor({_OPERATION_NAME: handler})

    result = await executor.execute(
        OperationRequest(operation_name="namespace.delete_everything", parameters={}),
        _context(privileges=frozenset({"Manage"}), confirmed=True),
    )

    assert result.status is OperationResultStatus.UNKNOWN_OPERATION
    fake_iris_client.get.assert_not_awaited()
    fake_iris_client.put.assert_not_awaited()


@pytest.mark.asyncio
async def test_extra_field_in_parameters_is_rejected_not_silently_dropped(
    executor: OperationExecutor, fake_iris_client: AsyncMock
) -> None:
    request = OperationRequest(
        operation_name=_OPERATION_NAME,
        parameters={
            "Name": "NEWAPP",
            "Globals": "USER",
            "Routines": "USER",
            "Password": "attempted-smuggled-field",
        },
    )

    result = await executor.execute(
        request, _context(privileges=frozenset({"Manage"}), confirmed=True, dry_run=True)
    )

    assert result.handler_result is not None
    assert result.handler_result.outcome is HandlerOutcome.FAILURE
    fake_iris_client.get.assert_not_awaited()
    fake_iris_client.put.assert_not_awaited()


def test_parameters_model_rejects_extra_fields_directly() -> None:
    with pytest.raises(ValidationError):
        NamespaceCreateParameters.model_validate(
            {"Name": "NEWAPP", "Globals": "USER", "Routines": "USER", "Password": "not-allowed"}
        )
