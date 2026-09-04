from datetime import datetime
from zoneinfo import ZoneInfo

from fastapi.testclient import TestClient
from rekha.advisor import filter_proposal
from rekha.api import app
from rekha.clocks import is_bank_holiday
from rekha.config import settings
from rekha.engine import RecoveryEngine, is_customer_contact
from rekha.eval.cohort import generate_cohort, parse_eval_now
from rekha.eval.runner import run_eval
from rekha.execute import Executor
from rekha.paths import FIXTURES_DIR
from rekha.policy import PolicyEngine, Verdict
from rekha.sandbox import FileInbox, RazorpaySandbox, UnavailablePayments
from rekha.store import ConsentStore, PromiseStore

IST = ZoneInfo("Asia/Kolkata")


def test_filter_proposal_keeps_reason_drops_channel():
    out = filter_proposal(
        {"action": "suppress_and_stop", "channel": "sms", "reason": "stay", "template_id": "nope"}
    )
    assert out == {"action": "suppress_and_stop", "reason": "stay"}


def test_dark_pattern_draft_denies():
    case = next(c for c in generate_cohort(42) if c.get("trap") == "dark_pattern_bait")
    engine = RecoveryEngine(
        payments=RazorpaySandbox(budget=0),
        comms=FileInbox(),
        policy=PolicyEngine(),
        strategy="rekha",
    )
    result = engine.run_case(case, parse_eval_now(case))
    assert result.blocked
    assert result.verdict["reason_code"] == "COMPLIANCE_COPY_VETO"
    assert not result.executed


def test_republic_day_is_holiday():
    assert is_bank_holiday(datetime(2026, 1, 26, 12, tzinfo=IST))
    assert not is_bank_holiday(datetime(2026, 1, 27, 12, tzinfo=IST))


def test_eval_write_false_leaves_cohort():
    path = FIXTURES_DIR / "cohort_200.jsonl"
    original = path.read_text(encoding="utf-8")
    run_eval(seed=42, write=False, write_golden=False)
    assert path.read_text(encoding="utf-8") == original


def test_health_503_when_boot_failed():
    from rekha import api as api_mod

    with TestClient(app) as client:
        api_mod.STATE["boot_ok"] = False
        api_mod.STATE["boot_errors"] = ["init_db: boom"]
        res = client.get("/health")
        assert res.status_code == 503
        body = res.json()
        assert body["ok"] is False
        assert "init_db" in body["errors"][0]


def test_kill_reports_persist_failure(monkeypatch):
    def boom(*_a, **_k):
        raise RuntimeError("kv down")

    monkeypatch.setattr("rekha.api.RuntimeKVStore.set", boom)
    with TestClient(app) as client:
        res = client.post("/kill-switch", json={"engaged": True})
        assert res.status_code == 200
        assert res.json()["kill_switch"] is True
        assert res.json()["persisted"] is False


def test_sandbox_reads_settings_budget(monkeypatch):
    monkeypatch.setattr(settings, "payment_link_budget", 1)
    psp = RazorpaySandbox()
    assert psp.budget == 1


def test_razorpay_unavailable_in_prod(monkeypatch):
    from rekha import api as api_mod

    monkeypatch.setattr(settings, "rekha_env", "prod")
    monkeypatch.setattr(settings, "payments_adapter", "razorpay_test")
    monkeypatch.setattr(settings, "razorpay_key_id", "")
    pay = api_mod._payments()
    assert isinstance(pay, UnavailablePayments)
    assert api_mod.STATE["payments_adapter_effective"] == "unavailable"
    assert api_mod.STATE["payments_error"]


def test_customer_flags_overlay_dnd():
    ConsentStore.upsert("cust-flag", status="GRANTED")
    row = ConsentStore.set_flags("cust-flag", dnd=True, legal_hold=True, opt_out=True)
    assert row["dnd"] is True
    assert row["legal_hold"] is True
    assert row["opt_out"] is True
    over = ConsentStore.overlay(
        {
            "id": "case-flag",
            "customer_id": "cust-flag",
            "consent_status": "GRANTED",
            "suppressed": False,
        }
    )
    assert over["suppressed"] is True
    assert over["dnd"] is True
    assert over["legal_hold"] is True


def test_customer_flags_endpoint():
    with TestClient(app) as client:
        res = client.post("/ops/customers/cust-api/flags", json={"dnd": True})
        assert res.status_code == 200
        assert res.json()["dnd"] is True


def test_awaaz_persists_promise():
    with TestClient(app) as client:
        res = client.post(
            "/awaaz/session",
            json={
                "case": {
                    "id": "c-awaaz-ptp",
                    "customer_id": "cust-awaaz",
                    "merchant_name": "NoonCart",
                    "first_name": "Riya",
                    "amount_paise": 49900,
                    "last4": "4242",
                },
                "lines": ["haan 42", "kal de dungi", "ok"],
            },
        )
        assert res.status_code == 200
        assert res.json()["captured_ptp"]
        assert res.json()["promise"]
        stored = PromiseStore.for_case("c-awaaz-ptp")
        assert stored is not None
        assert stored["promised_date"].startswith("20")


def test_status_exposes_boot_and_quality():
    with TestClient(app) as client:
        body = client.get("/status").json()
        assert "boot_ok" in body
        assert "whatsapp_quality" in body
        assert "degradation" in body
        assert "payments_adapter_effective" in body


def test_presentment_is_not_customer_contact():
    assert is_customer_contact({"action": "schedule_mandate_presentment", "channel": "sms"}) is False
    assert is_customer_contact({"action": "silent_retry_same_instrument", "channel": "sms"}) is False
    assert is_customer_contact({"action": "create_payment_link", "channel": "sms"}) is True
    inbox = FileInbox()
    ex = Executor(RazorpaySandbox(), inbox)
    verdict = Verdict(effect="ALLOW", reason_code="TEST", matched_rules=[], policy_version="t", policy_hash="h")
    out = ex.execute(
        {"id": "c-pres", "customer_id": "cust-pres", "amount_paise": 129900, "contact": "+919800000009"},
        {"action": "schedule_mandate_presentment", "channel": "sms", "template_id": "svc_pdn_sms"},
        verdict,
        datetime(2026, 8, 22, 11, tzinfo=IST),
    )
    assert out["ok"] is True
    assert out.get("silent") is True
    assert inbox.messages == []


def test_persist_dnd_close_does_not_crash():
    case = next(c for c in generate_cohort(42) if c.get("trap") == "dnd")
    engine = RecoveryEngine(
        payments=RazorpaySandbox(),
        comms=FileInbox(),
        policy=PolicyEngine(),
        strategy="rekha",
        persist=True,
    )
    result = engine.run_case(case, parse_eval_now(case))
    assert result.blocked
    assert result.verdict["reason_code"] == "SUPPRESSED"


def test_eval_run_does_not_rewrite_cohort():
    path = FIXTURES_DIR / "cohort_200.jsonl"
    original = path.read_text(encoding="utf-8")
    with TestClient(app) as client:
        res = client.post("/eval/run?seed=42")
        assert res.status_code == 200
    assert path.read_text(encoding="utf-8") == original
