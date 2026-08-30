"""T6 feature tests: MAC layer, MSMED ladder, PTP grace/instalments,
degradation statistics, Awaaz endpoint."""

from __future__ import annotations

from datetime import date, datetime
from zoneinfo import ZoneInfo

from rekha.degradation import DegradationMonitor
from rekha.msmed import compute_position, due_date
from rekha.p2p import Instalment, PromiseToPay, evaluate_promise, freeze_active, remind_if_open
from rekha.taxonomy import mac_forbidden, mac_retry_hours

IST = ZoneInfo("Asia/Kolkata")


def test_mac_absolute_stops():
    assert mac_forbidden("MAC03")
    assert mac_forbidden("mac 21")
    assert not mac_forbidden("MAC24")
    assert not mac_forbidden(None)


def test_mac_intervals():
    assert mac_retry_hours("MAC24") == 1
    assert mac_retry_hours("MAC30") == 240
    assert mac_retry_hours(None) is None


def test_mac_stop_overrides_policy():
    from rekha.policy import PolicyEngine

    engine = PolicyEngine()
    ctx = {
        "contacts_last_7d": 0,
        "touches_this_case": 0,
        "consent_status": "GRANTED",
        "mac_forbidden": True,
    }
    verdict = engine.evaluate({"action": "silent_retry_same_instrument"}, ctx, datetime(2026, 8, 22, 11, tzinfo=IST))
    assert verdict.effect == "DENY"
    assert verdict.reason_code == "MAC_DO_NOT_RETRY"
    assert verdict.matched_rules[0]["overridable"] is False


def test_msmed_due_date_caps_agreement():
    assert due_date(date(2026, 1, 1), 90) == date(2026, 2, 15)  # capped at 45
    assert due_date(date(2026, 1, 1), 30) == date(2026, 1, 31)
    assert due_date(date(2026, 1, 1), None) == date(2026, 1, 16)  # 15 default


def test_msmed_interest_compounds():
    pos = compute_position(
        acceptance_date=date(2026, 1, 1),
        today=date(2026, 3, 1),
        amount_paise=100_000_00,
        agreed_days=30,
    )
    assert pos.eligible
    assert pos.days_past_due == 29
    # ~1 month of 3x Bank Rate compound interest on ₹1,00,000
    assert 1_500_00 < pos.interest_paise < 2_000_00


def test_msmed_ineligible_for_non_msme():
    pos = compute_position(acceptance_date=date(2026, 1, 1), today=date(2026, 3, 1), amount_paise=100, supplier_msme=False)
    assert not pos.eligible


def test_b2b_msme_escalation_uses_factual_template():
    from rekha.playbooks.chaser import propose_b2b

    case = {
        "days_past_due": 50,
        "supplier_msme": True,
        "acceptance_date": "2026-05-01",
        "as_of_date": "2026-08-20",
        "amount_paise": 250_000_00,
        "agreed_payment_days": 30,
    }
    proposal = propose_b2b(case)
    assert proposal["template_id"] == "svc_msme_email"
    assert proposal["reason"] == "msmed_s16_factual_email"
    assert float(proposal["msmed_interest_inr"]) > 0


def test_ptp_grace_period():
    p = PromiseToPay("p1", "cust", "c1", 10000, "2026-08-25")
    # Day after the promise, still inside the +2 day grace: dunning stays paused.
    assert freeze_active(p, datetime(2026, 8, 26, 10, tzinfo=IST))
    assert freeze_active(p, datetime(2026, 8, 27, 10, tzinfo=IST))
    assert not freeze_active(p, datetime(2026, 8, 28, 10, tzinfo=IST))
    # Breaking requires passing the grace window too.
    assert evaluate_promise(p, 0, "2026-08-26").state != "Broken"
    assert evaluate_promise(p, 0, "2026-08-28").state == "Broken"


def test_ptp_instalments_evaluated():
    p = PromiseToPay(
        "p2",
        "cust",
        "c1",
        20000,
        "2026-09-05",
        instalments=[Instalment(1, 10000, "2026-08-25"), Instalment(2, 10000, "2026-09-05")],
    )
    out = evaluate_promise(p, 0, "2026-08-26", apply_instalments=[("2026-08-25", 10000)])
    assert out.instalments[0].state == "Kept"
    assert out.state in {"Open", "Reminded"}  # first instalment kept, second pending
    out2 = evaluate_promise(p, 0, "2026-09-06", apply_instalments=[("2026-08-25", 10000), ("2026-09-05", 10000)])
    assert out2.state == "Kept"
    out3 = evaluate_promise(p, 0, "2026-09-06", apply_instalments=[("2026-08-25", 10000)])
    assert out3.state == "Broken"


def test_ptp_reminded_transition():
    p = PromiseToPay("p3", "cust", "c1", 10000, "2026-08-25")
    remind_if_open(p)
    assert p.state == "Reminded"


def test_degradation_requires_three_of_five_windows():
    mon = DegradationMonitor(min_attempts=30, confirm_windows=3)
    for _ in range(40):
        mon.record(issuer="HDFC", method="upi", psp=None, success=False, amount_paise=100000)
    mon.close_window(issuer="HDFC", method="upi", psp=None)
    assert mon.slices["HDFC|upi|*"].window_history == [True]
    assert mon.incident(issuer="HDFC", method="upi") is False  # 1 of 3. hysteresis holds
    for _ in range(3):
        mon.close_window(issuer="HDFC", method="upi", psp=None)
    assert mon.incident(issuer="HDFC", method="upi") is True


def test_degradation_retries_never_feed_monitor():
    mon = DegradationMonitor()
    mon.record(issuer="ICICI", method="card", psp=None, success=False, attempt_no=2)
    assert mon.slices == {}


def test_degradation_ranks_by_rupees():
    mon = DegradationMonitor(min_attempts=5, confirm_windows=1)
    for _ in range(10):
        mon.record(issuer="SBI", method="upi", psp=None, success=False, amount_paise=500_000)
        mon.record(issuer="AXIS", method="upi", psp=None, success=False, amount_paise=10_000)
    ranked = mon.ranked_by_rupees()
    assert ranked[0]["slice"].startswith("SBI")


def test_awaaz_endpoint_runs_session():
    from fastapi.testclient import TestClient
    from rekha.api import app

    with TestClient(app) as client:
        res = client.post(
            "/awaaz/session",
            json={
                "case": {"id": "c-awaaz-1", "merchant_name": "NoonCart", "first_name": "Riya", "amount_paise": 49900, "last4": "4242"},
                "lines": ["haan 42", "kal de dungi", "ok"],
            },
        )
        assert res.status_code == 200
        body = res.json()
        assert body["verified"] is True
        assert body["captured_ptp"]["date"].startswith("20")
        assert any(t["state"] == "VERIFYING" for t in body["turns"])
