"""Tests for database.create. Everything runs against a mocked IRISClient."""

from typing import Any
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from app.execution.database_create_handler import (
    DatabaseCreateHandler,
    DatabaseCreateParameters,
)
from app.execution.executor import OperationExecutor
from app.execution.models import (
    ExecutionContext,
    HandlerOutcome,
    OperationRequest,
    OperationResultStatus,
    PostActionVerificationStatus,
)
from app.iris_client.exceptions import IRISConnectionError, IRISResponseError

_OPERATION_NAME = "database.create"


def _databases_body(entries: list[dict[str, Any]]) -> dict[str, Any]:
    """GET /v2/databases response listing the given databases."""
    return {
        "status": {"errors": [], "summary": ""},
        "console": [],
        "result": [
            {
                "Name": entry["Name"],
                "Directory": entry.get("Directory", f"/usr/irissys/mgr/{entry['Name'].lower()}/"),
                "Server": entry.get("Server", ""),
                "ClusterMountMode": entry.get("ClusterMountMode", False),
                "MountRequired": entry.get("MountRequired", True),
                "MountAtStartup": entry.get("MountAtStartup", True),
                "StreamLocation": entry.get("StreamLocation", ""),
                "Status": entry.get("Status", "Mounted/RW"),
            }
            for entry in entries
        ],
    }


_DEFAULT_EXISTING_DATABASES = _databases_body(
    [{"Name": "IRISSYS"}, {"Name": "IRISLIB"}, {"Name": "IRISTEMP"}, {"Name": "USER"}]
)


def _database_dir_found(
    *,
    resource_name: str | None = "%DB_MYDB",
    read_only: bool = False,
    global_journal_state: bool = False,
    cluster_mount_mode: bool = False,
) -> dict[str, Any]:
    """GET /v2/database-dir?dir= response for a database that exists (no
    Name/Directory/Status, unlike the /v2/databases entries). "Not found" is
    an IRISResponseError(404) in the test's side_effect instead.
    """
    return {
        "status": {"errors": [], "summary": ""},
        "console": [],
        "result": {
            "MaxSize": 0,
            "ExpansionSize": 0,
            "NewVolumeThreshold": 0,
            "NewVolumeDirectory": "/usr/irissys/mgr/mydb/",
            "ResourceName": resource_name,
            "NewGlobalIsKeep": False,
            "NewGlobalCollation": 5,
            "ClusterMountMode": cluster_mount_mode,
            "ReadOnly": read_only,
            "GlobalJournalState": global_journal_state,
        },
    }


@pytest.fixture
def fake_iris_client() -> AsyncMock:
    """Fake client: GET lists IRISSYS, IRISLIB, IRISTEMP and USER, POST
    succeeds. Tests override either as needed.
    """
    client = AsyncMock()
    client.get.side_effect = [_DEFAULT_EXISTING_DATABASES]
    client.post.return_value = {
        "status": {"errors": [], "summary": ""},
        "console": [],
        "result": {"ResourceName": "%DB_MYDB"},
    }
    return client


@pytest.fixture
def executor(fake_iris_client: AsyncMock) -> OperationExecutor:
    handler = DatabaseCreateHandler(fake_iris_client)
    return OperationExecutor({_OPERATION_NAME: handler})


def _request(
    *,
    directory: str = "/usr/irissys/mgr/mydb/",
    resource_name: str | None = None,
    size: int | None = None,
    global_journal_state: bool | None = None,
    encrypted: bool | None = None,
) -> OperationRequest:
    params: dict[str, Any] = {"Directory": directory}
    if resource_name is not None:
        params["ResourceName"] = resource_name
    if size is not None:
        params["Size"] = size
    if global_journal_state is not None:
        params["GlobalJournalState"] = global_journal_state
    if encrypted is not None:
        params["Encrypted"] = encrypted
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
    fake_iris_client.post.assert_not_awaited()


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
    fake_iris_client.post.assert_not_awaited()


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
    fake_iris_client.post.assert_not_awaited()


# --- dry-run ---


