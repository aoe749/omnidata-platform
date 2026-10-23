"""Authorisation is enforced by dependencies *before* any database is touched."""

import pytest
from fastapi.testclient import TestClient

from app.api.deps import get_current_principal
from app.core.permissions import Principal
from app.main import create_app


@pytest.fixture
def app():
    application = create_app()
    yield application
    application.dependency_overrides.clear()


def as_role(app, permissions):
    app.dependency_overrides[get_current_principal] = lambda: Principal(
        user_id=7, email="t@example.com", full_name="T", role="test", permissions=permissions
    )
    return TestClient(app)


def test_missing_token_is_401(app):
    response = TestClient(app).get("/api/v1/transactions")
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"


@pytest.mark.parametrize(
    "method,path,permissions",
    [
        ("get", "/api/v1/transactions", {}),
        ("get", "/api/v1/transactions", {"transactions": 16}),  # export only, no read
        ("get", "/api/v1/transactions/export", {"transactions": 1}),  # read only, no export
        ("post", "/api/v1/sync/migrate", {"sync": 1}),  # needs create (2)
        ("post", "/api/v1/sync/publish", {"sync": 1 | 2}),  # needs update (4)
        ("post", "/api/v1/sync/ingest", {"sync": 1 | 2}),
        ("get", "/api/v1/users", {"transactions": 31}),  # wrong resource
        ("delete", "/api/v1/users/3", {"users": 1 | 2 | 4}),  # needs delete (8)
        ("get", "/api/v1/stats/overview", {}),
    ],
)
def test_insufficient_mask_is_403(app, method, path, permissions):
    client = as_role(app, permissions)
    kwargs = {"json": {}} if method == "post" else {}
    response = getattr(client, method)(path, **kwargs)
    assert response.status_code == 403, response.text
    assert "Missing" in response.json()["detail"]


def test_403_message_lists_granted_actions(app):
    response = as_role(app, {"sync": 1 | 16}).post("/api/v1/sync/migrate", json={})
    assert response.status_code == 403
    assert "granted: read, export" in response.json()["detail"]


def test_me_returns_profile_and_action_bits(app):
    response = as_role(app, {"sync": 3}).get("/api/v1/auth/me")
    assert response.status_code == 200
    body = response.json()
    assert body["permissions"] == {"sync": 3}
    assert body["action_bits"]["export"] == 16
