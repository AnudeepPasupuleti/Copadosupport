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
    import backend.deps as deps
    import backend.seed as seed
    import backend.auth as auth
    import backend.admin as admin
    import backend.queue as queue
    import backend.org as org
    import backend.workspaces as workspaces
    import backend.events as events
    import backend.sse as sse
    import backend.main as main

    importlib.reload(config)
    importlib.reload(db)
    importlib.reload(deps)
    importlib.reload(seed)
    importlib.reload(auth)
    importlib.reload(admin)
    importlib.reload(workspaces)
    importlib.reload(events)
    importlib.reload(queue)
    importlib.reload(org)
    importlib.reload(sse)
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
    listed_body = listed.json()
    listed_items = listed_body["items"] if isinstance(listed_body, dict) else listed_body
    assert any(t["id"] == task_id for t in listed_items)

    comment = client.post(
        f"/api/queue/tasks/{task_id}/comments",
        json={"body": "Looking into logs now"},
    )
    assert comment.status_code == 200
    assert len(comment.json()["comments"]) == 1
    current_version = comment.json()["version"]

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
        json={"assignee_id": agent["id"], "version": current_version},
    )
    assert patched.status_code == 200
    assert patched.json()["assignee"]["id"] == agent["id"]

    notifs = client.get("/api/queue/notifications").json()
    assert "items" in notifs
    assert "unread" in notifs


def test_user_roles(client):
    client.post("/auth/login", json={"username": "admin", "password": "admin"})
    me = client.get("/api/me").json()
    assert me["role"] == "super_admin"
    assert me["is_admin"] is True
    assert me["is_super_admin"] is True

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

    status = client.get("/api/admin/status")
    assert status.status_code == 200
    body = status.json()
    assert body["user_count"] >= 2
    assert "dialect" in body
    assert body["roles"]["super_admin"] >= 1


def test_super_admin_impersonate_admins(client):
    client.post("/auth/login", json={"username": "admin", "password": "admin"})
    me = client.get("/api/me").json()
    assert me["is_super_admin"] is True

    other_admin = client.post(
        "/api/admin/users",
        json={
            "email": "admin2@example.com",
            "name": "Admin Two",
            "auth_type": "password",
            "username": "admin2",
            "password": "admin2pass",
            "role": "admin",
        },
    )
    assert other_admin.status_code == 200
    other_admin_id = other_admin.json()["id"]
    assert other_admin.json()["role"] == "admin"
    assert other_admin.json()["is_admin"] is True
    assert other_admin.json()["is_super_admin"] is False

    other_sa = client.post(
        "/api/admin/users",
        json={
            "email": "sa2@example.com",
            "name": "Super Two",
            "auth_type": "password",
            "username": "sa2",
            "password": "sa2pass12",
            "role": "super_admin",
        },
    )
    assert other_sa.status_code == 200
    other_sa_id = other_sa.json()["id"]
    assert other_sa.json()["is_super_admin"] is True

    # Super Admin can impersonate a normal Admin
    ok = client.post(f"/api/admin/users/{other_admin_id}/impersonate")
    assert ok.status_code == 200
    assert ok.json()["user"]["email"] == "admin2@example.com"
    assert client.get("/api/me").json()["impersonating"] is True

    stop = client.post("/api/admin/stop-impersonating")
    assert stop.status_code == 200
    assert stop.json()["user"]["is_super_admin"] is True

    # Super Admin cannot impersonate another Super Admin
    blocked_sa = client.post(f"/api/admin/users/{other_sa_id}/impersonate")
    assert blocked_sa.status_code == 400

    client.post("/auth/logout")
    assert client.post("/auth/login", json={"username": "admin2", "password": "admin2pass"}).status_code == 200
    assert client.get("/api/me").json()["role"] == "admin"

    peer = client.post(
        "/api/admin/users",
        json={
            "email": "admin3@example.com",
            "name": "Admin Three",
            "auth_type": "oauth",
            "role": "admin",
        },
    )
    assert peer.status_code == 200

    # Normal Admin cannot impersonate another Admin
    denied = client.post(f"/api/admin/users/{peer.json()['id']}/impersonate")
    assert denied.status_code == 400
    assert "admin" in denied.json()["detail"].lower()


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


def test_profile_update_and_password(client):
    client.post("/auth/login", json={"username": "admin", "password": "admin"})
    me = client.get("/api/me").json()
    assert me["name"] == "Admin"

    updated = client.put(
        "/api/me/profile",
        json={"name": "Support Admin"},
    )
    assert updated.status_code == 200
    assert updated.json()["name"] == "Support Admin"

    pw = client.post(
        "/api/me/password",
        json={"current_password": "admin", "new_password": "adminpass1"},
    )
    assert pw.status_code == 200
    client.post("/auth/logout")
    assert client.post("/auth/login", json={"username": "admin", "password": "admin"}).status_code == 401
    assert client.post("/auth/login", json={"username": "admin", "password": "adminpass1"}).status_code == 200


