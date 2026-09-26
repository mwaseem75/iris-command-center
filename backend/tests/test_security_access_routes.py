"""Tests for the Identity & Access routes (app/routes/security_access.py).

The canned bodies are based on real responses, including the missing
%SQLTuneTable in the role list and the mixed AdminOption types ("0" vs
false).
"""

import copy
from typing import Any
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.iris_client.exceptions import IRISConnectionError, IRISResponseError

OK = {"errors": [], "summary": ""}


def envelope(result: Any) -> dict[str, Any]:
    return {"status": OK, "console": [], "result": result}


USERS = [
    {"Name": "Admin", "FullName": "System Administrator", "Namespace": "", "Routine": "",
     "Type": "Password user", "Enabled": True},
    {"Name": "_PUBLIC", "FullName": "(Internal use - not for login)", "Namespace": "", "Routine": "",
     "Type": "Password user", "Enabled": False},
]

USER_DETAIL = {
    "AccountNeverExpires": True, "AutheEnabled": 0, "ChangePassword": False,
    "Comment": "Contact jane.doe at home, not-a-real-note",
    "EmailAddress": "someone@example.invalid", "Enabled": True, "ExpirationDate": "",
    "FullName": "SQL System Manager", "HOTPKeyDisplay": False, "NameSpace": "",
    "PasswordNeverExpires": False, "PhoneNumber": "555-0100-not-real", "PhoneProvider": "CarrierX",
    "Roles": ["%All"], "EscalationRoles": [], "Routine": "",
}

ROLES = [
    {"Name": "%All", "Description": "The Super-User Role", "CreatedBy": "_SYSTEM", "EscalationOnly": False},
    {"Name": "%Manager", "Description": "A role for all System Managers", "CreatedBy": "_SYSTEM",
     "EscalationOnly": False},
    {"Name": "%EnsRole_Developer", "Description": "Developer", "CreatedBy": "_SYSTEM", "EscalationOnly": False},
]

ROLE_DETAILS: dict[str, dict[str, Any]] = {
    "%All": {"Description": "The Super-User Role", "GrantedRoles": [], "EscalationOnly": False, "Resources": []},
    "%Manager": {"Description": "A role for all System Managers", "GrantedRoles": [], "EscalationOnly": False,
                 "Resources": [{"Name": "%Admin_Secure", "Permissions": "U"},
                               {"Name": "%DB_USER", "Permissions": "RW"}]},
    "%EnsRole_Developer": {"Description": "Developer", "GrantedRoles": ["%Developer"], "EscalationOnly": False,
                           "Resources": [{"Name": "%Development", "Permissions": "U"}]},
    # Exists but isn't listed; %Developer only because another role grants it.
    "%Developer": {"Description": "A Role owned by all Developers", "GrantedRoles": [], "EscalationOnly": False,
                   "Resources": [{"Name": "%DB_USER", "Permissions": "RW"}]},
    "%SQLTuneTable": {"Description": "Role for use by tunetable to sample tables irrespective of row level security",
                      "GrantedRoles": [], "EscalationOnly": False,
                      "Resources": [{"Name": "%SQLTuneTable", "Permissions": "U"}]},
}

OWNERS = [
    {"Name": "_SYSTEM", "Type": "User", "AdminOption": "0"},
    {"Name": "_SYSTEM", "Type": "User (escalation)", "AdminOption": False},
    {"Name": "%EnsRole_Developer", "Type": "Role", "AdminOption": "0"},
]

RESOURCES = [
    {"Name": "%DB_USER", "Description": "The USER database", "PublicPermission": "", "ResourceType": "Database",
     "AllowDelete": False},
    {"Name": "%Service_Terminal", "Description": "Controls terminal sessions on Unix", "PublicPermission": "U",
     "ResourceType": "Service", "AllowDelete": False},
]


