#!/usr/bin/env python3
"""Fail when a service writes a database table it does not own.

The ownership map lives in infra/postgres/table-ownership.toml. This check keeps the service
boundaries in docs/ARCHITECTURE.md true in the code:

- every table created by a migration must have an entry in the map, and
- each service's application code may only INSERT, UPDATE, or DELETE tables that list it
  as a writer.

Tests are not scanned: fixtures legitimately write any table.
"""

from __future__ import annotations

import re
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OWNERSHIP_FILE = ROOT / "infra/postgres/table-ownership.toml"
MIGRATIONS_DIR = ROOT / "infra/postgres/migrations"
SERVICE_SOURCES = {
    "api": [ROOT / "services/api/app"],
    "trading-engine": [ROOT / "services/trading-engine/src"],
    "worker": [ROOT / "services/worker/app", ROOT / "services/worker/scripts"],
}
SOURCE_SUFFIXES = {".py", ".rs"}

CREATE_TABLE = re.compile(r"\bcreate\s+table\s+(?:if\s+not\s+exists\s+)?(\w+)", re.IGNORECASE)
RENAME_TABLE = re.compile(r"\balter\s+table\s+(\w+)\s+rename\s+to\s+(\w+)", re.IGNORECASE)
DROP_TABLE = re.compile(r"\bdrop\s+table\s+(?:if\s+exists\s+)?(\w+)", re.IGNORECASE)
WRITE = re.compile(r"\b(insert\s+into|update|delete\s+from)\s+(\w+)", re.IGNORECASE)


def migrated_tables() -> set[str]:
    tables: set[str] = set()
    for migration in sorted(MIGRATIONS_DIR.glob("*.sql")):
        sql = migration.read_text()
        events = [(m.start(), "create", m.group(1).lower(), "") for m in CREATE_TABLE.finditer(sql)]
        events += [
            (m.start(), "rename", m.group(1).lower(), m.group(2).lower())
            for m in RENAME_TABLE.finditer(sql)
        ]
        events += [(m.start(), "drop", m.group(1).lower(), "") for m in DROP_TABLE.finditer(sql)]
        for _, kind, name, new_name in sorted(events):
            if kind == "create":
                tables.add(name)
            elif kind == "rename" and name in tables:
                tables.discard(name)
                tables.add(new_name)
            elif kind == "drop":
                tables.discard(name)
    return tables


def service_writes(service: str, known_tables: set[str]) -> dict[str, list[str]]:
    """Map each known table the service writes to the places that write it."""
    writes: dict[str, list[str]] = {}
    for source_root in SERVICE_SOURCES[service]:
        for path in sorted(source_root.rglob("*")):
            if path.suffix not in SOURCE_SUFFIXES or "__pycache__" in path.parts:
                continue
            text = path.read_text()
            for match in WRITE.finditer(text):
                table = match.group(2).lower()
                if table not in known_tables:
                    continue  # e.g. "DO UPDATE SET", "FOR UPDATE", or prose in comments
                line = text.count("\n", 0, match.start()) + 1
                writes.setdefault(table, []).append(f"{path.relative_to(ROOT)}:{line}")
    return writes


def main() -> int:
    ownership = tomllib.loads(OWNERSHIP_FILE.read_text())["tables"]
    tables = migrated_tables()
    problems: list[str] = []

    for table in sorted(tables - ownership.keys()):
        problems.append(f"{table}: created by a migration but missing from {OWNERSHIP_FILE.name}")
    for table in sorted(ownership.keys() - tables):
        problems.append(f"{table}: listed in {OWNERSHIP_FILE.name} but no migration creates it")
    for table, entry in sorted(ownership.items()):
        unknown = set(entry["writers"]) - SERVICE_SOURCES.keys()
        if entry["owner"] not in entry["writers"] or unknown:
            problems.append(f"{table}: owner must be a writer and writers must be known services")

    for service in SERVICE_SOURCES:
        for table, locations in sorted(service_writes(service, tables).items()):
            allowed = ownership.get(table, {}).get("writers", [])
            if service not in allowed:
                owner = ownership.get(table, {}).get("owner", "nobody")
                where = ", ".join(locations)
                problems.append(
                    f"{service} writes {table}, which is owned by {owner} ({where})"
                )

    if problems:
        print("Table ownership check failed:", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        print(
            "Route the write through the owning service, or update "
            f"{OWNERSHIP_FILE.relative_to(ROOT)} with a documented exception.",
            file=sys.stderr,
        )
        return 1

    print(f"Table ownership check passed ({len(tables)} tables).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
