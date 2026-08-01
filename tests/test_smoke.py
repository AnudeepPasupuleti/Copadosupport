import os
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture()
def client(tmp_path, monkeypatch):
    db_path = tmp_path / "test.db"
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{db_path}")
    monkeypatch.setenv("SESSION_SECRET", "test-session-secret-at-least-24")
    monkeypatch.setenv("ADMIN_USERNAME", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", "admin")
    monkeypatch.setenv("BASE_URL", "http://localhost:8080")
    monkeypatch.setenv("ENV", "development")
    monkeypatch.setenv("GITHUB_CLIENT_ID", "")
    monkeypatch.setenv("GITHUB_CLIENT_SECRET", "")
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "")
    monkeypatch.setenv("USER1_GITHUB_LOGIN", "")

    # Reload config + app modules so env overrides take effect
    import importlib
    import backend.config as config
    import backend.db as db
    import backend.seed as seed
    import backend.queue as queue
    import backend.main as main

    importlib.reload(config)
    importlib.reload(db)
    importlib.reload(seed)
    importlib.reload(queue)
    importlib.reload(main)

    with TestClient(main.app) as c:
        yield c


def test_health(client):
    res = client.get("/api/health")
    assert res.status_code == 200
    assert res.json()["ok"] is True


def test_admin_login_and_state(client):
    assert client.get("/api/me").status_code == 401

    login = client.post("/auth/login", json={"username": "admin", "password": "admin"})
    assert login.status_code == 200
    assert login.json()["user"]["is_admin"] is True

    me = client.get("/api/me")
    assert me.status_code == 200
    assert me.json()["username"] == "admin"

    state = client.get("/api/state")
    assert state.status_code == 200
    body = state.json()
    assert "items" in body

    payload = {
        "activeDate": "2026-08-01",
        "items": [{"id": "1", "text": "smoke", "checked": False}],
        "history": [],
        "diary": [],
        "updatedAt": 123,
    }
    put = client.put("/api/state", json=payload)
    assert put.status_code == 200

    again = client.get("/api/state")
    assert again.status_code == 200
    assert again.json()["items"][0]["text"] == "smoke"


def test_admin_gate_blocks_non_admin(client):
    from unittest.mock import MagicMock

    from fastapi import HTTPException

    from backend.db import SessionLocal
    from backend.main import admin_js, admin_page

    res = client.get("/admin", follow_redirects=False)
    assert res.status_code == 302
    assert res.headers["location"] == "/login"

    client.post("/auth/login", json={"username": "admin", "password": "admin"})
    created = client.post(
        "/api/admin/users",
        json={"email": "user@example.com", "name": "User", "auth_type": "oauth"},
    )
    assert created.status_code == 200
    user_id = created.json()["id"]

    db = SessionLocal()
    try:
        req = MagicMock()
        req.session = {"user_id": user_id}
        blocked = admin_page(req, db)
        assert blocked.status_code == 302
        assert blocked.headers["location"] == "/"
        try:
            admin_js(req, db)
            assert False, "expected 403"
        except HTTPException as exc:
            assert exc.status_code == 403
    finally:
        db.close()

    client.post("/auth/logout")
    assert client.get("/api/admin/settings").status_code == 401


def test_change_password(client):
    client.post("/auth/login", json={"username": "admin", "password": "admin"})
    bad = client.post(
        "/api/admin/change-password",
        json={"current_password": "wrong", "new_password": "newpassword1"},
    )
    assert bad.status_code == 400

    ok = client.post(
        "/api/admin/change-password",
        json={"current_password": "admin", "new_password": "newpassword1"},
    )
    assert ok.status_code == 200

    client.post("/auth/logout")
    assert client.post("/auth/login", json={"username": "admin", "password": "admin"}).status_code == 401
    assert client.post("/auth/login", json={"username": "admin", "password": "newpassword1"}).status_code == 200