def fake_iris(role_details: dict[str, dict[str, Any]] | None = None, failing: set[str] = frozenset()):
    """Mock `client.get` for the security GETs."""
    details = ROLE_DETAILS if role_details is None else role_details

    async def get(path: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        name = (params or {}).get("name")
        if path == "/v2/security/users":
            return envelope(copy.deepcopy(USERS))
        if path == "/v2/security/user":
            if name != "_SYSTEM":
                raise IRISResponseError(404)
            return envelope(copy.deepcopy(USER_DETAIL))
        if path == "/v2/security/roles":
            return envelope(copy.deepcopy(ROLES))
        if path == "/v2/security/role":
            if name in failing:
                raise IRISResponseError(500)
            if name not in details:
                raise IRISResponseError(404)
            return envelope(copy.deepcopy(details[name]))
        if path == "/v2/security/role/owners":
            if name not in details:
                raise IRISResponseError(404)
            return envelope(copy.deepcopy(OWNERS))
        if path == "/v2/security/resources":
            return envelope(copy.deepcopy(RESOURCES))
        if path == "/v2/security/resource":
            if name != "%DB_USER":
                raise IRISResponseError(404)
            return envelope({"Description": "The USER database", "PublicPermission": ""})
        raise AssertionError(f"unexpected GET {path}")

    return get


@pytest.fixture
def iris(mock_iris_client: AsyncMock) -> AsyncMock:
    mock_iris_client.get.side_effect = fake_iris()
    return mock_iris_client


def assert_read_only(mock: AsyncMock) -> None:
    mock.put.assert_not_called()
    mock.post.assert_not_called()


# --- users ---


def test_users_list(client: TestClient, iris: AsyncMock) -> None:
    response = client.get("/api/iris/security/users")

    assert response.status_code == 200
    assert response.json()["result"] == USERS
    assert_read_only(iris)


def test_user_detail_withholds_personal_fields(client: TestClient, iris: AsyncMock) -> None:
    response = client.get("/api/iris/security/users/detail", params={"name": "_SYSTEM"})

    assert response.status_code == 200
    for value in ("someone@example.invalid", "555-0100-not-real", "CarrierX", "not-a-real-note", "jane.doe"):
        assert value not in response.text
    result = response.json()["result"]
    for field in ("EmailAddress", "PhoneNumber", "PhoneProvider", "Comment"):
        assert field not in result
    assert result["WithheldFields"] == ["EmailAddress", "PhoneNumber", "PhoneProvider", "Comment"]
    assert result["Roles"] == ["%All"]
    assert result["AutheEnabled"] == 0
    iris.get.assert_awaited_once_with("/v2/security/user", params={"name": "_SYSTEM"})
    assert_read_only(iris)


def test_user_detail_drops_unmodelled_fields(client: TestClient, mock_iris_client: AsyncMock) -> None:
    """Fields IRIS might add later (say, a hash) are dropped."""
    body = envelope({**USER_DETAIL, "PasswordHash": "not-a-real-hash"})
    mock_iris_client.get.return_value = body

    response = client.get("/api/iris/security/users/detail", params={"name": "_SYSTEM"})

    assert "not-a-real-hash" not in response.text
    assert "PasswordHash" not in response.json()["result"]


def test_user_detail_withheld_lists_only_fields_iris_sent(client: TestClient, mock_iris_client: AsyncMock) -> None:
    detail = {k: v for k, v in USER_DETAIL.items() if k not in ("PhoneProvider", "Comment")}
    mock_iris_client.get.return_value = envelope(detail)

    result = client.get("/api/iris/security/users/detail", params={"name": "_SYSTEM"}).json()["result"]

    assert result["WithheldFields"] == ["EmailAddress", "PhoneNumber"]


def test_user_detail_unknown_is_404(client: TestClient, iris: AsyncMock) -> None:
    response = client.get("/api/iris/security/users/detail", params={"name": "nobody"})

    assert response.status_code == 404
    assert response.json()["detail"] == "IRIS reports no user with this name"


def test_user_detail_requires_name(client: TestClient, iris: AsyncMock) -> None:
    assert client.get("/api/iris/security/users/detail").status_code == 422
    iris.get.assert_not_awaited()


# --- roles ---


def test_roles_list_is_passed_through_without_additions(client: TestClient, iris: AsyncMock) -> None:
    result = client.get("/api/iris/security/roles").json()["result"]

    assert [role["Name"] for role in result] == ["%All", "%Manager", "%EnsRole_Developer"]


def test_role_detail(client: TestClient, iris: AsyncMock) -> None:
    result = client.get("/api/iris/security/roles/detail", params={"name": "%Manager"}).json()["result"]

    assert result["Resources"] == [{"Name": "%Admin_Secure", "Permissions": "U"},
                                   {"Name": "%DB_USER", "Permissions": "RW"}]
    assert result["GrantedRoles"] == []


def test_role_detail_unknown_is_404(client: TestClient, iris: AsyncMock) -> None:
    response = client.get("/api/iris/security/roles/detail", params={"name": "%Nope"})

    assert response.status_code == 404
    assert response.json()["detail"] == "IRIS reports no role with this name"


def test_role_owners_keep_mixed_admin_option_types(client: TestClient, iris: AsyncMock) -> None:
    result = client.get("/api/iris/security/roles/owners", params={"name": "%All"}).json()["result"]

    assert result == OWNERS
    assert result[0]["AdminOption"] == "0"
    assert result[1]["AdminOption"] is False


def test_access_map_merges_details_and_marks_unlisted_roles(client: TestClient, iris: AsyncMock) -> None:
    body = client.get("/api/iris/security/roles/access-map").json()

    assert body["status"] == OK
    by_name = {entry["Name"]: entry for entry in body["result"]}
    assert [entry["Name"] for entry in body["result"] if entry["Listed"]] == ["%All", "%Manager", "%EnsRole_Developer"]
    # %Developer is granted by a listed role and %SQLTuneTable is missing
    # from the list; both are confirmed by their detail call.
    assert sorted(name for name, entry in by_name.items() if not entry["Listed"]) == ["%Developer", "%SQLTuneTable"]
    assert by_name["%Manager"]["Detail"]["Resources"][0] == {"Name": "%Admin_Secure", "Permissions": "U"}
    assert by_name["%All"]["Detail"]["Resources"] == []
    assert_read_only(iris)


def test_access_map_never_adds_a_role_iris_does_not_confirm(client: TestClient, mock_iris_client: AsyncMock) -> None:
    details = {k: v for k, v in ROLE_DETAILS.items() if k != "%SQLTuneTable"}
    mock_iris_client.get.side_effect = fake_iris(details)

    names = [e["Name"] for e in client.get("/api/iris/security/roles/access-map").json()["result"]]

    assert "%SQLTuneTable" not in names


def test_access_map_detail_failure_is_a_warning(client: TestClient, mock_iris_client: AsyncMock) -> None:
    mock_iris_client.get.side_effect = fake_iris(failing={"%Manager"})

    body = client.get("/api/iris/security/roles/access-map").json()

    by_name = {entry["Name"]: entry for entry in body["result"]}
    assert by_name["%Manager"]["Detail"] is None
    assert by_name["%Manager"]["Listed"] is True
    assert body["status"]["errors"] == [{"error": "Role detail unavailable for %Manager", "role": "%Manager"}]
    assert body["status"]["summary"] == "Role detail unavailable for 1 role"


def test_access_map_list_failure_fails_request(client: TestClient, mock_iris_client: AsyncMock) -> None:
    mock_iris_client.get.side_effect = IRISConnectionError("boom")

    response = client.get("/api/iris/security/roles/access-map")

    assert response.status_code == 502
    assert response.json()["detail"] == "Could not connect to IRIS"


# --- resources ---


def test_resources_list_and_detail(client: TestClient, iris: AsyncMock) -> None:
    assert client.get("/api/iris/security/resources").json()["result"] == RESOURCES
    detail = client.get("/api/iris/security/resources/detail", params={"name": "%DB_USER"}).json()["result"]
    assert detail == {"Description": "The USER database", "PublicPermission": ""}


def test_resource_detail_unknown_is_404(client: TestClient, iris: AsyncMock) -> None:
    response = client.get("/api/iris/security/resources/detail", params={"name": "%Nope"})

    assert response.status_code == 404
    assert response.json()["detail"] == "IRIS reports no resource with this name"


def test_non_404_errors_are_generic(client: TestClient, mock_iris_client: AsyncMock) -> None:
    mock_iris_client.get.side_effect = IRISResponseError(403)

    response = client.get("/api/iris/security/users")

    assert response.status_code == 502
    assert response.json()["detail"] == "IRIS returned an unexpected HTTP 403"


def test_unexpected_shape_is_rejected(client: TestClient, mock_iris_client: AsyncMock) -> None:
    mock_iris_client.get.return_value = envelope([{"Name": "x", "Description": "y"}])

    with pytest.raises(ValidationError):
        client.get("/api/iris/security/resources")
