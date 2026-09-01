"""Tiny idempotent column migrator. create_all builds fresh schemas; this
adds columns introduced later to databases that already exist."""

from __future__ import annotations

import logging

from sqlalchemy import inspect, text

log = logging.getLogger("rekha.migrate")

EXTRA_COLUMNS: list[tuple[str, str, str]] = [
    ("scheduled_jobs", "lease_expires_at", "TIMESTAMP NULL"),
    ("contact_reservations", "confirmed", "BOOLEAN NOT NULL DEFAULT 0"),
    ("contact_reservations", "lease_expires_at", "TIMESTAMP NULL"),
    ("recovery_cases", "mandate_attempts_used", "INTEGER NOT NULL DEFAULT 0"),
    ("recovery_cases", "nach_representations_used", "INTEGER NOT NULL DEFAULT 0"),
    ("recovery_cases", "first_failed_at", "TIMESTAMP NULL"),
    ("customers", "consent_changed_at", "TIMESTAMP NULL"),
    ("customers", "consent_withdrawn_at", "TIMESTAMP NULL"),
    ("recovery_ledger", "obligation_key", "VARCHAR"),
    ("promises_to_pay", "created_at", "TIMESTAMP NULL"),
    ("promises_to_pay", "updated_at", "TIMESTAMP NULL"),
]


def apply(engine) -> None:
    try:
        inspector = inspect(engine)
        existing = {table: {c["name"] for c in inspector.get_columns(table)} for table in inspector.get_table_names()}
    except Exception:  # noqa: BLE001
        return
    with engine.begin() as conn:
        for table, column, ddl in EXTRA_COLUMNS:
            cols = existing.get(table)
            if cols is None or column in cols:
                continue
            try:
                conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))
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
