from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from rekha import constants
from rekha.policy import PolicyEngine

IST = ZoneInfo("Asia/Kolkata")
NOW = datetime(2026, 8, 22, 11, 30, tzinfo=IST)


def _ctx(**kwargs):
    base = {
        "contacts_last_7d": 0,
        "touches_this_case": 0,
        "consent_status": "GRANTED",
        "suppressed": False,
        "legal_hold": False,
        "recoverability_class": "C",
        "error_reason": "insufficient_funds",
        "hours_since_failure": 36,
        "reconciled": True,
        "already_paid": False,
        "ptp_active": False,
        "dispute_open": False,
        "local_hour": 11,
        "amount_paise": 129900,
        "has_coupon": False,
        "amount_mismatch": False,
        "strategic_tier": "standard",
        "requested_legal_step": False,
        "portability_nudge": False,
        "would_pause_authenticated_sub": False,
        "whatsapp_quality": "green",
    }
    base.update(kwargs)
    return base


@pytest.fixture
def eng():
    return PolicyEngine()


def test_fail_closed_missing_counters(eng):
    with pytest.raises(ValueError, match="fail-closed"):
        eng.evaluate({"action": "create_payment_link", "channel": "email"}, {"touches_this_case": 0}, NOW)


def test_class_b_denies_outreach(eng):
    v = eng.evaluate(
        {"action": "create_payment_link", "channel": "email"},
        _ctx(recoverability_class="B"),
        NOW,
    )
    assert v.effect == "DENY"
    assert v.reason_code == "CLASS_B_ENGINEERING_ONLY"


def test_quiet_hours_defer(eng):
    v = eng.evaluate(
        {"action": "create_payment_link", "channel": "whatsapp"},
        _ctx(local_hour=21),
        datetime(2026, 8, 22, 21, 1, tzinfo=IST),
    )
    assert v.effect == "DEFER"
    assert v.reason_code == "QUIET_HOURS"


def test_same_day_iff(eng):
    v = eng.evaluate(
        {"action": "silent_retry_same_instrument"},
        _ctx(error_reason="insufficient_funds", hours_since_failure=2),
        NOW,
    )
    assert v.effect == "DENY"
    assert v.reason_code == "IFF_SAME_DAY_SUPPRESSES_APPROVAL"


def test_coupon_on_sms(eng):
    v = eng.evaluate(
        {"action": "send_template_message", "channel": "sms"},
        _ctx(has_coupon=True),
        NOW,
    )
    assert v.effect == "DENY"
    assert v.reason_code == "COUPON_RECLASSIFIES_PROMOTIONAL"


def test_upi_budget(eng):
    v = eng.evaluate(
        {"action": "schedule_mandate_presentment", "channel": "sms"},
        _ctx(mandate_rail="upi", mandate_attempts_used=4, in_upi_peak=False, pdn_elapsed_hours=36),
        NOW,
    )
    assert v.effect == "DENY"
    assert v.reason_code == "UPI_ATTEMPT_BUDGET_EXHAUSTED"


def test_pause_authenticated(eng):
    v = eng.evaluate(
        {"action": "suppress_and_stop"},
        _ctx(would_pause_authenticated_sub=True),
        NOW,
    )
    assert v.effect == "DENY"
    assert v.reason_code == "PAUSE_AUTHENTICATED_CANCELS"


def test_already_paid(eng):
    v = eng.evaluate({"action": "create_payment_link", "channel": "email"}, _ctx(already_paid=True), NOW)
    assert v.effect == "DENY"
    assert v.reason_code == "LATE_AUTH_ALREADY_PAID"


def test_voice_high_value_approval(eng):
    v = eng.evaluate(
        {"action": "send_template_message", "channel": "voice", "amount_paise": 5_000_100},
        _ctx(amount_paise=5_000_100),
        NOW,
    )
    assert v.effect == "REQUIRE_APPROVAL"


def test_silent_retry_revoked_is_deny(eng):
    v = eng.evaluate({"action": "silent_retry_same_instrument"}, _ctx(consent_status="REVOKED"), NOW)
    assert v.effect == "DENY"
    assert v.reason_code == "CONSENT_REVOKED"


def test_silent_retry_dnd_is_deny(eng):
    v = eng.evaluate({"action": "silent_retry_same_instrument"}, _ctx(suppressed=True), NOW)
    assert v.effect == "DENY"
    assert v.reason_code == "SUPPRESSED"


def test_paylink_revoked_without_channel(eng):
    v = eng.evaluate({"action": "create_payment_link"}, _ctx(consent_status="REVOKED"), NOW)
    assert v.effect == "DENY"
    assert v.reason_code == "CONSENT_REVOKED"


def test_presentment_skips_quiet_hours(eng):
    v = eng.evaluate(
        {"action": "schedule_mandate_presentment", "channel": "sms"},
        _ctx(
            local_hour=22,
            mandate_rail="upi",
            mandate_attempts_used=1,
            in_upi_peak=False,
            pdn_ready=True,
            pdn_elapsed_hours=36,
            customer_confirmed_funds=True,
        ),
        datetime(2026, 8, 22, 22, 0, tzinfo=IST),
    )
    assert v.reason_code != "QUIET_HOURS"


def test_rules_bind_constants(eng):
    quiet = next(r for r in eng.doc["rules"] if r["id"] == "QUIET_HOURS_IST")
    assert quiet["when"]["local_hour"]["not_in_range"] == [
        constants.CONTACT_WINDOW_START,
        constants.CONTACT_WINDOW_END,
    ]
    high = next(r for r in eng.doc["rules"] if r["id"] == "HIGH_VALUE_APPROVAL")
    assert high["when"]["amount_paise"]["gt"] == int(constants.CAPS["high_value_approval_paise"])


def test_high_value_follows_caps(monkeypatch):
    monkeypatch.setitem(constants.CAPS, "high_value_approval_paise", 100)
    eng = PolicyEngine()
    v = eng.evaluate(
        {"action": "create_payment_link", "channel": "email", "amount_paise": 101},
        _ctx(amount_paise=101),
        NOW,
    )
    assert v.effect == "REQUIRE_APPROVAL"
    assert v.reason_code == "AMOUNT_ABOVE_AUTO_THRESHOLD"


def test_whatsapp_red_defers(eng):
    v = eng.evaluate(
        {"action": "send_template_message", "channel": "whatsapp"},
        _ctx(whatsapp_quality="red"),
        NOW,
    )
    assert v.effect == "DEFER"
    assert v.reason_code == "WHATSAPP_QUALITY_RED"
