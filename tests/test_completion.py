"""Stage 1-4 completion tests. Each bug in the master plan has a lock here."""

from __future__ import annotations

import threading
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient
from rekha.api import app
from rekha.audit import AuditChain, verify_rows
from rekha.db.session import init_db
from rekha.engine import RecoveryEngine
from rekha.eval.runner import run_eval
from rekha.eval.stats import bca_bootstrap_sum_diff
from rekha.ingest import event_to_case
from rekha.paths import FIXTURES_DIR
from rekha.reservations import Slot
from rekha.sandbox import FileInbox
from rekha.store import (
    CaseStore,
    ComplaintStore,
    JobStore,
    LedgerStore,
    PersistentAuditSink,
    PersistentReservations,
)
from rekha.voice import VoiceSession, _safe_line, run_scripted_session

IST = ZoneInfo("Asia/Kolkata")


def test_prod_mutating_routes_require_ops_token(monkeypatch):
    from rekha.config import settings

    monkeypatch.setattr(settings, "rekha_env", "prod")
    monkeypatch.setattr(settings, "ops_token", "secret")
    with TestClient(app) as client:
        for path, body in (
            ("/cases/run", {"case": {"id": "x", "amount_paise": 100, "consent_status": "GRANTED", "contacts_last_7d": 0, "touches_this_case": 0}}),
            ("/complaints", {"customer_id": "cust-x"}),
            ("/eval/run", None),
            ("/awaaz/session", {"case": {"id": "x", "amount_paise": 100, "last4": "4242"}, "lines": ["haan"]}),
        ):
            res = client.post(path, json=body or {})
            assert res.status_code == 401, path
            assert res.json()["detail"]["code"] == "UNAUTHORIZED"
        ok = client.post("/kill-switch", json={"engaged": False}, headers={"X-Ops-Token": "secret"})
        assert ok.status_code == 200
        sign = client.post("/webhooks/sign", json={"event": "payment.failed"})
        assert sign.status_code == 401


def test_webhook_stays_open_without_ops_token():
    with TestClient(app) as client:
        res = client.post(
            "/webhooks/razorpay",
            headers={"X-Razorpay-Event-Id": "evt-open-1"},
            json={"event": "payment.failed", "payload": {"payment": {"entity": {"id": "pay-o", "status": "failed", "amount": 100}}}},
        )
        assert res.status_code == 200


def test_event_id_fallback_is_sha256():
    with TestClient(app) as client:
        body = {"event": "payment.failed", "payload": {"payment": {"entity": {"id": "pay-hash", "status": "failed", "amount": 1}}}}
        res = client.post("/webhooks/razorpay", json=body)
        assert res.status_code == 200
        event_id = res.json()["event_id"]
        assert len(event_id) == 64
        assert event_id.isalnum()


def test_complaints_persist_and_throttle():
    now = datetime(2026, 8, 22, 11, tzinfo=IST)
    ComplaintStore.record("cust-c", now)
    ComplaintStore.record("cust-c", now + timedelta(hours=1))
    assert ComplaintStore.throttled("cust-c", now + timedelta(hours=2)) is True
    assert ComplaintStore.throttled("cust-other", now + timedelta(hours=2)) is False
    state = ComplaintStore.state("cust-c", now + timedelta(hours=2))
    assert state["count"] == 2
    assert state["throttled"] is True


def test_kill_switch_blocks_approve_before_persist():
    with TestClient(app) as client:
        payload = {
            "case": {
                "id": "case-kill-appr",
                "customer_id": "cust-k",
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
                "contact": "+919800000099",
            }
        }
        res = client.post("/cases/run", json=payload)
        assert res.status_code == 200
        approval_id = res.json()["approval_id"]
        assert approval_id
        client.post("/kill-switch", json={"engaged": True})
        denied = client.post(f"/approvals/{approval_id}/decide", json={"decision": "approve", "approver": "ops"})
        assert denied.status_code == 409
        assert denied.json()["detail"]["code"] == "KILL_SWITCH"
        pending = client.get("/approvals").json()
        assert any(a["id"] == approval_id for a in pending)
        client.post("/kill-switch", json={"engaged": False})