@pytest.mark.asyncio
async def test_confirmation_and_dry_run_never_calls_post(
    executor: OperationExecutor, fake_iris_client: AsyncMock
) -> None:
    result = await executor.execute(
        _request(),
        _context(privileges=frozenset({"Manage"}), confirmed=True, dry_run=True),
    )

    assert result.status is OperationResultStatus.DRY_RUN
    fake_iris_client.post.assert_not_awaited()
    assert fake_iris_client.get.await_count == 1  # databases validation read only
    assert result.handler_result is not None
    assert result.handler_result.outcome is HandlerOutcome.SUCCESS
    assert result.handler_result.data["directory"] == "/usr/irissys/mgr/mydb/"
    assert result.verification is None


# --- successful execution ---


@pytest.mark.asyncio
async def test_confirmation_and_execution_calls_post_with_correct_body(
    fake_iris_client: AsyncMock,
) -> None:
    # A real run does two GETs: /v2/databases to validate, then
    # /v2/database-dir?dir=... to verify (found first time).
    fake_iris_client.get.side_effect = [
        _DEFAULT_EXISTING_DATABASES,
        _database_dir_found(),
    ]
    handler = DatabaseCreateHandler(fake_iris_client)
    executor = OperationExecutor({_OPERATION_NAME: handler})

    result = await executor.execute(
        _request(directory="/usr/irissys/mgr/mydb/"),
        _context(privileges=frozenset({"Manage"}), confirmed=True, dry_run=False),
    )

    assert result.status is OperationResultStatus.SUCCESS
    fake_iris_client.post.assert_awaited_once_with(
        "/v2/database-dir", json={"Directory": "/usr/irissys/mgr/mydb/"}
    )


@pytest.mark.asyncio
async def test_optional_fields_included_in_post_body_when_provided(
    fake_iris_client: AsyncMock,
) -> None:
    fake_iris_client.get.side_effect = [
        _DEFAULT_EXISTING_DATABASES,
        _database_dir_found(),
    ]
    handler = DatabaseCreateHandler(fake_iris_client)
    executor = OperationExecutor({_OPERATION_NAME: handler})

    await executor.execute(
        _request(
            directory="/usr/irissys/mgr/mydb/",
            resource_name="%DB_MYDB",
            size=100,
            global_journal_state=True,
            encrypted=False,
        ),
        _context(privileges=frozenset({"Manage"}), confirmed=True, dry_run=False),
    )

    fake_iris_client.post.assert_awaited_once_with(
        "/v2/database-dir",
        json={
            "Directory": "/usr/irissys/mgr/mydb/",
            "ResourceName": "%DB_MYDB",
            "Size": 100,
            "GlobalJournalState": True,
            "Encrypted": False,
        },
    )


# --- post-action verification ---
#
# verify() used to look in GET /v2/databases, which never lists databases
# created with POST /v2/database-dir, so it always failed. It now uses
# GET /v2/database-dir?dir=, where "not found" is a 404.


@pytest.mark.asyncio
async def test_verification_succeeds_when_database_appears_at_requested_directory(
    fake_iris_client: AsyncMock,
) -> None:
    fake_iris_client.get.side_effect = [
        _DEFAULT_EXISTING_DATABASES,
        _database_dir_found(resource_name="%DB_MYDB"),
    ]
    handler = DatabaseCreateHandler(fake_iris_client)
    executor = OperationExecutor({_OPERATION_NAME: handler})

    result = await executor.execute(
        _request(directory="/usr/irissys/mgr/mydb/"),
        _context(privileges=frozenset({"Manage"}), confirmed=True, dry_run=False),
    )

    assert result.status is OperationResultStatus.SUCCESS
    assert result.verification is not None
    assert result.verification.status is PostActionVerificationStatus.VERIFIED
    assert "/usr/irissys/mgr/mydb/" in result.verification.detail
    assert "database-dir" in result.verification.detail
    assert "%DB_MYDB" in result.verification.detail
    fake_iris_client.get.assert_awaited_with(
        "/v2/database-dir", params={"dir": "/usr/irissys/mgr/mydb/"}
    )


