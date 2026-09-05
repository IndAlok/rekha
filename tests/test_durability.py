"""Durability spine: dedupe, idempotency states, reservations, audit sink,
charge guard, kill-switch persistence. all survive a 'restart'."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from rekha import store as store_mod
from rekha.reservations import Slot
from rekha.store import (
    CaseStore,
    ChargeGuardStore,
    PersistentAuditSink,
    PersistentIdempotency,
    PersistentInbox,
    PersistentReservations,
    RuntimeKVStore,
)


def test_inbox_dedupe_survives_restart():
    inbox1 = PersistentInbox()
    _, first = inbox1.accept("evt-1", "payment.failed", {"x": 1})
    assert first is True
    # Simulated restart: a brand-new instance over the same database.
    inbox2 = PersistentInbox()
    _, first2 = inbox2.accept("evt-1", "payment.failed", {"x": 1})
    assert first2 is False


def test_inbox_mark_processed_and_pending():
    inbox = PersistentInbox()
    inbox.accept("evt-2", "payment.failed", {"x": 1})
    assert len(inbox.pending()) == 1
    inbox.mark_processed("evt-2", {"ok": True})
    assert inbox.pending() == []
    inbox.accept("evt-3", "payment.failed", {})
    inbox.mark_processed("evt-3", None, error="boom")
    assert inbox.pending() == []  # errored rows are marked, not stuck pending


def test_idempotency_states():
    idem = PersistentIdempotency()
    calls = []

    def factory():
        calls.append(1)
        return {"ok": True, "n": len(calls)}

    first, is_first = idem.claim("k1", factory)
    assert is_first and first["ok"]
    replay, is_first2 = idem.claim("k1", factory)
    assert not is_first2 and replay["ok"] and len(calls) == 1


def test_idempotency_timeout_leaves_inflight_then_retries():
    idem = PersistentIdempotency()

    def boom():
        raise RuntimeError("network timeout")

    try:
        idem.claim("k2", boom)
    except RuntimeError:
        pass
    calls = []
    result, first = idem.claim("k2", lambda: (calls.append(1), {"ok": True})[1])
    assert first is True
    assert result["ok"]


def test_reservations_release_and_reoccupy():
    res = PersistentReservations()
    slot = Slot("cust-1", "2026-08-22", "sms")
    assert res.reserve(slot) is True
    assert res.reserve(slot) is False
    res.release(slot)
    assert res.reserve(slot) is True


def test_audit_sink_persists_rows():
    from rekha.audit import AuditChain, verify_rows

    chain = AuditChain(sink=PersistentAuditSink())
    chain.append({"actor": "t", "action": "a", "payload": {}})
    chain.append({"actor": "t", "action": "b", "payload": {}})
    rows = PersistentAuditSink.rows()
    assert len(rows) >= 2
    ok, msg = verify_rows(rows)
    assert ok, msg


def test_charge_guard_blocks_double_capture():
    assert ChargeGuardStore.try_capture("case-1", 1, 1000) is True
    assert ChargeGuardStore.try_capture("case-1", 1, 1000) is False  # same attempt twice
    assert ChargeGuardStore.try_capture("case-1", 2, 1000) is True  # next attempt ok


def test_kill_switch_and_counters_persist():
    RuntimeKVStore.set("kill_switch", True)
    assert RuntimeKVStore.get("kill_switch") is True
    RuntimeKVStore.set("kill_switch", False)
    assert RuntimeKVStore.get("kill_switch") is False

    CaseStore.upsert({"id": "case-k", "customer_id": "cust", "amount_paise": 100})
    assert CaseStore.record_touch("case-k") == 1
    assert CaseStore.record_touch("case-k") == 2
    assert CaseStore.counters("case-k") == (2, 0)
    assert CaseStore.record_touch("case-k", contacted=True) == 3
    assert CaseStore.counters("case-k") == (3, 1)


def test_case_close_and_live_listing():
    CaseStore.upsert({"id": "case-live-1", "customer_id": "cust", "loss_class": "payment_failure", "amount_paise": 500})
    CaseStore.close("case-live-1", recovered=True, source="agent")
    rows = CaseStore.live_cases()
    match = [r for r in rows if r["case_id"] == "case-live-1"]
    assert match and match[0]["recovered"] is True and match[0]["status"] == "recovered"


def test_upsert_refreshes_live_order(monkeypatch):
    clock = {"n": datetime(2026, 9, 5, 10, 0, tzinfo=UTC)}

    def fake_now():
        clock["n"] = clock["n"] + timedelta(seconds=1)
        return clock["n"]

    monkeypatch.setattr(store_mod, "_now", fake_now)
    CaseStore.upsert({"id": "case-live-old", "customer_id": "cust", "amount_paise": 100})
    CaseStore.upsert({"id": "case-live-new", "customer_id": "cust", "amount_paise": 200})
    CaseStore.upsert({"id": "case-live-old", "customer_id": "cust", "amount_paise": 100})
    ids = [r["case_id"] for r in CaseStore.live_cases()]
    assert ids.index("case-live-old") < ids.index("case-live-new")


def test_ledger_records_and_totals():
    from rekha.store import LedgerStore

    LedgerStore.record("case-l1", 100000, source_event="payment.captured", attribution="agent", action="create_payment_link", channel="whatsapp")
    LedgerStore.record("case-l2", 50000, source_event="recon", attribution="self_cure", action=None, channel=None)
    totals = LedgerStore.total()
    assert totals["agent_paise"] == 100000
    assert totals["self_cure_paise"] == 50000
    assert totals["entries"] >= 2


def test_audit_chain_resumes_after_restart():
    from rekha.audit import AuditChain, verify_rows
    from rekha.store import PersistentAuditSink

    process1 = AuditChain(sink=PersistentAuditSink())
    process1.append({"actor": "t", "action": "first", "payload": {}})

    # Simulated restart: a fresh chain must continue, not collide on seq.
    process2 = AuditChain(sink=PersistentAuditSink())
    last = PersistentAuditSink.last_row()
    assert last is not None and last["seq"] == 1
    process2.resume(last["seq"], last["entry_hash"])
    row = process2.append({"actor": "t", "action": "second", "payload": {}})
    assert row["seq"] == 2
    assert row["prev_hash"] == last["entry_hash"]
    ok, msg = verify_rows(PersistentAuditSink.rows())
    assert ok, msg


def test_kill_switch_and_audit_survive_api_restart():
    from fastapi.testclient import TestClient
    from rekha.api import app

    with TestClient(app) as client:
        on = client.post("/kill-switch", json={"engaged": True})
        assert on.status_code == 200
        # an audited action while engaged
        blocked = client.post(
            "/webhooks/razorpay?wait=true",
            headers={"X-Razorpay-Event-Id": "evt-restart-blocked"},
            json={"event": "payment.failed", "payload": {"payment": {"entity": {"id": "pay-x", "status": "failed", "amount": 1000}}}},
        )
        assert blocked.status_code == 200

    # Restart: fresh TestClient re-runs lifespan, which resumes the chain and
    # reloads the persisted kill switch.
    with TestClient(app) as client:
        state = client.get("/kill-switch").json()
        assert state["kill_switch"] is True
        again = client.post("/kill-switch", json={"engaged": True})
        assert again.status_code == 200  # no UNIQUE collision on audit seq
        audit = client.get("/audit").json()
        assert audit["source"] == "live"
        assert audit["ok"] is True
        client.post("/kill-switch", json={"engaged": False})
