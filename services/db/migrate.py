"""Simple SQL migration runner with version tracking."""

from __future__ import annotations

import argparse
import asyncio
import os
import re
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from services.db.session import normalize_database_url

MIGRATIONS_DIR = Path(__file__).parent / "migrations"
_STATEMENT_SPLIT = re.compile(r";\s*\n")


async def _ensure_migrations_table(conn) -> None:
    await conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS schema_migrations (
                version TEXT PRIMARY KEY,
                applied_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )
    )


async def _applied_versions(conn) -> set[str]:
    result = await conn.execute(text("SELECT version FROM schema_migrations"))
    return {row[0] for row in result.fetchall()}


def _split_sql(sql: str) -> list[str]:
    statements: list[str] = []
    for chunk in _STATEMENT_SPLIT.split(sql):
        statement = chunk.strip()
        if statement:
            statements.append(statement)
    return statements


async def run_migrations(
    database_url: str | None = None,
    *,
    engine: AsyncEngine | None = None,
) -> list[str]:
    """Apply pending SQL migrations. Returns newly applied version ids."""
    url = normalize_database_url(database_url or os.environ.get("DATABASE_URL", ""))
    own_engine = engine is None
    if own_engine:
        engine = create_async_engine(url)

    assert engine is not None
    applied_new: list[str] = []

    async with engine.begin() as conn:
        await _ensure_migrations_table(conn)
        applied = await _applied_versions(conn)

        for path in sorted(MIGRATIONS_DIR.glob("*.sql")):
            version = path.stem
            if version in applied:
                continue

            sql = path.read_text(encoding="utf-8")
            for statement in _split_sql(sql):
                await conn.execute(text(statement))

            await conn.execute(
                text("INSERT INTO schema_migrations (version) VALUES (:version)"),
                {"version": version},
            )
            applied_new.append(version)

    if own_engine:
        await engine.dispose()

    return applied_new


def main() -> None:
    parser = argparse.ArgumentParser(description="Apply FM21 database migrations")
    parser.parse_args()
    applied = asyncio.run(run_migrations())
    if applied:
        print(f"Applied migrations: {', '.join(applied)}")
    else:
        print("No pending migrations")


if __name__ == "__main__":
    main()