def test_job_lease_reclaim_after_crash():
    init_db()
    case = {
        "id": "case-lease-1",
        "customer_id": "cust-lease",
        "amount_paise": 100,
        "consent_status": "GRANTED",
        "contacts_last_7d": 0,
        "touches_this_case": 0,
    }
    JobStore.schedule("deferred", case, datetime.now(UTC) - timedelta(minutes=1))
    claimed = JobStore.due(datetime.now(UTC))
    assert len(claimed) == 1
    assert claimed[0]["id"]
    # Crash: the job is running with an expired lease.
    from rekha.db.models import ScheduledJob
    from rekha.db.session import session_scope

    with session_scope() as session:
        row = session.get(ScheduledJob, claimed[0]["id"])
        row.lease_expires_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(minutes=10)
    again = JobStore.due(datetime.now(UTC))
    assert len(again) == 1
    assert again[0]["id"] == claimed[0]["id"]


def test_reservation_ttl_allows_retry():
    res = PersistentReservations()
    slot = Slot("cust-ttl", "2026-08-22", "sms")
    assert res.reserve(slot) is True
    assert res.reserve(slot) is False
    from rekha.db.models import ContactReservationRow
    from rekha.db.session import session_scope
    from sqlalchemy import select

    with session_scope() as session:
        row = session.scalars(select(ContactReservationRow).where(ContactReservationRow.customer_id == "cust-ttl")).first()
        row.lease_expires_at = datetime.now(UTC) - timedelta(minutes=10)
        row.confirmed = False
    assert res.reserve(slot) is True


def test_ledger_does_not_double_count_same_obligation():
    ok1 = LedgerStore.record("case-d1", 1000, source_event="payment.authorized", attribution="agent", action="x", channel="email", obligation_key="case-d1:pay-1")
    ok2 = LedgerStore.record("case-d1", 1000, source_event="payment.captured", attribution="agent", action="x", channel="email", obligation_key="case-d1:pay-1")
    assert ok1 is True
    assert ok2 is False
    totals = LedgerStore.total()
    assert totals["agent_paise"] == 1000


def test_open_case_for_refs_is_exact():
    CaseStore.upsert({"id": "case-order-abc", "customer_id": "c", "amount_paise": 1, "loss_class": "payment_failure"})
    CaseStore.stash_payload({"id": "case-order-abc", "source_refs": {"order_id": "order-abc"}, "customer_id": "c", "amount_paise": 1, "loss_class": "payment_failure"})
    assert CaseStore.open_case_for_refs({"order_id": "order-abc"}) == "case-order-abc"
    assert CaseStore.open_case_for_refs({"order_id": "abc"}) is None


def test_contacts_last_7d_is_a_window():
    CaseStore.upsert({"id": "case-win", "customer_id": "cust-win", "amount_paise": 1})
    CaseStore.record_touch("case-win", contacted=True, channel="sms", customer_id="cust-win")
    _, n = CaseStore.counters("case-win")
    assert n == 1
    from rekha.db.models import CaseContact
    from rekha.db.session import session_scope
    from sqlalchemy import select

    with session_scope() as session:
        row = session.scalars(select(CaseContact).where(CaseContact.case_id == "case-win")).first()
        row.contacted_at = datetime.now(UTC) - timedelta(days=8)
    _, n2 = CaseStore.counters("case-win")
    assert n2 == 0


def test_audit_append_is_serialized_and_rehydrates():
    sink = PersistentAuditSink()
    chain = AuditChain(sink=sink)
    errors = []

    def _writer(n: int) -> None:
        try:
            chain.append({"actor": "t", "action": f"a{n}", "payload": {}})
        except Exception as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=_writer, args=(i,)) for i in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    rows = PersistentAuditSink.rows()
    ok, msg = verify_rows(rows)
    assert ok, msg
    last = PersistentAuditSink.last_row()
    restarted = AuditChain(sink=PersistentAuditSink())
    restarted.resume(last["seq"], last["entry_hash"], rows=rows)
    assert any(r.get("action") == "a0" for r in restarted.rows)
    nxt = restarted.append({"actor": "t", "action": "after", "payload": {}})
    assert nxt["seq"] == last["seq"] + 1


def test_notes_case_id_wins_on_link_paid():
    case = event_to_case(
        {
            "event_type": "payment_link.paid",
            "payload": {
                "payment_link": {
                    "entity": {
                        "id": "plink_x",
                        "entity": "payment_link",
                        "amount": 5000,
                        "status": "paid",
                        "notes": {"case_id": "case-origin-1"},
                    }
                }
            },
        }
    )
    assert case["id"] == "case-origin-1"
    assert case["loss_class"] == "recovery_event"


