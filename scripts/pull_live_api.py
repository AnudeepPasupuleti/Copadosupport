#!/usr/bin/env python3
"""Pull recoverable data from a running Copado Support instance via existing APIs.

No Render Shell required. Does not redeploy (redeploy would wipe Free SQLite).

Usage:
  python scripts/pull_live_api.py \\
    --base-url https://teamcopa.onrender.com \\
    --admin-user admin \\
    --admin-password 'YOUR_PASSWORD' \\
    -o data/backups/live-api-dump.json

Then also: log in as each OAuth user on the live site → ⋯ → Export
(checklist JSON). Merge later with restore_backup.py + inject_checklist.py.
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx


def _login(client: httpx.Client, base: str, username: str, password: str) -> None:
    r = client.post(
        f"{base}/auth/login",
        json={"username": username, "password": password},
    )
    if r.status_code != 200:
        raise SystemExit(f"Admin login failed ({r.status_code}): {r.text}")


def _get(client: httpx.Client, url: str) -> Any:
    r = client.get(url)
    if r.status_code != 200:
        raise SystemExit(f"GET {url} failed ({r.status_code}): {r.text}")
    return r.json()


def pull(base_url: str, username: str, password: str) -> dict:
    base = base_url.rstrip("/")
    with httpx.Client(follow_redirects=True, timeout=60.0) as client:
        _login(client, base, username, password)

        me = _get(client, f"{base}/api/me")
        admin_state = _get(client, f"{base}/api/state")
        users = _get(client, f"{base}/api/admin/users")
        tasks_brief = _get(client, f"{base}/api/queue/tasks?scope=all")
        settings = _get(client, f"{base}/api/admin/settings")

        tasks_full = []
        comments = []
        for t in tasks_brief:
            detail = _get(client, f"{base}/api/queue/tasks/{t['id']}")
            tasks_full.append(detail)
            for c in detail.get("comments") or []:
                comments.append({**c, "task_id": detail["id"]})

    # Map into backup_v1 shape (best-effort; IDs are live IDs)
    user_rows = []
    for u in users:
        user_rows.append(
            {
                "id": u["id"],
                "username": u.get("username"),
                "password_hash": None,  # not exposed by API
                "google_sub": None,
                "github_id": None,
                "email": u.get("email"),
                "name": u.get("name") or "",
                "picture": u.get("picture"),
                "auth_type": u.get("auth_type") or "oauth",
                "created_at": None,
            }
        )

    state_rows = []
    if me.get("id") is not None:
        state_rows.append(
            {
                "user_id": me["id"],
                "payload": json.dumps(admin_state),
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }
        )

    task_rows = []
    for t in tasks_full:
        reporter = t.get("reporter") or {}
        assignee = t.get("assignee")
        task_rows.append(
            {
                "id": t["id"],
                "case_number": t.get("case_number"),
                "title": t.get("title"),
                "description": t.get("description") or "",
                "status": t.get("status"),
                "priority": t.get("priority"),
                "due_date": t.get("due_date"),
                "tags": t.get("tags") or "",
                "reporter_id": reporter.get("id"),
                "assignee_id": (assignee or {}).get("id"),
                "created_at": t.get("created_at"),
                "updated_at": t.get("updated_at"),
            }
        )

    comment_rows = []
    for c in comments:
        author = c.get("author") or {}
        comment_rows.append(
            {
                "id": c.get("id"),
                "task_id": c["task_id"],
                "author_id": author.get("id"),
                "body": c.get("body") or "",
                "created_at": c.get("created_at"),
            }
        )

    settings_rows = [
        {
            "key": "google_login_enabled",
            "value": "true" if settings.get("google_login_enabled") else "false",
        },
        {
            "key": "github_login_enabled",
            "value": "true" if settings.get("github_login_enabled") else "false",
        },
    ]
    # Keep case counter above max CS-N seen
    max_n = 1000
    for t in task_rows:
        cn = t.get("case_number") or ""
        if cn.startswith("CS-"):
            try:
                max_n = max(max_n, int(cn.split("-", 1)[1]))
            except ValueError:
                pass
    settings_rows.append({"key": "team_case_counter", "value": str(max_n)})

    return {
        "format": "copado_support_backup_v1",
        "source": "live-api",
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "note": (
            "Pulled via public APIs (no Shell). password_hash/oauth ids not included. "
            "Only Admin checklist state included; other users must Export from UI."
        ),
        "tables": {
            "users": user_rows,
            "user_state": state_rows,
            "app_settings": settings_rows,
            "team_tasks": task_rows,
            "task_comments": comment_rows,
            "notifications": [],
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="https://teamcopa.onrender.com")
    parser.add_argument("--admin-user", default="admin")
    parser.add_argument("--admin-password", required=True)
    parser.add_argument("-o", "--output", type=Path, required=True)
    args = parser.parse_args()

    payload = pull(args.base_url, args.admin_user, args.admin_password)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, default=str))
    counts = {k: len(v) for k, v in payload["tables"].items()}
    print(f"Wrote {args.output}")
    print("Rows:", counts)
    if counts.get("team_tasks", 0) == 0 and counts.get("users", 0) <= 2:
        print(
            "Note: little/no queue data — live SQLite may already have been wiped by a redeploy."
        )


if __name__ == "__main__":
    main()
