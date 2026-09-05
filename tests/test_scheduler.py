"""Scheduler + approvals: DEFER becomes a durable dispatch, approvals have a
completion path, and time-shifted proposals fire at the right moment."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient
from rekha.api import app
from rekha.db.session import init_db
from rekha.scheduler import Scheduler
from rekha.store import ApprovalStore, JobStore

IST = ZoneInfo("Asia/Kolkata")


def _client():
    init_db()
    return TestClient(app)


def test_quiet_hours_defers_into_scheduled_job(monkeypatch):
    frozen = datetime(2026, 8, 22, 22, 15, tzinfo=IST)
    monkeypatch.setattr("rekha.api.wall_now", lambda: frozen)
    with _client() as client:
        res = client.post(
            "/webhooks/razorpay?wait=true",
            headers={"X-Razorpay-Event-Id": "evt-quiet-1"},
            json={
                "event": "cart.abandoned",
                "payload": {
                    "customer": {"id": "cust-q", "consent": True, "contact": "+919800000002"},
                    "payment": {"entity": {"id": "pay-q1", "entity": "payment", "status": "failed", "amount": 49900, "order_id": "order-q1", "error_reason": "payment_cancelled"}},
                },
            },
        )
        assert res.status_code == 200
        body = res.json()["result"]
        assert body["verdict"]["effect"] == "DEFER"
        jobs = JobStore.upcoming()
        assert jobs and all(j["status"] == "pending" for j in jobs)


def test_scheduler_fires_due_job():
    init_db()
    case = {
        "id": "case-sched-1",
        "customer_id": "cust-s",
        "merchant_name": "NoonCart",
        "loss_class": "payment_failure",
        "amount_paise": 129900,
        "error_reason": "insufficient_funds",
        "error_source": "customer",
        "consent_status": "GRANTED",
        "contacts_last_7d": 0,
        "touches_this_case": 0,
        "hours_since_failure": 40,
    }
    JobStore.schedule("deferred", case, datetime.now(UTC) - timedelta(minutes=1))
    from rekha.api import _live_engine

    out = Scheduler(_live_engine).tick()
    assert out["fired"] >= 1
    assert JobStore.due(datetime.now(UTC)) == []
    from rekha.store import CaseStore

    touches, _ = CaseStore.counters("case-sched-1")
    assert touches >= 1


def test_schedule_keeps_ist_instant():
    from rekha.db.models import ScheduledJob
    from rekha.db.session import get_session
    from rekha.store import _as_utc, _aware

    init_db()
    when = datetime(2026, 9, 10, 14, 0, tzinfo=IST)
    job_id = JobStore.schedule("send_after", {"id": "c-tz-1"}, when)
    assert _as_utc(when) == datetime(2026, 9, 10, 8, 30, tzinfo=UTC)
    with get_session() as session:
        row = session.get(ScheduledJob, job_id)
    stored = _aware(row.run_at)
    assert stored is not None
    assert stored.astimezone(UTC) == when.astimezone(UTC)
    listed = JobStore.get(job_id)
    assert listed is not None
    parsed = datetime.fromisoformat(listed["run_at"])
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    assert parsed.astimezone(UTC) == when.astimezone(UTC)


def test_approval_flow_end_to_end():
    with _client() as client:
        # High-value voice case -> REQUIRE_APPROVAL -> approval row.
        payload = {
            "case": {
                "id": "case-appr-1",
                "customer_id": "cust-appr",
                "merchant_name": "NoonCart",
                "first_name": "Riya",
                "last4": "4242",
                "prefer_voice": True,
                "voice_consent": True,
                "voice_lines": ["haan 42", "kal"],
                "amount_paise": 5_000_100,
                "loss_class": "payment_failure",
                "error_reason": "insufficient_funds",
                "error_source": "customer",
                "consent_status": "GRANTED",
                "contacts_last_7d": 0,
                "touches_this_case": 0,
                "hours_since_failure": 40,
                "contact": "+919800000003",
            }
        }
        res = client.post("/cases/run", json=payload)
        assert res.status_code == 200
        assert res.json()["verdict"]["effect"] == "REQUIRE_APPROVAL"
        approval_id = res.json()["approval_id"]
        assert approval_id, "live runs must persist an approval"

        pending = client.get("/approvals").json()
        assert any(a["id"] == approval_id for a in pending)

        decision = client.post(
            f"/approvals/{approval_id}/decide",
            json={"decision": "approve", "approver": "finance_ops@test"},
        )
        assert decision.status_code == 200
        assert decision.json()["status"] == "approved"
        assert decision.json()["execution"]["ok"] is True

        # Deciding again is a 409.
        again = client.post(f"/approvals/{approval_id}/decide", json={"decision": "reject", "approver": "x"})
        assert again.status_code == 409


def test_approval_timeout_auto_denies():
    init_db()

    approval_id = ApprovalStore.create(
        {"id": "case-t-o", "customer_id": "c", "amount_paise": 100, "contacts_last_7d": 0, "touches_this_case": 0, "consent_status": "GRANTED"},
        {"action": "send_template_message", "channel": "voice"},
        {"effect": "REQUIRE_APPROVAL"},
        "finance_ops",
    )
    # Force the expiry into the past.
    from datetime import timedelta

    from rekha.db.models import Approval as ApprovalModel
    from rekha.db.session import get_session

    with get_session() as session:
        row = session.get(ApprovalModel, approval_id)
        row.expires_at = datetime.now(UTC) - timedelta(days=1)
        session.commit()

    expired = ApprovalStore.expire_due()
    assert approval_id in expired
    assert ApprovalStore.get(approval_id)["status"] == "timed_out"
