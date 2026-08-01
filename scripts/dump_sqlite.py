#!/usr/bin/env python3
"""Dump a Copado Support SQLite DB to a portable JSON backup."""

from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

TABLES = (
    "users",
    "user_state",
    "app_settings",
    "team_tasks",
    "task_comments",
    "notifications",
)


def dump_sqlite(db_path: Path, source: str) -> dict:
    con = sqlite3.connect(db_path)
    con.row_factory = sqlite3.Row
    try:
        existing = {
            r[0]
            for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        tables: dict[str, list] = {}
        for name in TABLES:
            if name not in existing:
                tables[name] = []
                continue
            tables[name] = [dict(row) for row in con.execute(f'SELECT * FROM "{name}"')]
    finally:
        con.close()
    return {
        "format": "copado_support_backup_v1",
        "source": source,
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "tables": tables,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("db", type=Path, help="Path to app.db / .sqlite file")
    parser.add_argument("-o", "--output", type=Path, required=True, help="Output JSON path")
    parser.add_argument("--source", default="sqlite", help="Label: local, live, …")
    args = parser.parse_args()
    if not args.db.exists():
        raise SystemExit(f"Database not found: {args.db}")
    payload = dump_sqlite(args.db, args.source)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2, default=str))
    counts = {k: len(v) for k, v in payload["tables"].items()}
    print(f"Wrote {args.output} from {args.db}")
    print("Rows:", counts)


if __name__ == "__main__":
    main()
