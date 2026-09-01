"""Recovery events: payment.authorized/captured never open a dunning case;
attribution lands in the ledger; the late-auth race is closed end to end."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from rekha.engine import RecoveryEngine
from rekha.ingest import event_to_case
from rekha.sandbox import FileInbox, RazorpaySandbox

IST = ZoneInfo("Asia/Kolkata")

FAILURE_EVENT = {
    "event_id": "evt-fail-1",
    "event_type": "payment.failed",
    "payload": {
        "customer": {"id": "cust-r", "name": "Riya", "contact": "+919800000001", "consent": True},
        "payment": {"entity": {"id": "pay-r1", "entity": "payment", "status": "failed", "amount": 129900, "order_id": "order-r1", "error_reason": "insufficient_funds", "error_source": "customer"}},
    },
}

AUTHORIZED_EVENT = {
    "event_id": "evt-auth-1",
    "event_type": "payment.authorized",
    "payload": {
        "customer": {"id": "cust-r", "name": "Riya", "contact": "+919800000001", "consent": True},
        "payment": {"entity": {"id": "pay-r1", "entity": "payment", "status": "authorized", "amount": 129900, "order_id": "order-r1"}},
    },
}


def _engine() -> RecoveryEngine:
    return RecoveryEngine(payments=RazorpaySandbox(), comms=FileInbox(), strategy="rekha")


def test_authorized_event_is_recovery_not_loss():
    case = event_to_case(AUTHORIZED_EVENT)
    assert case["loss_class"] == "recovery_event"
    assert case["live_statuses"]["payment"] == "authorized"


def test_failed_then_authorized_same_case_identity():
    failed = event_to_case(FAILURE_EVENT)
    paid = event_to_case(AUTHORIZED_EVENT)
    assert failed["id"] == paid["id"]  # both key on order-r1


def test_recovery_event_never_sends_outreach():
    engine = _engine()
    case = event_to_case(AUTHORIZED_EVENT)
    result = engine.run_case(case, datetime(2026, 8, 22, 11, 30, tzinfo=IST))
    assert result.proposal["action"] == "suppress_and_stop"
    assert result.executed is False
    assert engine.comms.messages == []


def test_live_attribution_records_ledger():
    from rekha.db.session import init_db
    from rekha.store import LedgerStore

    init_db()
    engine = RecoveryEngine(payments=RazorpaySandbox(), comms=FileInbox(), strategy="rekha", persist=True)
    failed_case = event_to_case(FAILURE_EVENT)
    engine.run_case(failed_case, datetime(2026, 8, 22, 11, 30, tzinfo=IST))
    paid_case = event_to_case(AUTHORIZED_EVENT)
    result = engine.run_case(paid_case, datetime(2026, 8, 22, 12, 30, tzinfo=IST))
    assert result.recovered is True
    assert result.recovery_source == "self_cure"
    totals = LedgerStore.total()
    assert totals["entries"] >= 1
    assert totals["self_cure_paise"] == 129900
    assert totals["agent_paise"] == 0


def test_live_attribution_is_agent_only_after_execute():
    from rekha.store import LedgerStore

    engine = RecoveryEngine(payments=RazorpaySandbox(), comms=FileInbox(), strategy="rekha", persist=True)
    failed_case = event_to_case(FAILURE_EVENT)
    failed_case["error_reason"] = "bank_technical_error"
    failed_case["error_source"] = "gateway"
    ran = engine.run_case(failed_case, datetime(2026, 8, 22, 11, 30, tzinfo=IST))
    assert ran.executed is True
    paid_case = event_to_case(AUTHORIZED_EVENT)
    result = engine.run_case(paid_case, datetime(2026, 8, 22, 12, 30, tzinfo=IST))
    assert result.recovery_source == "agent"
    totals = LedgerStore.total()
    assert totals["agent_paise"] == 129900


def test_deemed_transaction_blocked_until_reconciled():
    engine = _engine()
    case = event_to_case(FAILURE_EVENT)
    case["error_reason"] = "deemed_transaction"
    case["error_source"] = "gateway"
    case["id"] = "case-deemed"
    case["contacts_last_7d"] = 0
    case["touches_this_case"] = 0
    result = engine.run_case(case, datetime(2026, 8, 22, 11, 30, tzinfo=IST))
    assert result.verdict["effect"] == "DENY"
    assert result.verdict["reason_code"] == "RECONCILE_BEFORE_RETRY"
    assert result.executed is False


def test_settled_deemed_transaction_self_cures():
    engine = _engine()
    case = event_to_case(FAILURE_EVENT)
    case["error_reason"] = "duplicate_rrn"
    case["id"] = "case-dup"
    case["contacts_last_7d"] = 0
    case["touches_this_case"] = 0
    # The webhook says failed; the settlement layer says the money moved.
    # deep_check confirms via acquirer_data + settled flag, not the status.
    engine.payments.seed_entity(
        "payment",
        case["source_refs"]["payment_id"],
        {
            "id": case["source_refs"]["payment_id"],
            "status": "failed",
            "acquirer_data": {"rrn": "123456789012"},
            "settled": True,
        },
    )
    result = engine.run_case(case, datetime(2026, 8, 22, 11, 30, tzinfo=IST))
    assert result.recovery_source == "self_cure"
    assert result.executed is False
