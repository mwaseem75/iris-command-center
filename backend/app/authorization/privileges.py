"""The IRIS `%Admin_*` privileges CONFIRMED during Phase 1 verification.

Every member below was individually exercised by a real, successful API
call against a running IRIS 2026.2 instance, and each name matches exactly
what `GET /api/admin/info` returned for `_SYSTEM` (see
docs/api-capability-matrix.md, "Privilege Coverage Summary — Complete").

`ConfigStore` is deliberately NOT a member of this enum. It is listed in
mainspec_v2.json's `Info` schema, but it was absent from every observed
`/info` response on this instance — never confirmed present, `true`, or
`false`. Treating it as a known/confirmed privilege would be an assumption
this project has explicitly avoided making everywhere else. Because this
enum is the only source of "known" privilege names used anywhere in the
authorization layer (see service.py), `ConfigStore` cannot be required by
any operation, nor can any caller-supplied claim of holding `"ConfigStore"`
be recognized as a real, confirmed privilege — it is simply not a valid
enum value, so it is silently dropped by `parse_available_privileges`
rather than granting anything.
"""

from enum import Enum


class IRISPrivilege(str, Enum):
    MANAGE = "Manage"
    OPERATE = "Operate"
    SECURE = "Secure"
    EXTERNAL_LANGUAGE_SERVER_EDIT = "ExternalLanguageServerEdit"
    TASK = "Task"
    FILE_SYSTEM_ACCESS = "FileSystemAccess"
    JOURNAL = "Journal"
    OAUTH2_SERVER = "OAuth2_Server"
    OAUTH2_CLIENT = "OAuth2_Client"
    OAUTH2_REGISTRATION = "OAuth2_Registration"
    WALLET = "Wallet"


def parse_available_privileges(raw_privileges: object) -> frozenset[IRISPrivilege]:
    """Safely convert arbitrary input (e.g. keys from an IRIS /info response,
    or any other caller-supplied iterable) into a set of KNOWN privileges.

    Anything that isn't a string, or is a string that doesn't exactly match
    a confirmed privilege name (including "ConfigStore", any typo, or any
    unrecognized name), is silently dropped rather than raising or being
    granted. This function never raises — malformed input safely yields an
    empty (or partial) set, never an error and never an unearned privilege.
    """
    if not isinstance(raw_privileges, (list, tuple, set, frozenset)):
        return frozenset()

    confirmed: set[IRISPrivilege] = set()
    for item in raw_privileges:
        if not isinstance(item, str):
            continue
        try:
            confirmed.add(IRISPrivilege(item))
        except ValueError:
            continue  # unrecognized/malformed privilege name — ignored, never granted
    return frozenset(confirmed)
