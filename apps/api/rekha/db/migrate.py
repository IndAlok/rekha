"""Tiny idempotent column migrator. create_all builds fresh schemas. this
adds columns introduced later and lifts bare timestamps to timestamptz."""

from __future__ import annotations

import logging
import re

from sqlalchemy import inspect, text

log = logging.getLogger("rekha.migrate")

_IDENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

BARE_TIMESTAMP_SQL = """
SELECT table_name, column_name
FROM information_schema.columns
WHERE table_schema = current_schema()
  AND data_type = 'timestamp without time zone'
"""

# kind: timestamptz | boolean | integer | varchar
EXTRA_COLUMNS: list[tuple[str, str, str]] = [
    ("scheduled_jobs", "lease_expires_at", "timestamptz"),
    ("contact_reservations", "confirmed", "boolean"),
    ("contact_reservations", "lease_expires_at", "timestamptz"),
    ("recovery_cases", "mandate_attempts_used", "integer"),
    ("recovery_cases", "nach_representations_used", "integer"),
    ("recovery_cases", "first_failed_at", "timestamptz"),
    ("customers", "consent_changed_at", "timestamptz"),
    ("customers", "consent_withdrawn_at", "timestamptz"),
    ("customers", "legal_hold", "boolean"),
    ("recovery_ledger", "obligation_key", "varchar"),
    ("promises_to_pay", "created_at", "timestamptz"),
    ("promises_to_pay", "updated_at", "timestamptz"),
]


def column_sql(dialect: str, kind: str) -> str:
    postgres = dialect == "postgresql"
    if kind == "timestamptz":
        return "TIMESTAMPTZ NULL" if postgres else "TIMESTAMP NULL"
    if kind == "boolean":
        return "BOOLEAN NOT NULL DEFAULT FALSE" if postgres else "BOOLEAN NOT NULL DEFAULT 0"
    if kind == "integer":
        return "INTEGER NOT NULL DEFAULT 0"
    if kind == "varchar":
        return "VARCHAR"
    raise ValueError(f"unknown column kind {kind}")


def _safe_ident(name: str) -> str | None:
    if isinstance(name, str) and _IDENT.match(name):
        return name
    return None


def _needs_timestamptz(col: dict) -> bool:
    typ = col.get("type")
    if typ is None:
        return False
    if getattr(typ, "timezone", None) is True:
        return False
    raw = str(typ).upper()
    if "TIMESTAMPTZ" in raw:
        return False
    if "WITH TIME ZONE" in raw and "WITHOUT" not in raw:
        return False
    return "TIMESTAMP" in raw or "DATETIME" in raw


def _inspect_bare_timestamps(engine) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    try:
        inspector = inspect(engine)
        tables = inspector.get_table_names()
    except Exception:
        log.exception("ensure_timestamptz inspect failed")
        return out
    for table in tables:
        try:
            cols = inspector.get_columns(table)
        except Exception:
            log.exception("ensure_timestamptz columns failed for %s", table)
            continue
        for col in cols:
            if _needs_timestamptz(col):
                out.append((table, col["name"]))
    return out


def _lift_column(conn, table: str, name: str) -> None:
    table = _safe_ident(table)
    name = _safe_ident(name)
    if table is None or name is None:
        return
    conn.execute(
        text(
            f'ALTER TABLE "{table}" ALTER COLUMN "{name}" TYPE TIMESTAMPTZ '
            f'USING "{name}" AT TIME ZONE \'UTC\''
        )
    )


def ensure_timestamptz(engine) -> None:
    """psycopg3 errors if we bind an aware datetime to timestamp without tz.
    Live columns added as TIMESTAMP NULL must be lifted."""
    if engine.dialect.name != "postgresql":
        return
    try:
        with engine.begin() as conn:
            try:
                rows = conn.execute(text(BARE_TIMESTAMP_SQL)).fetchall()
                targets = [(r[0], r[1]) for r in rows]
            except Exception:
                log.exception("ensure_timestamptz catalog failed")
                targets = _inspect_bare_timestamps(engine)
            for table, name in targets:
                try:
                    _lift_column(conn, table, name)
                    log.info("lifted %s.%s to timestamptz", table, name)
                except Exception:
                    log.exception("timestamptz lift failed for %s.%s", table, name)
    except Exception:
        log.exception("ensure_timestamptz failed")


def apply(engine) -> None:
    dialect = engine.dialect.name
    try:
        inspector = inspect(engine)
        existing = {table: {c["name"] for c in inspector.get_columns(table)} for table in inspector.get_table_names()}
    except Exception:  # noqa: BLE001
        return
    with engine.begin() as conn:
        for table, column, kind in EXTRA_COLUMNS:
            cols = existing.get(table)
            if cols is None or column in cols:
                continue
            try:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {column_sql(dialect, kind)}"))
                log.info("migrated %s.%s", table, column)
            except Exception:
                log.exception("migration failed for %s.%s", table, column)
        if "recovery_ledger" in existing:
            try:
                conn.execute(
                    text(
                        "UPDATE recovery_ledger SET obligation_key = "
                        "case_id || ':' || source_event || ':' || CAST(id AS VARCHAR) "
                        "WHERE obligation_key IS NULL OR obligation_key = ''"
                    )
                )
            except Exception:
                log.exception("backfill obligation_key failed")
            try:
                conn.execute(text("CREATE UNIQUE INDEX IF NOT EXISTS uq_ledger_obligation ON recovery_ledger (obligation_key)"))
            except Exception:
                log.exception("unique obligation_key index failed")
    ensure_timestamptz(engine)
