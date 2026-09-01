"""Compliance additions: lexicon word boundaries, card-number escape removal,
URL whitelist host-suffix, voice identity verification, PTP dating, hard DNC,
preflight ceilings, NACH/PDN fail-closed facts."""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from rekha.compliance import scan_copy
from rekha.preflight import preflight
from rekha.taxonomy import classify, hard_do_not_contact, needs_reconcile_first
from rekha.templates import render
from rekha.voice import run_scripted_session

IST = ZoneInfo("Asia/Kolkata")

CASE = {"id": "c-v", "merchant_name": "NoonCart", "first_name": "Riya", "amount_paise": 49900, "last4": "4242"}


def test_confirm_does_not_trip_fir():
    scan = scan_copy("Please confirm your payment of INR 499.")
    assert scan.ok, scan.flags


def test_ibc_word_boundary():
    assert scan_copy("Your IBC account is due.").flags  # trips
    assert scan_copy("Libibc symbols are irrelevant here.").ok  # does not


def test_card_number_blocked_even_with_ending_word():
    scan = scan_copy("card ending 4111111111111111 is pending")
    assert "PAN_SHAPED_DIGITS" in scan.flags


def test_last4_safe():
    assert scan_copy("Your card ending 4242 could not be charged.").ok


def test_url_whitelist_host_suffix():
    with pytest.raises(ValueError):
        render("svc_pay_link_sms", {"amount": "499", "ref": "r", "url": "https://rzp.io.evil.com/x"})
    with pytest.raises(ValueError):
        render("svc_pay_link_sms", {"amount": "499", "ref": "r", "url": "https://evil.com/?u=rzp.io"})
    _body, scan = render("svc_pay_link_sms", {"amount": "499", "ref": "r", "url": "https://pay.rzp.io/i/abc"})
    assert scan.ok


def test_voice_wrong_secret_fails_closed():
    session = run_scripted_session(CASE, ["haan main Riya hoon", "haan 99"], datetime(2026, 8, 22, 11, tzinfo=IST))
    assert session.stopped
    assert session.stop_reason == "VERIFY_FAILED"
    assert session.captured_ptp is None


def test_voice_correct_secret_proceeds_and_dates_ptp():
    session = run_scripted_session(CASE, ["haan main Riya hoon 42", "kal de dungi", "ok"], datetime(2026, 8, 22, 11, tzinfo=IST))
    assert session.verified
    assert not session.stopped
    assert session.captured_ptp is not None
    assert session.captured_ptp["date"] == "2026-08-23"  # a real date, not "tomorrow"


def test_voice_escalate_and_complaint_paths():
    escalated = run_scripted_session(CASE, ["human se baat karao"], datetime(2026, 8, 22, 11, tzinfo=IST))
    assert escalated.stop_reason == "ESCALATE_HUMAN"
    complaint = run_scripted_session(CASE, ["shikayat karni hai"], datetime(2026, 8, 22, 11, tzinfo=IST))
    assert complaint.stop_reason == "COMPLAINT"


def test_hard_dnc_set():
    assert hard_do_not_contact("nach_60")
    assert hard_do_not_contact("nach_69")
    assert hard_do_not_contact("U16_00930")
    assert not hard_do_not_contact("insufficient_funds")
    assert classify("nach_69").value in {"T", "C", "I", "R", "B"}  # classified, but DNC overrides in policy


def test_duplicate_rrn_reconcile_first():
    assert needs_reconcile_first("duplicate_rrn")
    assert needs_reconcile_first("duplicate_rrn_found")


def test_preflight_exempt_category_ceiling():
    # ₹2,00,000 mutual-fund mandate debit must be refused (above the ₹1L exempt ceiling)
    result = preflight({"amount_paise": 20_000_000, "mandate": {"rail": "upi", "state": "active", "max_amount": 25_000_000, "category": "mutual_fund"}})
    assert not result.ok
    assert result.reason == "above_1l_exempt_ceiling"
    # ₹50,000 mutual-fund debit passes (under ₹1L, exempt category)
    ok = preflight({"amount_paise": 5_000_000, "mandate": {"rail": "upi", "state": "active", "max_amount": 25_000_000, "category": "mutual_fund"}})
    assert ok.ok
    # ₹20,000 education debit is refused (non-exempt above ₹15k AFA-free)
    edu = preflight({"amount_paise": 2_000_000, "mandate": {"rail": "upi", "state": "active", "max_amount": 25_000_000, "category": "education"}})
    assert not edu.ok


def test_policy_hard_dnc_and_unknown_consent(monkeypatch):

    from rekha.policy import PolicyEngine

    engine = PolicyEngine()
    ctx = {
        "contacts_last_7d": 0,
        "touches_this_case": 0,
        "consent_status": "UNKNOWN",
        "hard_dnc": True,
    }
    verdict = engine.evaluate({"action": "send_template_message", "channel": "sms"}, ctx, datetime(2026, 8, 22, 11, tzinfo=IST))
    assert verdict.effect == "DENY"
    assert verdict.matched_rules[0]["id"] == "HARD_DNC"  # precedence over consent


def test_policy_nach_unknown_gap_fails_closed():
    from rekha.policy import PolicyEngine

    engine = PolicyEngine()
    ctx = {
        "contacts_last_7d": 0,
        "touches_this_case": 0,
        "consent_status": "GRANTED",
        "mandate_rail": "nach",
        "nach_gap_ok": None,  # unknown
        "customer_confirmed_funds": True,
        "nach_representations_used": 0,
    }
    verdict = engine.evaluate({"action": "schedule_mandate_presentment"}, ctx, datetime(2026, 8, 22, 11, tzinfo=IST))
    assert verdict.effect == "DENY"
    assert verdict.reason_code == "NACH_MIN_GAP"


