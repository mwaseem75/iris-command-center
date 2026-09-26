"""Tests for journal.update_purge_archived. Everything runs against a mocked IRISClient."""

from typing import Any
from unittest.mock import AsyncMock

import pytest

from app.execution.executor import OperationExecutor
from app.execution.journal_purge_archived_handler import JournalUpdatePurgeArchivedHandler
from app.execution.models import (
    ExecutionContext,
    HandlerOutcome,
    OperationRequest,
    OperationResultStatus,
    PostActionVerificationStatus,
)

_OPERATION_NAME = "journal.update_purge_archived"


def _journal_settings_body(purge_archived: bool) -> dict[str, Any]:
    """JournalSettings response with the given PurgeArchived value."""
    return {
        "status": {"errors": [], "summary": ""},
        "console": [],
        "result": {
            "AlternateDirectory": "/usr/irissys/mgr/journal/",
            "ArchiveName": "",
            "BackupsBeforePurge": 2,
            "CurrentDirectory": "/usr/irissys/mgr/journal/",
            "DaysBeforePurge": 2,
            "FileSizeLimit": 1024,
            "FreezeOnError": False,
            "JournalFilePrefix": "",
            "JournalcspSession": False,
            "PurgeArchived": purge_archived,
            "CompressFiles": True,
            "wijdir": "",
            "targwijsz": 0,
        },
    }


@pytest.fixture
def fake_iris_client() -> AsyncMock:
    """Fake client: GET reports PurgeArchived=False and PUT echoes the requested
    value. Tests override as needed.
    """
    client = AsyncMock()
    client.get.return_value = _journal_settings_body(purge_archived=False)
    client.put.return_value = _journal_settings_body(purge_archived=True)
    return client


@pytest.fixture
def executor(fake_iris_client: AsyncMock) -> OperationExecutor:
    handler = JournalUpdatePurgeArchivedHandler(fake_iris_client)
    return OperationExecutor({_OPERATION_NAME: handler})


def _request(purge_archived: bool = True) -> OperationRequest:
    return OperationRequest(
        operation_name=_OPERATION_NAME, parameters={"PurgeArchived": purge_archived}
    )


def _context(
    *, privileges: frozenset[str], confirmed: bool = False, dry_run: bool = False
) -> ExecutionContext:
    return ExecutionContext(
        available_privileges=privileges, confirmation_received=confirmed, dry_run=dry_run
    )


# --- unauthorized user -> denied ---


@pytest.mark.asyncio
async def test_no_privilege_is_denied(
    executor: OperationExecutor, fake_iris_client: AsyncMock
) -> None:
    result = await executor.execute(_request(), _context(privileges=frozenset()))

    assert result.status is OperationResultStatus.UNAUTHORIZED
    fake_iris_client.put.assert_not_awaited()


@pytest.mark.asyncio
async def test_neither_manage_nor_journal_privilege_is_denied(
    executor: OperationExecutor, fake_iris_client: AsyncMock
) -> None:
    result = await executor.execute(
        _request(), _context(privileges=frozenset({"Operate", "Secure"}), confirmed=True)
    )

    assert result.status is OperationResultStatus.UNAUTHORIZED
    fake_iris_client.put.assert_not_awaited()


# --- Manage privilege -> authorized ---


@pytest.mark.asyncio
async def test_manage_privilege_is_authorized(executor: OperationExecutor) -> None:
    result = await executor.execute(
        _request(), _context(privileges=frozenset({"Manage"}), confirmed=True, dry_run=True)
    )

    assert result.authorization is not None
    assert result.authorization.authorized is True
    assert result.status is OperationResultStatus.DRY_RUN


# --- Journal privilege -> authorized ---


@pytest.mark.asyncio
async def test_journal_privilege_is_authorized(executor: OperationExecutor) -> None:
    result = await executor.execute(
        _request(), _context(privileges=frozenset({"Journal"}), confirmed=True, dry_run=True)
    )

    assert result.authorization is not None
    assert result.authorization.authorized is True
    assert result.status is OperationResultStatus.DRY_RUN


# --- no confirmation -> blocked ---


