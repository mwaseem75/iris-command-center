"""Static list of IRIS Admin API capabilities for the API Explorer page.

Each row records an IRIS endpoint we've tested, the privilege it needs, the
result, and which Command Center route (if any) exposes it. None means it's
only used internally (e.g. login, async-task polling).
app/routes/capabilities.py checks the listed routes against the real app
routes at request time, so a stale path shows up as unavailable.
"""

from pydantic import BaseModel, ConfigDict


class CapabilityEntry(BaseModel):
    model_config = ConfigDict(frozen=True)

    capability: str
    endpoint: str
    method: str
    required_privilege: str
    iris_version: str
    verification_status: str  # "Verified" or "Not tested"
    notes: str
    command_center_path: str | None = None
    command_center_method: str | None = None


_VERIFIED_AGAINST = "2026.2 (Build 221U), intersystemsdc/iris-community:2026.2"

CAPABILITY_REGISTRY: list[CapabilityEntry] = [
    CapabilityEntry(
        capability="Authenticate and obtain JWT access/refresh tokens",
        endpoint="/api/admin/login",
        method="POST",
        required_privilege="None documented",
        iris_version=_VERIFIED_AGAINST,
        verification_status="Verified",
        notes="Used internally by this backend's session layer (app/auth/iris_auth.py) to obtain "
        "every other call's bearer token — never exposed as its own public route.",
        command_center_path=None,
    ),
    CapabilityEntry(
        capability="Retrieve server, API, and logged-in-user info, including %Admin_* privilege flags",
        endpoint="/api/admin/info",
        method="GET",
        required_privilege="At least one %Admin_* privilege",
        iris_version=_VERIFIED_AGAINST,
        verification_status="Verified",
        notes="ConfigStore privilege flag is documented by the spec but was absent from the actual "
        "response on this instance.",
        command_center_path="/api/iris/info",
        command_center_method="GET",
    ),
    CapabilityEntry(
        capability="View a list of namespaces",
        endpoint="/api/admin/v2/namespaces",
        method="GET",
        required_privilege="%Admin_Manage:U",
        iris_version=_VERIFIED_AGAINST,
        verification_status="Verified",
        notes="Returned one more namespace than /info did for the same account/instance "
        "(3 vs. 2) — a real, observed discrepancy, not a bug in this route.",
        command_center_path="/api/iris/namespaces",
        command_center_method="GET",
    ),
    CapabilityEntry(
        capability="List databases (Config.Databases entries)",
        endpoint="/api/admin/v2/databases",
        method="GET",
        required_privilege="%Admin_Manage:U or %Admin_Operate:U",
        iris_version=_VERIFIED_AGAINST,
        verification_status="Verified",
        notes="10 real databases returned; directory paths cross-confirmed against container "
        "startup logs.",
        command_center_path="/api/iris/databases",
        command_center_method="GET",
    ),
    CapabilityEntry(
        capability="View a list of processes",
        endpoint="/api/admin/v2/processes",
        method="GET",
        required_privilege="%Admin_Operate:U",
        iris_version=_VERIFIED_AGAINST,
        verification_status="Verified",
        notes="25 real processes returned, including this connection's own SQL/web-server processes.",
        command_center_path="/api/iris/processes",
        command_center_method="GET",
    ),
    CapabilityEntry(
        capability="View a list of web applications",
        endpoint="/api/admin/v2/web-apps",
        method="GET",
        required_privilege="%Admin_Secure:U",
        iris_version=_VERIFIED_AGAINST,
        verification_status="Verified",
        notes="22 real web applications returned, including /api/admin itself.",
        command_center_path="/api/iris/web-apps",
        command_center_method="GET",
    ),
    CapabilityEntry(
        capability="View a list of external language servers",
        endpoint="/api/admin/v2/ext-lang-servers",
        method="GET",
        required_privilege="%Admin_ExternalLanguageServerEdit:U",
        iris_version=_VERIFIED_AGAINST,
        verification_status="Verified",
        notes="8 built-in external language gateways returned (.NET, Java, Python, R, ML, ODBC, "
        "JDBC, XSLT).",
        command_center_path="/api/iris/ext-lang-servers",
        command_center_method="GET",
    ),
    CapabilityEntry(
        capability="View a list of tasks",
        endpoint="/api/admin/v2/tasks",
        method="GET",
        required_privilege="%Admin_Operate:U or %Admin_Task:U",
        iris_version=_VERIFIED_AGAINST,
        verification_status="Verified",
        notes="16 built-in scheduled system tasks returned (Switch Journal, Purge Journal, ...).",
        command_center_path="/api/iris/tasks",
        command_center_method="GET",
    ),
    CapabilityEntry(
        capability="List file system access purposes",
        endpoint="/api/admin/v2/fs-access-purposes",
        method="GET",
        required_privilege="%Admin_FileSystemAccess:U",
        iris_version=_VERIFIED_AGAINST,
        verification_status="Verified",
        notes="Result was an empty list on this instance — no purposes configured.",
        command_center_path="/api/iris/fs-access-purposes",
        command_center_method="GET",
    ),
    CapabilityEntry(
        capability="View journal settings",
        endpoint="/api/admin/v2/journal/settings",
        method="GET",
        required_privilege="%Admin_Manage:U or %Admin_Journal:U",
        iris_version=_VERIFIED_AGAINST,
        verification_status="Verified",
        notes="First endpoint verified with an object-shaped (not list-shaped) result.",
        command_center_path="/api/iris/journal/settings",
        command_center_method="GET",
    ),
    CapabilityEntry(
        capability="View OAuth2 Authorization Server configuration",
        endpoint="/api/admin/v2/security/oauth2/server",
        method="GET",
        required_privilege="%Admin_OAuth2_Server:U",
        iris_version=_VERIFIED_AGAINST,
        verification_status="Verified",
        notes="Returns a documented 404 when not configured — this backend treats that as a "
        "normal, successful read, not an error.",
        command_center_path="/api/iris/security/oauth2/server",
        command_center_method="GET",
    ),
    CapabilityEntry(
        capability="List OAuth2 auth server definitions (client-side config)",
        endpoint="/api/admin/v2/security/oauth2/client/server-definitions",
        method="GET",
        required_privilege="%Admin_OAuth2_Client:U",
        iris_version=_VERIFIED_AGAINST,
        verification_status="Verified",
        notes="Result was an empty list on this instance — no server definitions configured.",
        command_center_path="/api/iris/security/oauth2/client/server-definitions",
        command_center_method="GET",
    ),
    CapabilityEntry(
        capability="List clients registered against this instance acting as an OAuth2 auth server",
        endpoint="/api/admin/v2/security/oauth2/server/clients",
        method="GET",
        required_privilege="%Admin_OAuth2_Registration:U",
        iris_version=_VERIFIED_AGAINST,
        verification_status="Verified",
        notes="Result was an empty list on this instance — consistent with no OAuth2 server "
        "configured at all.",
        command_center_path="/api/iris/security/oauth2/server/clients",
        command_center_method="GET",
    ),
    CapabilityEntry(
        capability="List wallet collections",
        endpoint="/api/admin/v2/wallet/collections",
        method="GET",
        required_privilege="%Admin_Wallet:U",
        iris_version=_VERIFIED_AGAINST,
        verification_status="Verified",
        notes="Result was an empty list on this instance — no wallet collections configured.",
        command_center_path="/api/iris/wallet/collections",
        command_center_method="GET",
    ),
    CapabilityEntry(
        capability="See whether security auditing is enabled",
        endpoint="/api/admin/v2/security/audit/enabled",
        method="GET",
        required_privilege="%Admin_Secure:U",
        iris_version=_VERIFIED_AGAINST,
        verification_status="Verified",
        notes="Auditing is genuinely enabled on this instance — real audit records exist to query.",
        command_center_path="/api/iris/security/audit/enabled",
        command_center_method="GET",
    ),
    CapabilityEntry(
        capability="List/search audit records, optionally filtering by time/event/username/etc.",
        endpoint="/api/admin/v2/security/audit/records",
        method="POST",
        required_privilege="%Admin_Secure:U",
        iris_version=_VERIFIED_AGAINST,
        verification_status="Verified",
        notes="Runs as an IRIS async task (202 Accepted + poll); this backend's own route hides "
        "that entirely and exposes it as a plain GET (see command_center_method).",
        command_center_path="/api/iris/security/audit/records",
        command_center_method="GET",
    ),
    CapabilityEntry(
        capability="View the status/result of an async task started by another operation",
        endpoint="/api/admin/v2/async-result",
        method="GET",
        required_privilege="%Admin_Operate:U",
        iris_version=_VERIFIED_AGAINST,
        verification_status="Verified",
        notes="Used internally to poll the audit-records query above to completion — never "
        "exposed as its own public route.",
        command_center_path=None,
    ),
    CapabilityEntry(
        capability="All other documented IRIS SysAdmin REST API capabilities",
        endpoint="(various — see spec/mainspec_v2.json)",
        method="—",
        required_privilege="—",
        iris_version="Not applicable — never verified against a running instance",
        verification_status="Not tested",
        notes="173 remaining paths / 256 remaining operations in spec/mainspec_v2.json. None "
        "should be assumed to work as documented until individually verified.",
        command_center_path=None,
    ),
]
