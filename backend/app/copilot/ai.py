"""Deterministic Copilot AI provider.

The Copilot uses one local, rule-based provider. Its output is descriptive
text plus, at most, a proposal; deterministic application code controls
planning, authorization, confirmation and execution.
"""

import re
from typing import Protocol

from app.copilot.intents import CopilotIntent, is_task_detail_question, process_pid_in
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

        if request.intent is CopilotIntent.READ_ONLY_QUERY and _PROCESS_WORD.search(request.message):
            answer, process_observations = _process_answer(request.message, context)
            observations.extend(process_observations)
            return CopilotAIOutput(answer=answer, observations=observations[:8])

        if request.intent is CopilotIntent.READ_ONLY_QUERY and _TASK_WORD.search(request.message):
            observations.extend(
                _task_detail_observations(context)
                if is_task_detail_question(request.message)
                else _task_observations(context)
            )
            return CopilotAIOutput(answer=_task_answer(context), observations=observations[:8])

        observations.extend(_context_counts(context))
        return CopilotAIOutput(
            answer="Here is the available read-only operational context.",
            observations=observations[:8],
        )


_TASK_WORD = re.compile(r"\btasks?\b", re.IGNORECASE)
_PROCESS_WORD = re.compile(r"\bprocess(?:es)?\b|\bpid\b", re.IGNORECASE)
_CPU_WORD = re.compile(r"\bcpu\b|\btop\b|\bbusiest\b|\bheaviest\b", re.IGNORECASE)
_NAMESPACE_WORD = re.compile(r"\bnamespaces?\b", re.IGNORECASE)
_STATE_WORD = re.compile(r"\bstates?\b", re.IGNORECASE)
_CPU_NOTE = "cumulative CPU time as reported by IRIS, not current CPU usage"


def _process_answer(message: str, context: CopilotOperationalContext) -> tuple[str, list[str]]:
    """Read-only answers from the process list in the context. States are
    IRIS's own codes and are reported as they are, not judged."""
    total = context.processes_total
    if total is None:
        return "Process information could not be read, so process activity could not be assessed.", []
    pid = process_pid_in(message)
    if pid is not None:
        return _pid_answer(pid, context)
    if total == 0:
        return "IRIS reports no processes.", []
    noun = "process" if total == 1 else "processes"
    by_namespace = context.processes_by_namespace
    if _CPU_WORD.search(message):
        top = context.processes_top_cpu
        return (
            f"The top {len(top)} of {total} {noun} by {_CPU_NOTE}.",
            [
                f"PID {p.pid}: {p.cpu_time} ms, {p.routine or 'no routine'} "
                f"({p.namespace or '(none)'}, {p.state or 'state unknown'})"
                for p in top
            ],
        )
    if _NAMESPACE_WORD.search(message):
        return (
            f"IRIS reports {total} {noun} across {len(by_namespace)} namespaces. "
            "Processes without a namespace, such as system daemons, are listed as (none).",
            _count_lines("Namespace", by_namespace),
        )
    if _STATE_WORD.search(message):
        return (
            f"IRIS reports {total} {noun} in {len(context.processes_by_state)} states. "
            "States are IRIS's own process state codes, shown as reported.",
            _count_lines("State", context.processes_by_state),
        )
    observations = [
        "By state: " + _joined_counts(context.processes_by_state) + ".",
        "By namespace: " + _joined_counts(by_namespace) + ".",
    ]
    if context.processes_top_cpu:
        top = context.processes_top_cpu[0]
        observations.append(
            f"Highest cumulative CPU time: PID {top.pid} ({top.routine or 'no routine'}), "
            f"{top.cpu_time} ms."
        )
    return f"IRIS reports {total} {noun} across {len(by_namespace)} namespaces.", observations


def _pid_answer(pid: int, context: CopilotOperationalContext) -> tuple[str, list[str]]:
    process = context.process_focus
    if process is None or process.pid != pid:
        return (
            f"PID {pid} was not found in the current process data "
            f"({context.processes_total} processes reported).",
            [],
        )
    return (
        f"PID {pid} is in state {process.state or 'unknown'}, running "
        f"{process.routine or 'no routine'} in {process.namespace or 'no namespace'}.",
        [
            f"Namespace: {process.namespace or '(none)'}",
            f"Routine: {process.routine or '(none)'}",
            f"State: {process.state or 'unknown'}",
            f"Username: {process.username or '(none)'}",
            f"CPU time: {process.cpu_time} ms ({_CPU_NOTE})",
            f"Commands: {process.commands}",
            f"Globals: {process.globals}",
            f"Elapsed time: {process.elapsed_time or 'not reported'}",
        ],
    )


def _count_lines(label: str, counts: dict[str, int]) -> list[str]:
    lines = [f"{label} {key}: {count}" for key, count in counts.items()]
    if len(lines) <= 8:
        return lines
    rest = list(counts.values())[7:]
    return lines[:7] + [f"{len(rest)} more, with {sum(rest)} processes"]


def _joined_counts(counts: dict[str, int]) -> str:
    return ", ".join(f"{key} {count}" for key, count in counts.items())


def _task_answer(context: CopilotOperationalContext) -> str:
    """Summary of the tasks in the context only (at most 10); read-only."""
    if context.tasks_total is None:
        return "Task information could not be read, so task states are unknown."
    shown = len(context.tasks)
    if shown == 0:
        return "IRIS reports no tasks."
    suspended = sum(1 for task in context.tasks if task.state == "Suspended")
    failing = sum(1 for task in context.tasks if task.error)
    scope = (
        f"Of the {shown} tasks shown ({context.tasks_total} in total)"
        if shown < context.tasks_total
        else f"Of the {shown} task{'' if shown == 1 else 's'}"
    )
    return (
        f"{scope}: {suspended} suspended, {failing} with an error reported. "
        "Nothing is changed from here."
    )


def _task_observations(context: CopilotOperationalContext) -> list[str]:
    if context.tasks_total is None or not context.tasks:
        return []
    observations = [
        f"Suspended: {task.name}" + (f" ({task.type})" if task.type else "")
        for task in context.tasks
        if task.state == "Suspended"
    ] or ["No suspended tasks among those shown."]
    observations += [
        f"Error reported for {task.name}: {task.error}" for task in context.tasks if task.error
    ] or ["No task errors among those shown."]
    unknown = sum(1 for task in context.tasks if task.state is None)
    if unknown:
        observations.append(f"Run state unavailable for {unknown} task{'' if unknown == 1 else 's'}.")
    return observations


def _task_detail_observations(context: CopilotOperationalContext) -> list[str]:
    """Run-as and schedule per task, as IRIS reports them (not interpreted)."""
    if context.tasks_total is None:
        return []
    observations = []
    for task in context.tasks:
        if task.run_as_user is None and task.time_period is None:
            observations.append(f"{task.name}: details unavailable.")
            continue
        suspend_on_error = {True: "yes", False: "no"}.get(task.suspend_on_error, "unknown")
        observations.append(
            f"{task.name}: runs as {task.run_as_user}; TimePeriod {task.time_period}, "
            f"every {task.time_period_every}; DailyFrequency {task.daily_frequency}, "
            f"DailyStartTime {task.daily_start_time}; next run {task.next_scheduled or 'none'}; "
            f"suspend on error: {suspend_on_error}."
        )
    return observations


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
