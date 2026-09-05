from datetime import UTC, date, datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from rekha.db.migrate import (
    BARE_TIMESTAMP_SQL,
    _inspect_bare_timestamps,
    _needs_timestamptz,
    _safe_ident,
    column_sql,
    ensure_timestamptz,
)
from rekha.db.models import Base, RuntimeKV, ScheduledJob
from rekha.db.session import get_engine, session_scope
from rekha.db.time import as_utc, coerce_utc, maybe_utc
from rekha.db.types import TzDateTime
from rekha.store import CaseStore, ComplaintStore, ConsentStore, JobStore, db_json
from sqlalchemy import DateTime

IST = ZoneInfo("Asia/Kolkata")


def test_as_utc_naive_and_ist():
    naive = datetime(2026, 9, 10, 14, 0, 0)  # noqa: DTZ001
    assert as_utc(naive) == datetime(2026, 9, 10, 14, 0, tzinfo=UTC)
    ist = datetime(2026, 9, 10, 14, 0, tzinfo=IST)
    assert as_utc(ist) == datetime(2026, 9, 10, 8, 30, tzinfo=UTC)
    assert maybe_utc(None) is None


def test_coerce_utc_accepts_iso_and_date():
    assert coerce_utc(None) is None
    assert coerce_utc("2026-09-01T12:00:00Z") == datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
    assert coerce_utc("2026-09-01T14:00:00+05:30") == datetime(2026, 9, 1, 8, 30, tzinfo=UTC)
    assert coerce_utc(date(2026, 9, 1)) == datetime(2026, 9, 1, tzinfo=UTC)


def test_tz_datetime_bind_and_result():
    col = TzDateTime()
    bound = col.process_bind_param(datetime(2026, 1, 2, 3, 4, 5), None)  # noqa: DTZ001
    assert bound.tzinfo is not None
    assert bound == datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
    back = col.process_result_value(datetime(2026, 1, 2, 3, 4, 5), None)  # noqa: DTZ001
    assert back == datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)
    assert col.process_bind_param(None, None) is None
    assert col.process_bind_param("2026-01-02T03:04:05Z", None) == datetime(2026, 1, 2, 3, 4, 5, tzinfo=UTC)


def test_every_datetime_column_is_tz():
    found = 0
    for table in Base.metadata.tables.values():
        for col in table.columns:
            if isinstance(col.type, TzDateTime):
                found += 1
                assert col.type.impl.timezone is True
                continue
            assert not isinstance(col.type, DateTime), f"{table.name}.{col.name} is bare DateTime"
    assert found >= 20


def test_column_sql_matches_dialect():
    assert "TIMESTAMPTZ" in column_sql("postgresql", "timestamptz")
    assert column_sql("sqlite", "timestamptz") == "TIMESTAMP NULL"
    assert "FALSE" in column_sql("postgresql", "boolean")
    assert column_sql("sqlite", "boolean").endswith("0")
    assert column_sql("postgresql", "integer") == "INTEGER NOT NULL DEFAULT 0"
    assert column_sql("postgresql", "varchar") == "VARCHAR"
    try:
        column_sql("postgresql", "blob")
    except ValueError:
        pass
    else:
        raise AssertionError("unknown kind should fail")


def test_needs_timestamptz_detects_bare_timestamp():
    assert _needs_timestamptz({"type": SimpleNamespace(timezone=False)}) is False

    class Stamp:
        timezone = False

        def __str__(self):
            return "TIMESTAMP WITHOUT TIME ZONE"

    assert _needs_timestamptz({"type": Stamp()}) is True

    class Tz:
        timezone = True

        def __str__(self):
            return "TIMESTAMP WITH TIME ZONE"

    assert _needs_timestamptz({"type": Tz()}) is False
    assert "timestamp without time zone" in BARE_TIMESTAMP_SQL
    assert _safe_ident("first_failed_at") == "first_failed_at"
    assert _safe_ident('jobs"; drop') is None


def test_ensure_timestamptz_skips_sqlite():
    ensure_timestamptz(get_engine())


def test_db_json_strips_null_bytes():
    assert "\x00" not in db_json({"reason": "ok\x00bad"})


def test_complaint_and_job_accept_naive():
    naive = datetime(2026, 9, 1, 12, 0, 0)  # noqa: DTZ001
    ComplaintStore.record("cust-naive-dt", naive, source="case")
    assert ComplaintStore.throttled("cust-naive-dt", naive) is False
    state = ComplaintStore.state("cust-naive-dt", naive)
    assert state["count"] == 1
    job_id = JobStore.schedule("send_after", {"id": "c-naive-dt"}, naive)
    row = JobStore.get(job_id)
    assert row is not None
    parsed = datetime.fromisoformat(row["run_at"])
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    assert parsed.astimezone(UTC) == datetime(2026, 9, 1, 12, 0, tzinfo=UTC)


def test_case_hours_and_consent_accept_naive():
    naive = datetime(2026, 9, 1, 12, 0, 0)  # noqa: DTZ001
    CaseStore.upsert({"id": "c-naive-hours", "customer_id": "cust-naive-hours", "hours_since_failure": 2})
    hours = CaseStore.hours_since_failure("c-naive-hours", naive)
    assert hours is not None
    ConsentStore.upsert("cust-naive-hours", status="REVOKED")
    view = ConsentStore.get("cust-naive-hours", naive)
    assert view is not None
    assert "silent" in view


def test_coerce_utc_empty_and_junk():
    assert coerce_utc("") is None
    assert coerce_utc("   ") is None
    try:
        coerce_utc(12)
    except TypeError:
        pass
    else:
        raise AssertionError("non-datetime should fail")


def test_inspect_bare_timestamps_on_sqlite():
    rows = _inspect_bare_timestamps(get_engine())
    assert isinstance(rows, list)


def test_flush_coerces_iso_and_strips_nuls():
    with session_scope() as session:
        job = ScheduledJob(kind="deferred", case_id="c-iso-dt", run_at="2026-09-01T12:00:00Z", case_json="{}")
        session.add(job)
        session.add(RuntimeKV(key="k-nul-dt", value_json="ok\x00bad"))
        session.flush()
        assert job.run_at == datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
        row = session.get(RuntimeKV, "k-nul-dt")
        assert row is not None
        assert "\x00" not in row.value_json