@pytest.mark.asyncio
async def test_verification_fails_when_database_not_found_after_creation(
    fake_iris_client: AsyncMock,
) -> None:
    """Still 404 after every retry (1 + 3 = 4 GETs) must fail, not pass."""
    fake_iris_client.get.side_effect = [
        _DEFAULT_EXISTING_DATABASES,
        IRISResponseError(404),  # attempt 1: 404
        IRISResponseError(404),  # attempt 2: 404
        IRISResponseError(404),  # attempt 3: 404
        IRISResponseError(404),  # attempt 4: 404
    ]
    # Zero delays so the test doesn't actually sleep; the retry count is the same.
    handler = DatabaseCreateHandler(fake_iris_client, verify_retry_delays_seconds=(0.0, 0.0, 0.0))
    executor = OperationExecutor({_OPERATION_NAME: handler})

    result = await executor.execute(
        _request(directory="/usr/irissys/mgr/mydb/"),
        _context(privileges=frozenset({"Manage"}), confirmed=True, dry_run=False),
    )

    assert result.status is OperationResultStatus.VERIFICATION_FAILED
    assert result.status is not OperationResultStatus.EXECUTION_FAILED
    assert result.verification is not None
    assert result.verification.status is PostActionVerificationStatus.VERIFICATION_FAILED
    assert "4 attempts" in result.verification.detail
    assert "database-dir" in result.verification.detail
    # 1 GET to validate + 4 to verify, no more.
    assert fake_iris_client.get.await_count == 5


@pytest.mark.asyncio
async def test_verification_succeeds_when_database_appears_on_a_later_retry(
    fake_iris_client: AsyncMock,
) -> None:
    """Database only shows up on the third check; verify() should keep trying
    and pass (same retry logic as namespace.create).
    """
    fake_iris_client.get.side_effect = [
        _DEFAULT_EXISTING_DATABASES,
        IRISResponseError(404),  # attempt 1: not there yet
        IRISResponseError(404),  # attempt 2: not there yet
        _database_dir_found(),  # attempt 3: found
    ]
    handler = DatabaseCreateHandler(fake_iris_client, verify_retry_delays_seconds=(0.0, 0.0, 0.0))
    executor = OperationExecutor({_OPERATION_NAME: handler})

    result = await executor.execute(
        _request(directory="/usr/irissys/mgr/mydb/"),
        _context(privileges=frozenset({"Manage"}), confirmed=True, dry_run=False),
    )

    assert result.status is OperationResultStatus.SUCCESS
    assert result.verification is not None
    assert result.verification.status is PostActionVerificationStatus.VERIFIED
    assert "3 attempts" in result.verification.detail
    # Stops as soon as it's found: 1 (validate) + 3 (verify).
    assert fake_iris_client.get.await_count == 4


@pytest.mark.asyncio
async def test_verification_retries_perform_no_mutation(fake_iris_client: AsyncMock) -> None:
    """Retries only re-read; the POST still happens exactly once."""
    fake_iris_client.get.side_effect = [
        _DEFAULT_EXISTING_DATABASES,
        IRISResponseError(404),  # attempt 1 — absent
        IRISResponseError(404),  # attempt 2 — absent
        IRISResponseError(404),  # attempt 3 — absent
        IRISResponseError(404),  # absent (out of retries)
    ]
    handler = DatabaseCreateHandler(fake_iris_client, verify_retry_delays_seconds=(0.0, 0.0, 0.0))
    executor = OperationExecutor({_OPERATION_NAME: handler})

    result = await executor.execute(
        _request(directory="/usr/irissys/mgr/mydb/"),
        _context(privileges=frozenset({"Manage"}), confirmed=True, dry_run=False),
    )

    assert result.status is OperationResultStatus.VERIFICATION_FAILED
    fake_iris_client.post.assert_awaited_once()
    assert fake_iris_client.get.await_count == 5