def test_team_queue_dashboard_and_notifications(client):
    login = client.post("/auth/login", json={"username": "admin", "password": "admin"})
    assert login.status_code == 200
    admin_id = login.json()["user"]["id"]

    created = client.post(
        "/api/queue/tasks",
        json={
            "title": "Pipeline fails on deploy",
            "description": "Repro steps…",
            "priority": "high",
            "status": "investigating",
            "assignee_id": admin_id,
            "due_date": "2099-01-15",
            "tags": "pipeline,production",
        },
    )
    assert created.status_code == 200
    task = created.json()
    assert task["case_number"].startswith("CS-")
    assert task["title"] == "Pipeline fails on deploy"
    task_id = task["id"]

    listed = client.get("/api/queue/tasks")
    assert listed.status_code == 200
    assert any(t["id"] == task_id for t in listed.json())

    comment = client.post(
        f"/api/queue/tasks/{task_id}/comments",
        json={"body": "Looking into logs now"},
    )
    assert comment.status_code == 200
    assert len(comment.json()["comments"]) == 1

    dash = client.get("/api/queue/dashboard")
    assert dash.status_code == 200
    body = dash.json()
    assert body["total"] >= 1
    assert body["mine"] >= 1
    assert body["by_status"]["investigating"] >= 1
    assert "my_tickets" in body
    assert any(t["id"] == task_id for t in body["my_tickets"])

    client.post(
        "/api/admin/users",
        json={"email": "agent@example.com", "name": "Agent", "auth_type": "oauth"},
    )
    users = client.get("/api/queue/users").json()
    agent = next(u for u in users if u["email"] == "agent@example.com")

    patched = client.patch(
        f"/api/queue/tasks/{task_id}",
        json={"assignee_id": agent["id"]},
    )
    assert patched.status_code == 200
    assert patched.json()["assignee"]["id"] == agent["id"]

    notifs = client.get("/api/queue/notifications").json()
    assert "items" in notifs
    assert "unread" in notifs


def test_user_roles(client):
    client.post("/auth/login", json={"username": "admin", "password": "admin"})
    me = client.get("/api/me").json()
    assert me["role"] == "admin"
    assert me["is_admin"] is True

    created = client.post(
        "/api/admin/users",
        json={"email": "mgr@example.com", "name": "Mgr", "auth_type": "oauth", "role": "member"},
    )
    assert created.status_code == 200
    user_id = created.json()["id"]
    assert created.json()["role"] == "member"

    promoted = client.post(
        f"/api/admin/users/{user_id}/role",
        json={"role": "manager"},
    )
    assert promoted.status_code == 200
    assert promoted.json()["role"] == "manager"
    assert promoted.json()["is_manager"] is True

    # Cannot demote self
    bad = client.post(
        f"/api/admin/users/{me['id']}/role",
        json={"role": "member"},
    )
    assert bad.status_code == 400


def test_impersonate_and_reset_password(client):
    client.post("/auth/login", json={"username": "admin", "password": "admin"})
    created = client.post(
        "/api/admin/users",
        json={"email": "agent@example.com", "name": "Agent", "auth_type": "oauth"},
    )
    assert created.status_code == 200
    user_id = created.json()["id"]

    reset = client.post(
        f"/api/admin/users/{user_id}/reset-password",
        json={"new_password": "agentpass1", "username": "agent1"},
    )
    assert reset.status_code == 200
    assert reset.json()["username"] == "agent1"

    imp = client.post(f"/api/admin/users/{user_id}/impersonate")
    assert imp.status_code == 200
    assert imp.json()["user"]["email"] == "agent@example.com"

    me = client.get("/api/me")
    assert me.status_code == 200
    assert me.json()["impersonating"] is True
    assert me.json()["email"] == "agent@example.com"
    assert me.json()["is_admin"] is False

    # Admin APIs blocked while impersonating
    assert client.get("/api/admin/users").status_code == 403

    stop = client.post("/api/admin/stop-impersonating")
    assert stop.status_code == 200
    assert stop.json()["user"]["is_admin"] is True
    assert client.get("/api/me").json()["impersonating"] is False

    client.post("/auth/logout")
    login_user = client.post("/auth/login", json={"username": "agent1", "password": "agentpass1"})
    assert login_user.status_code == 200
    assert login_user.json()["user"]["email"] == "agent@example.com"
