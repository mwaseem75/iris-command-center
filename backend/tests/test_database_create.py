"""Tests for the database.create operation — this project's first
Database mutation. ALL tests here use a fake/mock IRISClient (an
AsyncMock with .get/.post), exactly like test_namespace_create.py. No test
in this file makes, or could make, a real network call, and no test
performs a real database creation — there is no real IRISClient
constructed anywhere in this file.
"""

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
    """A real-shaped GET /v2/databases envelope (matches
    docs/api-capability-matrix.md's verified response shape) listing
    whichever databases a test needs to already exist."""
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
    """A real-shaped GET /v2/database-dir?dir=<Directory> envelope — the
    exact LocalDatabase result shape confirmed live against icc-iris-dev
    (see database_create_handler.py's module docstring, "iccrehearsal"
    investigation): no Name/Directory/Status field, unlike GET
    /v2/databases' DatabaseEntry. Represents "IRIS reports a database
    exists at this directory" — used by verify()'s post-action checks.
    "Not found" (the endpoint's documented 404) is represented directly by
    an IRISResponseError(404) instance in a test's side_effect list, not
    by this helper."""
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
    """A fake client whose GET reports four pre-existing databases
    (IRISSYS, IRISLIB, IRISTEMP, USER) and whose POST succeeds with the
    documented (LocalDatabase) response shape — unless a test overrides
    either."""
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
    # GET is called twice by a real execution: GET /v2/databases
    # (validation), then GET /v2/database-dir?dir=... (post-action
    # verification, found on the first read).
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
# Regression coverage for the real "iccrehearsal" rehearsal bug: verify()
# used to poll GET /v2/databases (the persistent, CPF-registered list) and
# could never find a database POST /v2/database-dir genuinely created and
# mounted, because creation never adds a [Databases] CPF entry — confirmed
# live (see database_create_handler.py's module docstring). verify() now
# polls GET /v2/database-dir?dir=<Directory> instead — "not found" is that
# endpoint's own documented 404, represented here by an
# IRISResponseError(404) instance in a side_effect list (unittest.mock
# raises an exception instance/class placed in `side_effect`), never an
# absent-from-list entry.


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
    """Genuinely absent (IRIS's documented 404) across every retry
    attempt — the bounded-retry policy must not turn this into a false
    success. One GET per attempt: 1 immediate + 3 retries (see
    _VERIFY_RETRY_DELAYS_SECONDS) = 4 total, all still 404."""
    fake_iris_client.get.side_effect = [
        _DEFAULT_EXISTING_DATABASES,
        IRISResponseError(404),  # attempt 1 — still absent
        IRISResponseError(404),  # attempt 2 (1st retry) — still absent
        IRISResponseError(404),  # attempt 3 (2nd retry) — still absent
        IRISResponseError(404),  # attempt 4 (3rd retry) — still absent
    ]
    # Zero delays: exercises the exact same retry COUNT/logic as production
    # without the test actually sleeping ~1.7 real seconds.
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
    # 1 (validate) + 4 (verify retries) GETs — never more than the bounded
    # policy allows.
    assert fake_iris_client.get.await_count == 5


@pytest.mark.asyncio
async def test_verification_succeeds_when_database_appears_on_a_later_retry(
    fake_iris_client: AsyncMock,
) -> None:
    """Regression protection for the exact propagation-delay behavior
    already observed live for namespace.create (an immediate GET right
    after a successful mutating call did not yet list the new resource,
    while a normal Refresh moments later did — see
    app/execution/namespace_create_handler.py's module docstring).
    database.create's verify() reuses the identical bounded-retry policy;
    this test proves it actually retries rather than giving up after the
    first 404."""
    fake_iris_client.get.side_effect = [
        _DEFAULT_EXISTING_DATABASES,
        IRISResponseError(404),  # attempt 1 — not yet propagated
        IRISResponseError(404),  # attempt 2 (1st retry) — still not yet
        _database_dir_found(),  # attempt 3 (2nd retry) — now present
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
    # Stopped the instant it was found — 1 (validate) + 3 (verify) = 4.
    assert fake_iris_client.get.await_count == 4


@pytest.mark.asyncio
async def test_verification_retries_perform_no_mutation(fake_iris_client: AsyncMock) -> None:
    """The retry loop must only ever re-read (GET /v2/database-dir) —
    never re-attempt the creation itself. POST must still be called
    exactly once, no matter how many times verification retries its GET."""
    fake_iris_client.get.side_effect = [
        _DEFAULT_EXISTING_DATABASES,
        IRISResponseError(404),  # attempt 1 — absent
        IRISResponseError(404),  # attempt 2 — absent
        IRISResponseError(404),  # attempt 3 — absent
        IRISResponseError(404),  # attempt 4 — absent (exhausted)
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
    """Only the documented 404 ("not found yet") is treated as a
    retry-worthy signal. A genuine unexpected IRIS error (500) during
    verification must propagate, not be silently swallowed and misread as
    "not found" — doing so would hide a real failure behind a generic
    VERIFICATION_FAILED message."""
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
    # Never retried past the one unexpected error.
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


# --- validation against live data: directory/name collision, system databases ---


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
    """A different literal path whose final segment still derives to an
    already-existing database's real Name ("USER") must be rejected — the
    same collision-defense mechanism that also protects system databases
    like IRISSYS/IRISLIB/IRISTEMP, since they too are already present in
    the existing database list (see test below)."""
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
    """"Obviously unsafe/system database target" rejection: a request
    whose directory would derive to "IRISSYS" — a real, already-existing
    system database per _DEFAULT_EXISTING_DATABASES — is rejected by the
    exact same real-data-driven mechanism as any other name collision, not
    a separately hardcoded "system names" list."""
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
