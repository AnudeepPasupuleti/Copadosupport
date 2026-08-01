#!/usr/bin/env python3
"""Inject a UI checklist Export JSON into a backup dump for a given user email."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("backup", type=Path, help="Existing backup_v1 JSON to update")
    parser.add_argument("checklist", type=Path, help="File from ⋯ → Export on the site")
    parser.add_argument("--email", required=True, help="User email to attach state to")
    parser.add_argument("-o", "--output", type=Path, help="Output path (default: overwrite backup)")
    args = parser.parse_args()

    backup = json.loads(args.backup.read_text(encoding="utf-8"))
    checklist = json.loads(args.checklist.read_text(encoding="utf-8"))
    if "items" not in checklist:
        raise SystemExit("Checklist file missing 'items' — use ⋯ → Export from the app")

    email = args.email.strip().lower()
    users = backup.setdefault("tables", {}).setdefault("users", [])
    states = backup.setdefault("tables", {}).setdefault("user_state", [])

    user = next((u for u in users if (u.get("email") or "").lower() == email), None)
    if not user:
        # Assign a temporary high id; restore matches by email when merging later
        next_id = max([int(u["id"]) for u in users] + [0]) + 1
        user = {
            "id": next_id,
            "username": None,
            "password_hash": None,
            "google_sub": None,
            "github_id": None,
            "email": email,
            "name": email.split("@")[0],
            "picture": None,
            "auth_type": "oauth",
            "created_at": None,
        }
        users.append(user)

    payload = {
        "activeDate": checklist.get("activeDate"),
        "items": checklist.get("items") or [],
        "history": checklist.get("history") or [],
        "diary": checklist.get("diary") or [],
        "updatedAt": checklist.get("updatedAt")
        or int(datetime.now(timezone.utc).timestamp() * 1000),
    }
    uid = int(user["id"])
    states[:] = [s for s in states if int(s["user_id"]) != uid]
    states.append(
        {
            "user_id": uid,
            "payload": json.dumps(payload),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
    )

    out = args.output or args.backup
    out.write_text(json.dumps(backup, indent=2))
    print(f"Attached checklist for {email} → {out}")


if __name__ == "__main__":
    main()