@pytest.mark.asyncio
async def test_verification_does_not_treat_unexpected_iris_errors_as_not_found(
    fake_iris_client: AsyncMock,
) -> None:
    """Only a 404 means "not there yet". A 500 during verify should propagate
    instead of being treated as missing.
    """
    fake_iris_client.get.side_effect = [
        _DEFAULT_EXISTING_DATABASES,
        IRISResponseError(500),
    ]
    handler = DatabaseCreateHandler(fake_iris_client)
    executor = OperationExecutor({_OPERATION_NAME: handler})

    with pytest.raises(IRISResponseError) as exc_info:
        await executor.execute(
            _request(directory="/usr/irissys/mgr/mydb/"),
            _context(privileges=frozenset({"Manage"}), confirmed=True, dry_run=False),
        )
    assert exc_info.value.status_code == 500
    # Not retried after the unexpected error.
    assert fake_iris_client.get.await_count == 2


# --- validation: required fields / format ---


def test_missing_directory_is_rejected_by_parameters_model() -> None:
    with pytest.raises(ValidationError):
        DatabaseCreateParameters.model_validate({})


def test_empty_directory_is_rejected() -> None:
    with pytest.raises(ValidationError):
        DatabaseCreateParameters.model_validate({"Directory": ""})


@pytest.mark.parametrize(
    "bad_directory",
    [
        "relative/path/",  # not absolute
        "usr/irissys/mgr/mydb/",  # not absolute
        "/usr/irissys/mgr/../mydb/",  # parent-traversal segment
        "/usr/irissys/../../etc/",  # parent-traversal segment
    ],
)
def test_invalid_directory_format_is_rejected(bad_directory: str) -> None:
    with pytest.raises(ValidationError):
        DatabaseCreateParameters.model_validate({"Directory": bad_directory})


def test_valid_directory_is_accepted() -> None:
    params = DatabaseCreateParameters.model_validate({"Directory": "/usr/irissys/mgr/mydb/"})
    assert params.Directory == "/usr/irissys/mgr/mydb/"


def test_negative_size_is_rejected() -> None:
    with pytest.raises(ValidationError):
        DatabaseCreateParameters.model_validate({"Directory": "/usr/irissys/mgr/mydb/", "Size": -1})


def test_empty_resource_name_is_rejected_when_provided() -> None:
    with pytest.raises(ValidationError):
        DatabaseCreateParameters.model_validate(
            {"Directory": "/usr/irissys/mgr/mydb/", "ResourceName": ""}
        )


@pytest.mark.asyncio
async def test_missing_directory_never_reaches_iris(
    executor: OperationExecutor, fake_iris_client: AsyncMock
) -> None:
    request = OperationRequest(operation_name=_OPERATION_NAME, parameters={})

    result = await executor.execute(
        request, _context(privileges=frozenset({"Manage"}), confirmed=True, dry_run=True)
    )

    assert result.status is OperationResultStatus.DRY_RUN
    assert result.handler_result is not None
    assert result.handler_result.outcome is HandlerOutcome.FAILURE
    fake_iris_client.get.assert_not_awaited()
    fake_iris_client.post.assert_not_awaited()


# --- validation against live data: collisions, system databases ---


@pytest.mark.asyncio
async def test_existing_directory_is_rejected(
    executor: OperationExecutor, fake_iris_client: AsyncMock
) -> None:
    result = await executor.execute(
        _request(directory="/usr/irissys/mgr/user/"),  # USER's real directory
        _context(privileges=frozenset({"Manage"}), confirmed=True, dry_run=True),
    )

    assert result.handler_result is not None
    assert result.handler_result.outcome is HandlerOutcome.FAILURE
    assert "already exists" in result.handler_result.detail
    fake_iris_client.post.assert_not_awaited()


@pytest.mark.asyncio
async def test_existing_directory_is_rejected_ignoring_trailing_slash(
    executor: OperationExecutor, fake_iris_client: AsyncMock
) -> None:
    result = await executor.execute(
        _request(directory="/usr/irissys/mgr/user"),  # no trailing slash
        _context(privileges=frozenset({"Manage"}), confirmed=True, dry_run=True),
    )

    assert result.handler_result is not None
    assert result.handler_result.outcome is HandlerOutcome.FAILURE
    assert "already exists" in result.handler_result.detail
    fake_iris_client.post.assert_not_awaited()