def test_org_chart_permissions_and_cycle(client):
    client.post("/auth/login", json={"username": "admin", "password": "admin"})

    member = client.post(
        "/api/admin/users",
        json={
            "email": "member@example.com",
            "name": "Member",
            "auth_type": "password",
            "username": "member1",
            "password": "memberpass1",
            "role": "member",
        },
    )
    assert member.status_code == 200
    member_id = member.json()["id"]

    manager = client.post(
        "/api/admin/users",
        json={
            "email": "manager@example.com",
            "name": "Manager",
            "auth_type": "password",
            "username": "manager1",
            "password": "managerpass1",
            "role": "manager",
        },
    )
    assert manager.status_code == 200
    manager_id = manager.json()["id"]

    client.post("/auth/logout")
    assert client.post("/auth/login", json={"username": "member1", "password": "memberpass1"}).status_code == 200

    chart = client.get("/api/org/chart")
    assert chart.status_code == 200
    assert chart.json()["can_edit"] is False
    assert client.get("/api/me").json()["can_edit_org"] is False
    assert client.get("/api/me").json()["can_view_org"] is True

    denied = client.post("/api/org/teams", json={"name": "L1 Support", "description": "Front line"})
    assert denied.status_code == 403

    client.post("/auth/logout")
    assert client.post("/auth/login", json={"username": "manager1", "password": "managerpass1"}).status_code == 200
    assert client.get("/api/me").json()["can_edit_org"] is True

    team = client.post(
        "/api/org/teams",
        json={"name": "L1 Support", "description": "Front line"},
    )
    assert team.status_code == 200
    team_id = team.json()["id"]

    added = client.post(
        f"/api/org/teams/{team_id}/members",
        json={"user_id": member_id, "title": "Agent"},
    )
    assert added.status_code == 200
    assert any(m["id"] == member_id for m in added.json()["members"])

    set_mgr = client.put(
        f"/api/org/users/{member_id}/manager",
        json={"manager_id": manager_id},
    )
    assert set_mgr.status_code == 200
    assert set_mgr.json()["reports_to_id"] == manager_id

    client.post("/auth/logout")
    assert client.post("/auth/login", json={"username": "member1", "password": "memberpass1"}).status_code == 200
    me_member = client.get("/api/me").json()
    assert me_member["manager_name"]
    assert me_member["team_name"] == "L1 Support"
    assert me_member["can_view_org"] is True
    assert me_member["can_edit_org"] is False

    client.post("/auth/logout")
    assert client.post("/auth/login", json={"username": "manager1", "password": "managerpass1"}).status_code == 200

    # Cycle: manager reports to member who already reports to manager
    cycle = client.put(
        f"/api/org/users/{manager_id}/manager",
        json={"manager_id": member_id},
    )
    assert cycle.status_code == 400
    assert "cycle" in cycle.json()["detail"].lower()

    chart2 = client.get("/api/org/chart")
    assert chart2.status_code == 200
    assert chart2.json()["can_edit"] is True
    assert any(t["id"] == team_id for t in chart2.json()["teams"])


def test_phase4_versioning_activity_idempotency(client):
    login = client.post("/auth/login", json={"username": "admin", "password": "admin"})
    assert login.status_code == 200

    created = client.post(
        "/api/queue/tasks",
        headers={"Idempotency-Key": "create-case-1"},
        json={"title": "Versioned case", "status": "new", "priority": "medium"},
    )
    assert created.status_code == 200
    task = created.json()
    assert task["version"] == 1
    task_id = task["id"]

    # Idempotent replay returns same payload
    again = client.post(
        "/api/queue/tasks",
        headers={"Idempotency-Key": "create-case-1"},
        json={"title": "Versioned case", "status": "new", "priority": "medium"},
    )
    assert again.status_code == 200
    assert again.json()["id"] == task_id

    ok = client.patch(
        f"/api/queue/tasks/{task_id}",
        json={"status": "investigating", "version": 1},
    )
    assert ok.status_code == 200
    assert ok.json()["version"] == 2
    assert ok.json()["status"] == "investigating"

    conflict = client.patch(
        f"/api/queue/tasks/{task_id}",
        json={"status": "waiting_customer", "version": 1},
    )
    assert conflict.status_code == 409
    assert conflict.json()["code"] == "version_conflict"
    assert conflict.json()["task"]["version"] == 2

    acts = client.get(f"/api/queue/tasks/{task_id}/activities")
    assert acts.status_code == 200
    types = [a["type"] for a in acts.json()["items"]]
    assert "case.created" in types
    assert "case.updated" in types

    listed = client.get("/api/queue/tasks?limit=10")
    assert listed.status_code == 200
    body = listed.json()
    assert "items" in body
    assert "next_cursor" in body

    mentionee = client.post(
        "/api/admin/users",
        json={
            "email": "peer@example.com",
            "name": "Peer",
            "auth_type": "password",
            "username": "peer1",
            "password": "peerpass1",
            "role": "member",
        },
    )
    assert mentionee.status_code == 200
    peer_id = mentionee.json()["id"]

    commented = client.post(
        f"/api/queue/tasks/{task_id}/comments",
        json={"body": "Please check this", "mention_ids": [peer_id]},
    )
    assert commented.status_code == 200
    assert any(c.get("mention_ids") == [peer_id] for c in commented.json()["comments"])
