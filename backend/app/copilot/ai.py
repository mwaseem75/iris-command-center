"""Deterministic Copilot AI provider.

The Copilot uses one local, rule-based provider. Its output is descriptive
text plus, at most, a proposal; deterministic application code controls
planning, authorization, confirmation and execution.
"""

import re
from typing import Protocol

from app.copilot.intents import CopilotIntent
from app.models.copilot import CopilotAIOutput, CopilotAIRequest, CopilotOperationalContext


class CopilotAIProvider(Protocol):
    async def generate(self, request: CopilotAIRequest) -> CopilotAIOutput:
        """Return a structured explanation or descriptive proposal."""
        ...


def create_copilot_provider() -> CopilotAIProvider:
    """The Copilot's provider: always the deterministic provider."""
    return DeterministicCopilotProvider()


class DeterministicCopilotProvider:
    """Local, rule-based provider; it has no tools, network or IRIS access."""

    async def generate(self, request: CopilotAIRequest) -> CopilotAIOutput:
        context = request.context
        observations: list[str] = []
        if context.unavailable:
            observations.append(
                "Context unavailable for: " + ", ".join(context.unavailable) + "."
            )

        if request.intent is CopilotIntent.ISSUE_INVESTIGATION:
            observations.extend(_issue_observations(context))
            return CopilotAIOutput(answer=_issue_answer(context), observations=observations[:8])

        if request.intent is CopilotIntent.HEALTH_STATUS:
            observations.extend(_context_counts(context))
            return CopilotAIOutput(
                answer="Here is a summary of the available read-only operational context.",
                observations=observations[:8],
            )

        if request.intent is CopilotIntent.RESOLUTION_REQUEST:
            proposed_action = (
                _purge_archived_proposal(request.message)
                or _database_mount_proposal(request.message)
                or _web_app_disable_proposal(request.message)
            )
            return CopilotAIOutput(
                answer=(
                    "I can describe a possible next step, but no operation is executed "
                    "by this Copilot step."
                ),
                observations=observations[:8],
                proposed_action=proposed_action,
                requires_confirmation=proposed_action is not None,
            )

        observations.extend(_context_counts(context))
        return CopilotAIOutput(
            answer="Here is the available read-only operational context.",
            observations=observations[:8],
        )


def _purge_archived_proposal(message: str) -> str | None:
    match = re.fullmatch(
        r"\s*(enable|disable)\s+(?:the\s+)?purge[ _]?archived\s*[.!]?\s*",
        message,
        re.IGNORECASE,
    )
    if match is None:
        return None
    value = "true" if match.group(1).lower() == "enable" else "false"
    return f"Set PurgeArchived to {value}"


def _database_mount_proposal(message: str) -> str | None:
    """Proposal text only: the name never becomes a parameter; the planner
    uses it to select a currently detected dismounted-database issue."""
    for pattern in (
        r"\s*mount\s+(?:the\s+)?([A-Za-z0-9_%-]{1,64})\s+database\s*[.!]?\s*",
        r"\s*mount\s+(?:the\s+)?database\s+([A-Za-z0-9_%-]{1,64})\s*[.!]?\s*",
    ):
        match = re.fullmatch(pattern, message, re.IGNORECASE)
        if match is not None and match.group(1).lower() not in {"the", "database"}:
            return f"Mount database {match.group(1)}"
    return None


def _web_app_disable_proposal(message: str) -> str | None:
    """Proposal text only, disable only: the name never becomes a parameter;
    the planner uses it to select a currently detected web-app issue."""
    for pattern in (
        r"\s*disable\s+(?:the\s+)?web\s*app(?:lication)?\s+(/\S{0,255}?)\s*[.!]?\s*",
        r"\s*disable\s+(?:the\s+)?(/\S{0,255}?)\s+web\s*app(?:lication)?\s*[.!]?\s*",
    ):
        match = re.fullmatch(pattern, message, re.IGNORECASE)
        if match is not None:
            return f"Disable web app {match.group(1)}"
    return None


def _issue_answer(context: CopilotOperationalContext) -> str:
    total = context.issues_total
    if total is None:
        return "The Issue Resolver findings could not be read, so active issues are unknown."
    if total == 0:
        return "The Issue Resolver reports no active issues."
    answer = f"The Issue Resolver reports {total} active issue{'' if total == 1 else 's'}."
    if len(context.issues) < total:
        answer += f" The first {len(context.issues)} are listed."
    return answer + " Nothing is changed from here."


def _issue_observations(context: CopilotOperationalContext) -> list[str]:
    observations: list[str] = []
    if context.issue_checks_unavailable:
        observations.append(
            "Issue checks that could not run: "
            + ", ".join(context.issue_checks_unavailable) + "."
        )
    for issue in context.issues:
        severity = f"[{issue.severity}] " if issue.severity else ""
        line = f"{severity}{issue.title or issue.kind} ({issue.resource_name})"
        if issue.explanation:
            line += f": {issue.explanation}"
        observations.append(line)
    return observations


def _context_counts(context: CopilotOperationalContext) -> list[str]:
    observations = []
    for label, total in (
        ("Databases", context.databases_total),
        ("Processes", context.processes_total),
        ("Web applications", context.web_apps_total),
        ("Tasks", context.tasks_total),
    ):
        if total is not None:
            observations.append(f"{label}: {total}.")
    if context.info is not None:
        product = context.info.product or "IRIS"
        version = context.info.server_version or "version unavailable"
        observations.append(f"Connected instance: {product} {version}.")
    return observations