def test_recon_unknown_fetch_fail_closed():
    class Boom:
        def fetch_payment(self, _id):
            raise RuntimeError("timeout")

    result = RecoveryEngine(payments=Boom(), comms=FileInbox(), persist=False).recon.check(
        {"source_refs": {"payment_id": "pay-x"}, "already_paid": False}
    )
    assert result.unknown is True
    engine = RecoveryEngine(payments=Boom(), comms=FileInbox(), persist=False)
    out = engine.run_case(
        {
            "id": "case-unknown",
            "customer_id": "c",
            "amount_paise": 100,
            "consent_status": "GRANTED",
            "contacts_last_7d": 0,
            "touches_this_case": 0,
            "source_refs": {"payment_id": "pay-x"},
            "error_reason": "insufficient_funds",
            "error_source": "customer",
        },
        datetime(2026, 8, 22, 11, 30, tzinfo=IST),
    )
    assert out.blocked is True
    assert out.recovered is False
    assert out.verdict["reason_code"] == "RECON_FETCH_UNKNOWN"


def test_voice_missing_last4_fail_closed():
    session = run_scripted_session({"id": "c1", "merchant_name": "NoonCart", "first_name": "Riya", "amount_paise": 100000}, ["haan 42"])
    assert session.stopped
    assert session.stop_reason == "VERIFY_FAILED"
    assert session.verified is False


def test_awaaz_missing_amount_is_400():
    with TestClient(app) as client:
        res = client.post("/awaaz/session", json={"case": {"id": "c-amt", "last4": "4242"}, "lines": ["haan"]})
        assert res.status_code == 400
        assert res.json()["detail"]["code"] == "BAD_REQUEST"


def test_run_eval_write_does_not_change_golden():
    path = FIXTURES_DIR / "golden.json"
    original = path.read_text(encoding="utf-8")
    run_eval(seed=42, write=True, write_golden=False)
    assert path.read_text(encoding="utf-8") == original


def test_bca_two_sample_unequal_arms():
    treat = [100, 0, 100]
    hold = [0, 0, 0, 50, 0]
    obs, lo, hi = bca_bootstrap_sum_diff(treat, hold)
    assert obs == 150
    assert lo <= obs <= hi
    again = bca_bootstrap_sum_diff(treat, hold)
    assert again == (obs, lo, hi)


def test_quiet_hours_with_injected_clock(monkeypatch):
    frozen = datetime(2026, 8, 22, 22, 15, tzinfo=IST)
    monkeypatch.setattr("rekha.api.wall_now", lambda: frozen)
    with TestClient(app) as client:
        res = client.post(
            "/webhooks/razorpay?wait=true",
            headers={"X-Razorpay-Event-Id": "evt-quiet-clock"},
            json={
                "event": "cart.abandoned",
                "payload": {
                    "customer": {"id": "cust-qc", "consent": True, "contact": "+919800000002"},
                    "payment": {
                        "entity": {
                            "id": "pay-qc",
                            "entity": "payment",
                            "status": "failed",
                            "amount": 49900,
                            "order_id": "order-qc",
                            "error_reason": "payment_cancelled",
                        }
                    },
                },
            },
        )
        assert res.status_code == 200
        body = res.json()["result"]
        assert body["verdict"]["effect"] == "DEFER"
        jobs = JobStore.upcoming()
        assert any(j["case_id"] == body["case_id"] for j in jobs)


def test_policy_and_jobs_endpoints():
    with TestClient(app) as client:
        pol = client.get("/policy")
        assert pol.status_code == 200
        assert pol.json()["version"]
        assert pol.json()["rules"]
        jobs = client.get("/jobs")
        assert jobs.status_code == 200
        assert "jobs" in jobs.json()


def test_safe_line_vetoes_on_scan_fail():
    session = VoiceSession(case_id="c-veto")
    spoken = _safe_line(session, "We will file a section 138 case if you do not pay")
    assert spoken == "[blocked]"
    assert session.stopped is True
    assert session.stop_reason == "COMPLIANCE_VETO"
    assert session.compliance_flags


def test_at_risk_excludes_already_paid():
    payload = run_eval(seed=42, write=False)
    from rekha.eval.cohort import generate_cohort

    cases = generate_cohort(42)
    expected = sum(c["amount_paise"] for c in cases if not c.get("duplicate_of") and not c.get("already_paid"))
    assert payload["report"]["at_risk_paise"] == expected