@pytest.mark.asyncio
async def test_no_confirmation_blocks_before_put(
    executor: OperationExecutor, fake_iris_client: AsyncMock
) -> None:
    result = await executor.execute(
        _request(), _context(privileges=frozenset({"Manage"}), confirmed=False, dry_run=False)
    )

    assert result.status is OperationResultStatus.CONFIRMATION_REQUIRED
    fake_iris_client.get.assert_not_awaited()
    fake_iris_client.put.assert_not_awaited()


# --- confirmation + dry_run -> succeeds without PUT ---


@pytest.mark.asyncio
async def test_confirmation_and_dry_run_never_calls_put(
    executor: OperationExecutor, fake_iris_client: AsyncMock
) -> None:
    result = await executor.execute(
        _request(purge_archived=True),
        _context(privileges=frozenset({"Manage"}), confirmed=True, dry_run=True),
    )

    assert result.status is OperationResultStatus.DRY_RUN
    fake_iris_client.put.assert_not_awaited()
    fake_iris_client.get.assert_awaited_once_with("/v2/journal/settings")
    assert result.handler_result is not None
    assert result.handler_result.outcome is HandlerOutcome.SUCCESS
    assert result.handler_result.data["requested_purge_archived"] is True
    assert result.verification is None


# --- confirmation + execution -> PUT called exactly once, correct body ---


@pytest.mark.asyncio
async def test_confirmation_and_execution_calls_put_exactly_once_with_correct_body(
    fake_iris_client: AsyncMock,
) -> None:
    # A real run does two GETs: before the PUT and after it (verify). The
    # second one returns the new value, like IRIS would.
    fake_iris_client.get.side_effect = [
        _journal_settings_body(purge_archived=False),
        _journal_settings_body(purge_archived=True),
    ]
    handler = JournalUpdatePurgeArchivedHandler(fake_iris_client)
    executor = OperationExecutor({_OPERATION_NAME: handler})

    result = await executor.execute(
        _request(purge_archived=True),
        _context(privileges=frozenset({"Manage"}), confirmed=True, dry_run=False),
    )

    assert result.status is OperationResultStatus.SUCCESS
    fake_iris_client.put.assert_awaited_once_with(
        "/v2/journal/settings", json={"PurgeArchived": True}
    )


# --- original value captured ---


@pytest.mark.asyncio
async def test_original_value_is_captured_in_result(
    executor: OperationExecutor, fake_iris_client: AsyncMock
) -> None:
    # the fixture's GET reports False
    result = await executor.execute(
        _request(purge_archived=True),
        _context(privileges=frozenset({"Journal"}), confirmed=True, dry_run=False),
    )

    assert result.handler_result is not None
    assert result.handler_result.data["original_purge_archived"] is False
    assert result.handler_result.data["requested_purge_archived"] is True


# --- post-action GET verification succeeds ---


@pytest.mark.asyncio
async def test_post_action_verification_succeeds_when_get_matches_requested_value(
    fake_iris_client: AsyncMock,
) -> None:
    # First GET says False, PUT returns True, the verify GET must say True.
    fake_iris_client.get.side_effect = [
        _journal_settings_body(purge_archived=False),
        _journal_settings_body(purge_archived=True),
    ]
    handler = JournalUpdatePurgeArchivedHandler(fake_iris_client)
    executor = OperationExecutor({_OPERATION_NAME: handler})

    result = await executor.execute(
        _request(purge_archived=True),
        _context(privileges=frozenset({"Manage"}), confirmed=True, dry_run=False),
    )

    assert result.status is OperationResultStatus.SUCCESS
    assert result.verification is not None
    assert result.verification.status is PostActionVerificationStatus.VERIFIED
    assert fake_iris_client.get.await_count == 2


# --- post-action verification detects an incorrect resulting value ---


@pytest.mark.asyncio
async def test_post_action_verification_fails_when_get_does_not_match_requested_value(
    fake_iris_client: AsyncMock,
) -> None:
    # PUT says OK but the next GET still shows the old value.
    fake_iris_client.get.side_effect = [
        _journal_settings_body(purge_archived=False),
        _journal_settings_body(purge_archived=False),  # unchanged!
    ]
    handler = JournalUpdatePurgeArchivedHandler(fake_iris_client)
    executor = OperationExecutor({_OPERATION_NAME: handler})

    result = await executor.execute(
        _request(purge_archived=True),
        _context(privileges=frozenset({"Manage"}), confirmed=True, dry_run=False),
    )

    assert result.status is OperationResultStatus.VERIFICATION_FAILED
    assert result.status is not OperationResultStatus.EXECUTION_FAILED
    assert result.verification is not None
    assert result.verification.status is PostActionVerificationStatus.VERIFICATION_FAILED