@pytest.mark.asyncio
async def test_directory_deriving_to_an_existing_database_name_is_rejected(
    executor: OperationExecutor, fake_iris_client: AsyncMock
) -> None:
    """A different path whose last segment still derives to an existing name
    ("USER") is rejected.
    """
    result = await executor.execute(
        _request(directory="/some/other/path/user/"),
        _context(privileges=frozenset({"Manage"}), confirmed=True, dry_run=True),
    )

    assert result.handler_result is not None
    assert result.handler_result.outcome is HandlerOutcome.FAILURE
    assert "already exists" in result.handler_result.detail
    fake_iris_client.post.assert_not_awaited()


@pytest.mark.asyncio
async def test_directory_deriving_to_a_system_database_name_is_rejected(
    executor: OperationExecutor, fake_iris_client: AsyncMock
) -> None:
    """A path that derives to "IRISSYS" is rejected by the same collision
    check, since IRISSYS is already in the database list.
    """
    result = await executor.execute(
        _request(directory="/tmp/attempted/irissys/"),
        _context(privileges=frozenset({"Manage"}), confirmed=True, dry_run=True),
    )

    assert result.handler_result is not None
    assert result.handler_result.outcome is HandlerOutcome.FAILURE
    assert "IRISSYS" in result.handler_result.detail
    fake_iris_client.post.assert_not_awaited()


@pytest.mark.asyncio
async def test_new_nonconflicting_directory_passes_validation(
    executor: OperationExecutor, fake_iris_client: AsyncMock
) -> None:
    result = await executor.execute(
        _request(directory="/usr/irissys/mgr/mydb/"),
        _context(privileges=frozenset({"Manage"}), confirmed=True, dry_run=True),
    )

    assert result.status is OperationResultStatus.DRY_RUN
    assert result.handler_result is not None
    assert result.handler_result.outcome is HandlerOutcome.SUCCESS
    fake_iris_client.post.assert_not_awaited()


# --- unexpected IRIS failures ---


@pytest.mark.asyncio
async def test_post_raising_becomes_structured_execution_failure(
    fake_iris_client: AsyncMock,
) -> None:
    fake_iris_client.post.side_effect = IRISResponseError(500)
    handler = DatabaseCreateHandler(fake_iris_client)
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
    handler = DatabaseCreateHandler(fake_iris_client)
    executor = OperationExecutor({_OPERATION_NAME: handler})

    result = await executor.execute(
        _request(),
        _context(privileges=frozenset({"Manage"}), confirmed=True, dry_run=True),
    )

    assert result.status is OperationResultStatus.EXECUTION_FAILED
    fake_iris_client.post.assert_not_awaited()


# --- unknown operation / extra fields ---


@pytest.mark.asyncio
async def test_unknown_operation_is_still_denied(fake_iris_client: AsyncMock) -> None:
    handler = DatabaseCreateHandler(fake_iris_client)
    executor = OperationExecutor({_OPERATION_NAME: handler})

    result = await executor.execute(
        OperationRequest(operation_name="database.delete_everything", parameters={}),
        _context(privileges=frozenset({"Manage"}), confirmed=True),
    )

    assert result.status is OperationResultStatus.UNKNOWN_OPERATION
    fake_iris_client.get.assert_not_awaited()
    fake_iris_client.post.assert_not_awaited()


@pytest.mark.asyncio
async def test_extra_field_in_parameters_is_rejected_not_silently_dropped(
    executor: OperationExecutor, fake_iris_client: AsyncMock
) -> None:
    request = OperationRequest(
        operation_name=_OPERATION_NAME,
        parameters={
            "Directory": "/usr/irissys/mgr/mydb/",
            "Password": "attempted-smuggled-field",
        },
    )

    result = await executor.execute(
        request, _context(privileges=frozenset({"Manage"}), confirmed=True, dry_run=True)
    )

    assert result.handler_result is not None
    assert result.handler_result.outcome is HandlerOutcome.FAILURE
    fake_iris_client.get.assert_not_awaited()
    fake_iris_client.post.assert_not_awaited()


def test_parameters_model_rejects_extra_fields_directly() -> None:
    with pytest.raises(ValidationError):
        DatabaseCreateParameters.model_validate(
            {"Directory": "/usr/irissys/mgr/mydb/", "Password": "not-allowed"}
        )
