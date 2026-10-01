"""Turns IRIS data (already fetched by the route) into short chat replies."""

from app.models.iris import DatabaseEntry, InfoResult, ProcessEntry, TaskEntry, WebAppEntry

_MAX_LISTED = 5

UNKNOWN_REPLY = (
    "I can help with read-only questions about this IRIS instance: system status, "
    "process count or list, database status, web app status, and task information. "
    'Try asking, for example, "Show me the current IRIS system status."'
)

UNREACHABLE_REPLY = "I couldn't reach IRIS to answer that just now. Please try again shortly."
PRIMARY_ONLY_REPLY = (
    "Changes run on the Primary instance only. Switch to Primary in the header to make this change."
)


def format_system_status(info: InfoResult) -> str:
    mode = f" ({info.systemMode})" if info.systemMode else ""
    return (
        f"Connected to {info.product or 'IRIS'} {info.serverVersion or 'unknown version'}"
        f"{mode} as {info.username or 'an unknown user'}. API v{info.apiVersion}."
    )


def format_process_count(processes: list[ProcessEntry]) -> str:
    count = len(processes)
    if count == 0:
        return "No processes are currently reported."
    noun = "process is" if count == 1 else "processes are"
    return f"{count} {noun} currently running."


def format_process_list(processes: list[ProcessEntry]) -> str:
    if not processes:
        return "No processes are currently reported."
    shown = processes[:_MAX_LISTED]
    lines = [f"PID {p.Pid} — {p.Routine or 'unknown routine'} ({p.State})" for p in shown]
    reply = f"Showing {len(shown)} of {len(processes)} processes:\n" + "\n".join(lines)
    remaining = len(processes) - len(shown)
    if remaining > 0:
        reply += f"\n…and {remaining} more."
    return reply


def format_database_status(databases: list[DatabaseEntry]) -> str:
    if not databases:
        return "No databases are currently reported."
    shown = databases[:_MAX_LISTED]
    lines = [f"{d.Name} — {d.Status or 'unknown status'}" for d in shown]
    reply = f"{len(databases)} databases configured:\n" + "\n".join(lines)
    remaining = len(databases) - len(shown)
    if remaining > 0:
        reply += f"\n…and {remaining} more."
    return reply


def format_web_app_status(web_apps: list[WebAppEntry]) -> str:
    if not web_apps:
        return "No web applications are currently reported."
    enabled = sum(1 for w in web_apps if w.Enabled)
    disabled = len(web_apps) - enabled
    return f"{len(web_apps)} web applications configured — {enabled} enabled, {disabled} disabled."


def format_task_info(tasks: list[TaskEntry]) -> str:
    if not tasks:
        return "No scheduled tasks are currently reported."
    suspended = sum(1 for t in tasks if t.Suspended)
    active = len(tasks) - suspended
    example = tasks[0]
    next_run = example.NextScheduled or "not scheduled"
    return (
        f"{len(tasks)} scheduled tasks configured ({active} active, {suspended} suspended). "
        f'Example: "{example.Name}" next runs {next_run}.'
    )