# --- handler/PUT failure -> structured execution failure ---


@pytest.mark.asyncio
async def test_put_raising_becomes_structured_execution_failure(
    fake_iris_client: AsyncMock,
) -> None:
    from app.iris_client.exceptions import IRISResponseError

    fake_iris_client.put.side_effect = IRISResponseError(500)
    handler = JournalUpdatePurgeArchivedHandler(fake_iris_client)
    executor = OperationExecutor({_OPERATION_NAME: handler})

    result = await executor.execute(
        _request(purge_archived=True),
        _context(privileges=frozenset({"Manage"}), confirmed=True, dry_run=False),
    )

    assert result.status is OperationResultStatus.EXECUTION_FAILED
    assert "credential" not in result.detail.lower()
    assert "password" not in result.detail.lower()


# --- unknown operation remains denied ---


@pytest.mark.asyncio
async def test_unknown_operation_is_still_denied(fake_iris_client: AsyncMock) -> None:
    handler = JournalUpdatePurgeArchivedHandler(fake_iris_client)
    executor = OperationExecutor({_OPERATION_NAME: handler})

    result = await executor.execute(
        OperationRequest(operation_name="journal.delete_everything", parameters={}),
        _context(privileges=frozenset({"Manage"}), confirmed=True),
    )

    assert result.status is OperationResultStatus.UNKNOWN_OPERATION
    fake_iris_client.get.assert_not_awaited()
    fake_iris_client.put.assert_not_awaited()


# --- dry-run's own GET failure must not crash the executor ---


@pytest.mark.asyncio
async def test_dry_run_get_failure_becomes_structured_failure_not_a_crash(
    fake_iris_client: AsyncMock,
) -> None:
    from app.iris_client.exceptions import IRISConnectionError

    fake_iris_client.get.side_effect = IRISConnectionError("simulated — no real network involved")
    handler = JournalUpdatePurgeArchivedHandler(fake_iris_client)
    executor = OperationExecutor({_OPERATION_NAME: handler})

    result = await executor.execute(
        _request(purge_archived=True),
        _context(privileges=frozenset({"Manage"}), confirmed=True, dry_run=True),
    )

    assert result.status is OperationResultStatus.EXECUTION_FAILED
    fake_iris_client.put.assert_not_awaited()


# --- extra fields are rejected ---


@pytest.mark.asyncio
async def test_extra_field_in_parameters_is_rejected_not_silently_dropped(
    executor: OperationExecutor, fake_iris_client: AsyncMock
) -> None:
    request = OperationRequest(
        operation_name=_OPERATION_NAME,
        parameters={"PurgeArchived": True, "ArchiveName": "attempted-smuggled-field"},
    )

    result = await executor.execute(
        request, _context(privileges=frozenset({"Manage"}), confirmed=True, dry_run=True)
    )

    assert result.status is OperationResultStatus.EXECUTION_FAILED
    fake_iris_client.put.assert_not_awaited()


def test_parameters_model_rejects_extra_fields_directly() -> None:
    from pydantic import ValidationError

    from app.execution.journal_purge_archived_handler import JournalPurgeArchivedParameters

    with pytest.raises(ValidationError):
        JournalPurgeArchivedParameters.model_validate(
            {"PurgeArchived": True, "ArchiveName": "not-allowed"}
        )


# --- only PurgeArchived is ever sent ---


@pytest.mark.asyncio
async def test_put_body_contains_only_purge_archived_field(
    executor: OperationExecutor, fake_iris_client: AsyncMock
) -> None:
    await executor.execute(
        _request(purge_archived=False),
        _context(privileges=frozenset({"Manage"}), confirmed=True, dry_run=False),
    )

    _, kwargs = fake_iris_client.put.await_args
    assert kwargs["json"] == {"PurgeArchived": False}
    assert list(kwargs["json"].keys()) == ["PurgeArchived"]
