#!/usr/bin/env python3
"""Expand/contract check for Alembic migrations (CI: migrations:lint, check-task.sh).

A failed deploy rolls back to the previous release's pods, not its schema, so a migration
must leave the database usable by the previous release's code (docs/operator-guide.md,
"Rollback, and migrations"): add first, drop or rename in a later release. This flags the
operations in a migration's upgrade() that the previous code may still depend on:

  drop_table, drop_column, rename_table, alter_column(new_column_name=... | type_=... |
  nullable=False), and op.execute() SQL with DROP TABLE/COLUMN/VIEW/TYPE/FUNCTION, RENAME,
  ALTER COLUMN ... TYPE or SET NOT NULL.

A migration that does one on purpose (the contract step, once no released code uses it)
says why in a comment anywhere in the file:

  # contract-ok: 0.3.0 stopped reading users.legacy_flag; 0.4.0 drops it

Migrations up to CHECKED_AFTER shipped before this check and are not read. Standard
library only.

  python3 scripts/lib/check-migrations.py [versions-dir] [--after 0015]
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

CHECKED_AFTER = "0015"
REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DIR = REPO_ROOT / "backend" / "app" / "migrations" / "versions"
MARKER = re.compile(r"#\s*contract-ok:\s*\S")
REVISION = re.compile(r"""^revision(?:\s*:\s*[^=]+)?\s*=\s*["']([^"']+)["']""", re.MULTILINE)
DESTRUCTIVE_CALLS = {"drop_table", "drop_column", "rename_table"}
DESTRUCTIVE_SQL = re.compile(
    r"\b(DROP\s+(TABLE|COLUMN|VIEW|TYPE|FUNCTION|SCHEMA)|RENAME\s+(TO|COLUMN)"
    r"|ALTER\s+COLUMN\s+\S+\s+(SET\s+DATA\s+)?TYPE|SET\s+NOT\s+NULL)\b",
    re.IGNORECASE,
)


def strings(node: ast.AST) -> str:
    """The literal text in an expression (str constants, f-string parts, concatenations)."""
    return " ".join(
        sub.value for sub in ast.walk(node) if isinstance(sub, ast.Constant) and isinstance(sub.value, str)
    )


def findings(source: str) -> list[tuple[int, str]]:
    tree = ast.parse(source)
    found: list[tuple[int, str]] = []
    for function in tree.body:
        if not (isinstance(function, ast.FunctionDef) and function.name == "upgrade"):
            continue
        for call in ast.walk(function):
            if not (isinstance(call, ast.Call) and isinstance(call.func, ast.Attribute)):
                continue
            name = call.func.attr
            keywords = {k.arg: k.value for k in call.keywords if k.arg}
            if name in DESTRUCTIVE_CALLS:
                found.append((call.lineno, f"{name}()"))
            elif name == "alter_column":
                if "new_column_name" in keywords:
                    found.append((call.lineno, "alter_column(new_column_name=...): a rename"))
                if "type_" in keywords:
                    found.append((call.lineno, "alter_column(type_=...): a new type"))
                nullable = keywords.get("nullable")
                if isinstance(nullable, ast.Constant) and nullable.value is False:
                    found.append((call.lineno, "alter_column(nullable=False): old code may insert NULL"))
            elif name == "execute" and call.args:
                match = DESTRUCTIVE_SQL.search(strings(call.args[0]))
                if match:
                    found.append((call.lineno, f"execute() with {' '.join(match.group(0).upper().split())}"))
    return sorted(found)


def main(argv: list[str]) -> int:
    after = CHECKED_AFTER
    directory = DEFAULT_DIR
    args = list(argv)
    while args:
        arg = args.pop(0)
        if arg == "--after" and args:
            after = args.pop(0)
        else:
            directory = Path(arg)
    files = sorted(directory.glob("*.py"))
    if not files:
        print(f"check-migrations: no migrations in {directory}", file=sys.stderr)
        return 1
    failed = checked = 0
    for path in files:
        source = path.read_text(encoding="utf-8")
        revision = REVISION.search(source)
        if not revision or revision.group(1) <= after:
            continue
        checked += 1
        problems = findings(source)
        if problems and not MARKER.search(source):
            failed += 1
            try:
                shown = path.resolve().relative_to(REPO_ROOT)
            except ValueError:
                shown = path
            for line, what in problems:
                print(f"{shown}:{line}: upgrade() {what}", file=sys.stderr)
    if failed:
        print(
            f"check-migrations: {failed} migration(s) may break the previous release's code, which a "
            "failed deploy rolls back to. Split it (expand now, contract in a later release), or add "
            '"# contract-ok: <why no released code needs it>" to the file.',
            file=sys.stderr,
        )
        return 1
    print(f"check-migrations: {checked} migration(s) after {after} checked, none breaks the previous release")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
