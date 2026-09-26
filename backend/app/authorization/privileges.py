"""The %Admin_* privileges we know about (as reported by IRIS's /info).

ConfigStore is in the OpenAPI spec but never showed up in /info on 2026.2,
so it's left out on purpose and can't be required or claimed.
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
    """Turn a list of names into known privileges.

    Unknown names and non-strings are ignored rather than raising.
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
            continue  # unknown name, ignore it
    return frozenset(confirmed)
