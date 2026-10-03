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

        if request.intent is CopilotIntent.READ_ONLY_QUERY and _DATABASE_WORD.search(request.message):
            answer, database_observations = _database_answer(context)
            observations.extend(database_observations)
            return CopilotAIOutput(answer=answer, observations=observations[:8])

        if request.intent is CopilotIntent.READ_ONLY_QUERY and _WEB_APP_WORD.search(request.message):
            answer, web_app_observations = _web_app_answer(request.message, context)
            observations.extend(web_app_observations)
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
_DATABASE_WORD = re.compile(r"\bdatabases?\b", re.IGNORECASE)
_WEB_APP_WORD = re.compile(r"\bweb\s*apps?\b|\bweb\s+applications?\b", re.IGNORECASE)
_DATABASE_ISSUES = ("database_dismounted", "database_full")


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


def _detected(context: CopilotOperationalContext, kinds: tuple[str, ...], what: str) -> str:
    """What the Issue Resolver's detection says about `kinds` (from the issues
    in the context, which lists at most the first 10)."""
    if context.issues_total is None:
        return f"Issue detection could not be read, so {what} are unknown."
    found = sum(1 for issue in context.issues if issue.kind in kinds)
    unchecked = [kind for kind in kinds if kind in context.issue_checks_unavailable]
    text = (
        f"The Issue Resolver detects {what}: {found}."
        if found else f"The Issue Resolver detects no {what}."
    )
    if unchecked:
        text += " Checks that could not run: " + ", ".join(unchecked) + "."
    return text


def _issue_lines(context: CopilotOperationalContext, kinds: tuple[str, ...]) -> list[str]:
    return [
        f"{issue.title or issue.kind}: {issue.resource_name}" for issue in context.issues
        if issue.kind in kinds
    ]


def _database_answer(context: CopilotOperationalContext) -> tuple[str, list[str]]:
    """Status as IRIS reports it, plus detected dismounted or full databases.
    The context has no database sizes."""
    total = context.databases_total
    if total is None:
        return "Database information could not be read, so database status could not be assessed.", []
    if total == 0:
        return "IRIS reports no databases.", []
    noun = "database" if total == 1 else "databases"
    answer = (
        f"IRIS reports {total} {noun}: {_joined_counts(context.databases_by_status)}. "
        + _detected(context, _DATABASE_ISSUES, "dismounted or full databases")
    )
    observations = _issue_lines(context, _DATABASE_ISSUES)
    observations += _count_lines("Status", context.databases_by_status)
    names = [database.name for database in context.databases]
    more = f" and {total - len(names)} more" if total > len(names) else ""
    observations.append("Databases: " + ", ".join(names) + more + ".")
    return answer, observations[:8]


def _web_app_answer(message: str, context: CopilotOperationalContext) -> tuple[str, list[str]]:
    """Enabled state, namespace and type as IRIS reports them, plus detected
    applications whose namespace is missing."""
    total = context.web_apps_total
    if total is None:
        return (
            "Web application information could not be read, so web applications could not be assessed.",
            [],
        )
    if total == 0:
        return "IRIS reports no web applications.", []
    by_state = context.web_apps_by_state
    noun = "web application" if total == 1 else "web applications"
    answer = (
        f"IRIS reports {total} {noun}: {by_state.get('Enabled', 0)} enabled, "
        f"{by_state.get('Disabled', 0)} disabled. "
        + _detected(context, ("web_app_namespace_missing",), "web applications with a missing namespace")
    )
    observations = _issue_lines(context, ("web_app_namespace_missing",))
    if _NAMESPACE_WORD.search(message):
        return answer, (observations + _count_lines("Namespace", context.web_apps_by_namespace))[:8]
    disabled = context.web_apps_disabled
    if disabled:
        more = by_state.get("Disabled", 0) - len(disabled)
        observations.append(
            "Disabled: " + ", ".join(disabled) + (f" and {more} more" if more > 0 else "") + "."
        )
    observations.append("By namespace: " + _joined_counts(context.web_apps_by_namespace) + ".")
    observations.append("By type (as reported by IRIS): " + _joined_counts(context.web_apps_by_type) + ".")
    return answer, observations[:8]


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
    elif context.issues_total is not None:
        observations.append("All issue checks ran.")
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
