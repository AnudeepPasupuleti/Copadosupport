#!/usr/bin/env python3
"""Restore / merge one or more JSON backups into a target DATABASE_URL.

Users are matched by email. Checklist state keeps the newer updated_at.
Team tasks are matched by case_number; comments from both dumps are kept.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

# Allow `python scripts/restore_backup.py` from repo root
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from sqlalchemy.orm import Session  # noqa: E402

from backend.config import normalize_database_url  # noqa: E402
from backend.db import (  # noqa: E402
    AppSetting,
    Notification,
    TaskComment,
    TeamTask,
    User,
    UserState,
    init_db,
)
from backend import db as db_mod  # noqa: E402


def _parse_dt(value: Any) -> Optional[datetime]:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value).replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(text)
        except ValueError:
            return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _aware(dt: Optional[datetime]) -> Optional[datetime]:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _state_updated_at(payload_json: str) -> float:
    try:
        data = json.loads(payload_json or "{}")
        return float(data.get("updatedAt") or 0)
    except (TypeError, ValueError, json.JSONDecodeError):
        return 0.0


def _load_dump(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("format") != "copado_support_backup_v1":
        raise SystemExit(f"Unsupported backup format in {path}")
    return data


def _upsert_user(db: Session, row: dict, id_map: dict[int, int]) -> None:
    old_id = int(row["id"])
    email = (row.get("email") or "").strip().lower()
    if not email:
        print(f"  skip user id={old_id}: no email")
        return

    existing = db.query(User).filter(User.email == email).one_or_none()
    if existing:
        # Fill missing identity fields from backup (don't wipe newer live values blindly)
        if not existing.username and row.get("username"):
            existing.username = row["username"]
        if not existing.password_hash and row.get("password_hash"):
            existing.password_hash = row["password_hash"]
        if not existing.google_sub and row.get("google_sub"):
            existing.google_sub = row["google_sub"]
        if not existing.github_id and row.get("github_id"):
            existing.github_id = row["github_id"]
        if row.get("name") and (not existing.name or existing.name == existing.email):
            existing.name = row["name"]
        if row.get("picture") and not existing.picture:
            existing.picture = row["picture"]
        id_map[old_id] = existing.id
        return

    user = User(
        username=row.get("username"),
        password_hash=row.get("password_hash"),
        google_sub=row.get("google_sub"),
        github_id=row.get("github_id"),
        email=email,
        name=row.get("name") or "",
        picture=row.get("picture"),
        auth_type=row.get("auth_type") or "oauth",
        created_at=_parse_dt(row.get("created_at")) or datetime.now(timezone.utc),
    )
    db.add(user)
    db.flush()
    id_map[old_id] = user.id


def _merge_user_state(db: Session, row: dict, id_map: dict[int, int]) -> None:
    old_uid = int(row["user_id"])
    if old_uid not in id_map:
        return
    new_uid = id_map[old_uid]
    incoming = row.get("payload") or "{}"
    existing = db.get(UserState, new_uid)
    if not existing:
        db.add(
            UserState(
                user_id=new_uid,
                payload=incoming,
                updated_at=_parse_dt(row.get("updated_at")) or datetime.now(timezone.utc),
            )
        )
        return
    if _state_updated_at(incoming) >= _state_updated_at(existing.payload):
        existing.payload = incoming
        existing.updated_at = _parse_dt(row.get("updated_at")) or datetime.now(timezone.utc)


def _merge_settings(db: Session, rows: list[dict]) -> None:
    for row in rows:
        key = row["key"]
        value = row.get("value") or ""
        existing = db.get(AppSetting, key)
        if key == "team_case_counter":
            try:
                incoming_n = int(value)
            except ValueError:
                incoming_n = 0
            current_n = 0
            if existing:
                try:
                    current_n = int(existing.value)
                except ValueError:
                    current_n = 0
            best = str(max(incoming_n, current_n))
            if existing:
                existing.value = best
            else:
                db.add(AppSetting(key=key, value=best))
            continue
        if existing is None:
            db.add(AppSetting(key=key, value=value))


def _merge_tasks(
    db: Session,
    rows: list[dict],
    id_map: dict[int, int],
    task_id_map: dict[tuple[str, int], int],
    source: str,
) -> None:
    for row in rows:
        case_number = row.get("case_number") or ""
        if not case_number:
            continue
        old_id = int(row["id"])
        reporter_old = int(row["reporter_id"])
        assignee_old = row.get("assignee_id")
        if reporter_old not in id_map:
            print(f"  skip task {case_number}: missing reporter")
            continue
        reporter_id = id_map[reporter_old]
        assignee_id = None
        if assignee_old is not None and int(assignee_old) in id_map:
            assignee_id = id_map[int(assignee_old)]

        existing = db.query(TeamTask).filter(TeamTask.case_number == case_number).one_or_none()
        if existing:
            incoming_updated = _parse_dt(row.get("updated_at"))
            existing_updated = _aware(existing.updated_at)
            if incoming_updated and (
                not existing_updated or incoming_updated >= existing_updated
            ):
                existing.title = row.get("title") or existing.title
                existing.description = row.get("description") or ""
                existing.status = row.get("status") or existing.status
                existing.priority = row.get("priority") or existing.priority
                existing.due_date = row.get("due_date")
                existing.tags = row.get("tags") or ""
                existing.assignee_id = assignee_id
                existing.updated_at = incoming_updated
            task_id_map[(source, old_id)] = existing.id
            continue

        task = TeamTask(
            case_number=case_number,
            title=row.get("title") or "Untitled",
            description=row.get("description") or "",
            status=row.get("status") or "new",
            priority=row.get("priority") or "medium",
            due_date=row.get("due_date"),
            tags=row.get("tags") or "",
            reporter_id=reporter_id,
            assignee_id=assignee_id,
            created_at=_parse_dt(row.get("created_at")) or datetime.now(timezone.utc),
            updated_at=_parse_dt(row.get("updated_at")) or datetime.now(timezone.utc),
        )
        db.add(task)
        db.flush()
        task_id_map[(source, old_id)] = task.id


def _merge_comments(
    db: Session,
    rows: list[dict],
    id_map: dict[int, int],
    task_id_map: dict[tuple[str, int], int],
    source: str,
) -> None:
    for row in rows:
        old_task = int(row["task_id"])
        old_author = int(row["author_id"])
        new_task = task_id_map.get((source, old_task))
        if new_task is None or old_author not in id_map:
            continue
        body = row.get("body") or ""
        author_id = id_map[old_author]
        created = _parse_dt(row.get("created_at"))
        # Dedupe identical comment text from same author on same task
        q = (
            db.query(TaskComment)
            .filter(
                TaskComment.task_id == new_task,
                TaskComment.author_id == author_id,
                TaskComment.body == body,
            )
            .all()
        )
        if q:
            continue
        db.add(
            TaskComment(
                task_id=new_task,
                author_id=author_id,
                body=body,
                created_at=created or datetime.now(timezone.utc),
            )
        )


def _merge_notifications(
    db: Session,
    rows: list[dict],
    id_map: dict[int, int],
    task_id_map: dict[tuple[str, int], int],
    source: str,
) -> None:
    for row in rows:
        old_uid = int(row["user_id"])
        if old_uid not in id_map:
            continue
        task_id = None
        if row.get("task_id") is not None:
            task_id = task_id_map.get((source, int(row["task_id"])))
        title = row.get("title") or ""
        body = row.get("body") or ""
        kind = row.get("kind") or "info"
        user_id = id_map[old_uid]
        exists = (
            db.query(Notification)
            .filter(
                Notification.user_id == user_id,
                Notification.kind == kind,
                Notification.title == title,
                Notification.body == body,
                Notification.task_id == task_id,
            )
            .first()
        )
        if exists:
            continue
        db.add(
            Notification(
                user_id=user_id,
                kind=kind,
                title=title,
                body=body,
                task_id=task_id,
                read=int(row.get("read") or 0),
                created_at=_parse_dt(row.get("created_at")) or datetime.now(timezone.utc),
            )
        )


def apply_dump(db: Session, dump: dict, task_id_map: dict[tuple[str, int], int]) -> None:
    source = dump.get("source") or "backup"
    tables = dump["tables"]
    id_map: dict[int, int] = {}
    print(f"Merging source={source}")
    for row in tables.get("users") or []:
        _upsert_user(db, row, id_map)
    db.flush()
    for row in tables.get("user_state") or []:
        _merge_user_state(db, row, id_map)
    _merge_settings(db, tables.get("app_settings") or [])
    _merge_tasks(db, tables.get("team_tasks") or [], id_map, task_id_map, source)
    db.flush()
    _merge_comments(db, tables.get("task_comments") or [], id_map, task_id_map, source)
    _merge_notifications(db, tables.get("notifications") or [], id_map, task_id_map, source)
    db.commit()
    print(f"  users mapped: {len(id_map)}")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "dumps",
        nargs="+",
        type=Path,
        help="One or more backup JSON files (e.g. local then live)",
    )
    parser.add_argument(
        "--database-url",
        default=os.getenv("DATABASE_URL", ""),
        help="Target DB URL (default: DATABASE_URL env). Use Render External URL for Postgres.",
    )
    args = parser.parse_args()
    if not args.database_url:
        raise SystemExit("Pass --database-url or set DATABASE_URL")

    url = normalize_database_url(args.database_url)
    os.environ["DATABASE_URL"] = url
    # Re-bind engine after env change
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from backend import config as app_config

    app_config.DATABASE_URL = url
    engine = create_engine(
        url,
        connect_args={"check_same_thread": False} if url.startswith("sqlite") else {},
        pool_pre_ping=not url.startswith("sqlite"),
    )
    db_mod.engine = engine
    db_mod.SessionLocal = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    init_db()

    task_id_map: dict[tuple[str, int], int] = {}
    with db_mod.SessionLocal() as db:
        for path in args.dumps:
            apply_dump(db, _load_dump(path), task_id_map)
        users = db.query(User).count()
        tasks = db.query(TeamTask).count()
        print(f"Done. Target has {users} users, {tasks} team tasks.")


if __name__ == "__main__":
    main()
