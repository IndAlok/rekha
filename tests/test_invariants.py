from rekha.engine import RecoveryEngine
from rekha.eval.cohort import generate_cohort, parse_eval_now
from rekha.policy import PolicyEngine
from rekha.sandbox import FileInbox, RazorpaySandbox


def _run(trap: str):
    case = next(c for c in generate_cohort(42) if c.get("trap") == trap)
    engine = RecoveryEngine(
        payments=RazorpaySandbox(),
        comms=FileInbox(),
        policy=PolicyEngine(),
        strategy="rekha",
    )
    return engine.run_case(case, parse_eval_now(case)), case


def test_class_b_no_customer_message():
    result, _ = _run("class_b")
    assert result.proposal["action"] == "alert_engineering"
    assert result.proposal["channel"] == "internal"
    assert not result.violations


def test_late_auth_self_cure():
    result, _ = _run("late_auth")
    assert result.recovery_source == "self_cure"
    assert result.recovered
    assert result.proposal["action"] == "suppress_and_stop"


def test_dnd_no_customer_channel():
    result, _ = _run("dnd")
    assert result.proposal.get("channel") not in {"sms", "whatsapp", "email", "voice"}
    assert "contacted_dnd" not in result.violations
    assert result.verdict["effect"] == "DENY"
    assert result.verdict["reason_code"] == "SUPPRESSED"
    assert not result.executed


def test_never_pause_authenticated():
    result, _ = _run("pause_authenticated")
    assert result.proposal["action"] == "suppress_and_stop"
    assert "paused_authenticated_sub" not in result.violations


def test_voice_50001_needs_approval():
    result, _ = _run("amount_50001_voice")
    assert result.verdict["effect"] == "REQUIRE_APPROVAL"
    assert not result.executed


def test_voice_49999_allows():
    result, _ = _run("amount_49999_voice")
    assert result.verdict["effect"] == "ALLOW"


def test_legal_refuse():
    result, _ = _run("legal_step_refuse")
    assert result.proposal["action"] == "refuse_legal_step"


def test_outside_hours_is_defer_not_deny():
    result, _ = _run("outside_hours_1901")
    assert result.verdict["effect"] == "DEFER"
    assert result.verdict["reason_code"] == "QUIET_HOURS"


def test_missing_counters_fail_closed():
    result, _ = _run("missing_counters")
    assert result.blocked
    assert result.verdict["reason_code"] == "FAIL_CLOSED_MISSING_FACTS"