def test_policy_pdn_unknown_defers_with_target():
    from rekha.policy import PolicyEngine

    engine = PolicyEngine()
    ctx = {
        "contacts_last_7d": 0,
        "touches_this_case": 0,
        "consent_status": "GRANTED",
        "mandate_rail": "upi",
        "pdn_ready": False,
        "pdn_elapsed_hours": 5,
    }
    now = datetime(2026, 8, 22, 11, tzinfo=IST)
    verdict = engine.evaluate({"action": "schedule_mandate_presentment"}, ctx, now)
    assert verdict.effect == "DEFER"
    target = datetime.fromisoformat(verdict.defer_until)
    # 24h minus 5h elapsed plus a quarter-hour guard band
    expected_min = now + __import__("datetime").timedelta(hours=19)
    assert target >= expected_min


def test_policy_email_quiet_hours_defers():
    from rekha.policy import PolicyEngine

    engine = PolicyEngine()
    ctx = {"contacts_last_7d": 0, "touches_this_case": 0, "consent_status": "GRANTED", "local_hour": 3}
    verdict = engine.evaluate({"action": "create_payment_link", "channel": "email"}, ctx, datetime(2026, 8, 22, 3, 0, tzinfo=IST))
    assert verdict.effect == "DEFER"
    assert verdict.reason_code == "QUIET_HOURS"


def test_kill_switch_blocks_silent_retry_too():
    from rekha.engine import RecoveryEngine
    from rekha.runtime import FLAGS
    from rekha.sandbox import FileInbox, RazorpaySandbox

    FLAGS.kill_switch = True
    try:
        engine = RecoveryEngine(payments=RazorpaySandbox(), comms=FileInbox(), strategy="rekha")
        case = {
            "id": "case-ks",
            "customer_id": "cust-ks",
            "loss_class": "payment_failure",
            "amount_paise": 99900,
            "error_reason": "bank_technical_error",
            "error_source": "gateway",
            "consent_status": "GRANTED",
            "contacts_last_7d": 0,
            "touches_this_case": 0,
            "hours_since_failure": 40,
        }
        result = engine.run_case(case, datetime(2026, 8, 22, 11, tzinfo=IST))
        assert result.verdict["reason_code"] == "KILL_SWITCH"
        assert result.executed is False
    finally:
        FLAGS.kill_switch = False


def test_kill_switch_requires_token_in_prod(monkeypatch):
    from fastapi.testclient import TestClient
    from rekha.api import app
    from rekha.config import settings

    monkeypatch.setattr(settings, "rekha_env", "prod")
    with TestClient(app) as client:
        res = client.post("/kill-switch", json={"engaged": True})
        assert res.status_code == 401


def test_webhook_unsigned_rejected_in_prod(monkeypatch):
    from fastapi.testclient import TestClient
    from rekha.api import app
    from rekha.config import settings

    monkeypatch.setattr(settings, "rekha_env", "prod")
    with TestClient(app) as client:
        res = client.post(
            "/webhooks/razorpay",
            headers={"X-Razorpay-Event-Id": "evt-prod-1"},
            json={"event": "payment.failed"},
        )
        assert res.status_code == 400
        assert res.json()["detail"]["code"] == "SECRET_UNSET"


def test_webhook_sign_secret_unset_in_prod(monkeypatch):
    from fastapi.testclient import TestClient
    from rekha.api import app
    from rekha.config import settings

    monkeypatch.setattr(settings, "rekha_env", "prod")
    monkeypatch.setattr(settings, "ops_token", "ops")
    monkeypatch.setattr(settings, "razorpay_webhook_secret", "")
    with TestClient(app) as client:
        res = client.post("/webhooks/sign", json={"event": "payment.failed"}, headers={"X-Ops-Token": "ops"})
        assert res.status_code == 400
        assert res.json()["detail"]["code"] == "SECRET_UNSET"


def test_webhook_sign_then_accept_in_prod(monkeypatch):
    from fastapi.testclient import TestClient
    from rekha.api import app
    from rekha.config import settings

    monkeypatch.setattr(settings, "rekha_env", "prod")
    monkeypatch.setattr(settings, "ops_token", "ops-secret")
    monkeypatch.setattr(settings, "razorpay_webhook_secret", "whsec")
    payload = {
        "event": "payment.failed",
        "payload": {"payment": {"entity": {"id": "pay-signed", "status": "failed", "amount": 100}}},
    }
    with TestClient(app) as client:
        denied = client.post("/webhooks/sign", json=payload)
        assert denied.status_code == 401
        signed = client.post(
            "/webhooks/sign",
            json=payload,
            headers={"X-Ops-Token": "ops-secret"},
        )
        assert signed.status_code == 200
        sig = signed.json()["signature"]
        bad = client.post(
            "/webhooks/razorpay",
            headers={"X-Razorpay-Event-Id": "evt-signed-bad", "X-Razorpay-Signature": "deadbeef"},
            json=payload,
        )
        assert bad.status_code == 400
        assert bad.json()["detail"]["code"] == "BAD_SIGNATURE"
        ok = client.post(
            "/webhooks/razorpay?wait=true",
            headers={"X-Razorpay-Event-Id": "evt-signed-ok", "X-Razorpay-Signature": sig},
            json=payload,
        )
        assert ok.status_code == 200
        assert ok.json()["ok"] is True
