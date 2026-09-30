"""Stable identity helpers for detected issues."""

from enum import Enum
from hashlib import sha256

from pydantic import BaseModel, ConfigDict


class ResolutionReadiness(str, Enum):
    READY_TO_CHECK = "ready_to_check"
    BLOCKED = "blocked"
    INVESTIGATION_REQUIRED = "investigation_required"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


class IssueResourceReference(BaseModel):
    """The canonical resource an issue is about."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    type: str
    canonical_key: str
    display_name: str


class IssueIdentity(BaseModel):
    """Additive identity fields shared by every detected issue."""

    issue_id: str
    resource: IssueResourceReference
    readiness: ResolutionReadiness = ResolutionReadiness.INSUFFICIENT_EVIDENCE


def issue_identity(
    issue_type: str,
    resource_type: str,
    canonical_key: str,
    display_name: str,
) -> dict[str, object]:
    """Return deterministic identity fields for an issue and its resource.

    The canonical key is supplied by the detector. No case normalization is
    performed, which is important for filesystem paths.
    """
    identity = "\x00".join((issue_type, resource_type, canonical_key))
    issue_id = sha256(identity.encode("utf-8")).hexdigest()
    return {
        "issue_id": issue_id,
        "resource": IssueResourceReference(
            type=resource_type,
            canonical_key=canonical_key,
            display_name=display_name,
        ),
    }
