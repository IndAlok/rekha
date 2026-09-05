from unittest.mock import MagicMock

import httpx
from fastapi.testclient import TestClient
from rekha.advisor import (
    GROQ_BASE,
    GROQ_FALLBACK_MODEL,
    advise,
    advisor_base,
    advisor_public,
    filter_proposal,
)
from rekha.api import app
from rekha.config import settings
from rekha.engine import RecoveryEngine
from rekha.eval.runner import run_eval
from rekha.policy import PolicyEngine
from rekha.sandbox import FileInbox, RazorpaySandbox


def test_advisor_defaults_to_groq():
    assert advisor_base() == GROQ_BASE
    pub = advisor_public()
    assert pub["configured"] is False
    assert pub["provider"] == "off"
    assert pub["eval"] == "off"
    assert pub["live_only"] is True
    assert pub["timeout_s"] == 2.5
    assert pub["fallback_model"] == GROQ_FALLBACK_MODEL
    assert "reason_if_same_action" in pub["can"]
    assert "pick_tool" in pub["cannot"]
    assert "execute" in pub["cannot"]


def test_advisor_provider_from_host(monkeypatch):
    monkeypatch.setattr(settings, "openai_api_key", "gsk_x")
    monkeypatch.setattr(settings, "openai_base_url", "https://openrouter.ai/api/v1")
    assert advisor_public()["provider"] == "openrouter"
    monkeypatch.setattr(settings, "openai_base_url", "https://generativelanguage.googleapis.com/v1beta")
    assert advisor_public()["provider"] == "gemini"
    monkeypatch.setattr(settings, "openai_base_url", "https://api.openai.com/v1")
    assert advisor_public()["provider"] == "openai"
    monkeypatch.setattr(settings, "openai_base_url", "http://localhost:11434/v1")
    assert advisor_public()["provider"] == "openai_compat"


def test_advise_401_fails_closed(monkeypatch):
    monkeypatch.setattr(settings, "openai_api_key", "gsk_test")
    post = MagicMock(return_value=SimpleStatus(401))
    monkeypatch.setattr(httpx, "post", post)
    assert advise({"id": "c1"}, {}) is None
    assert post.call_count == 1


def test_advise_connect_error_fails_closed(monkeypatch):
    monkeypatch.setattr(settings, "openai_api_key", "gsk_test")
    post = MagicMock(side_effect=httpx.ConnectError("down"))
    monkeypatch.setattr(httpx, "post", post)
    assert advise({"id": "c1"}, {}) is None
    assert post.call_count == 1


def test_extract_json_and_unreadable(monkeypatch):
    from rekha.advisor import _extract_json

    assert _extract_json("") is None
    assert _extract_json("not json") is None
    assert _extract_json('{"action": "suppress_and_stop"}')["action"] == "suppress_and_stop"
    monkeypatch.setattr(settings, "openai_api_key", "gsk_test")
    post = MagicMock(return_value=SimpleStatus(200, "definitely not json"))
    monkeypatch.setattr(httpx, "post", post)
    assert advise({"id": "c1"}, {}) is None
    assert post.call_count == 4


def test_advisor_public_hides_key(monkeypatch):
    monkeypatch.setattr(settings, "openai_api_key", "gsk_secret")
    monkeypatch.setattr(settings, "openai_base_url", GROQ_BASE)
    monkeypatch.setattr(settings, "openai_model", "llama-3.3-70b-versatile")
    pub = advisor_public()
    assert pub["configured"] is True
    assert pub["provider"] == "groq"
    assert pub["model"] == "llama-3.3-70b-versatile"
    blob = str(pub)
    assert "gsk_" not in blob
    assert "secret" not in blob


def test_status_with_key_does_not_leak(monkeypatch):
    monkeypatch.setattr(settings, "openai_api_key", "gsk_leaked_secret")
    with TestClient(app) as client:
        body = client.get("/status").json()
    assert body["advisor"]["configured"] is True
    assert body["advisor"]["provider"] == "groq"
    assert body["advisor"]["eval"] == "off"
    assert "gsk_" not in str(body)
    assert "leaked" not in str(body)


def test_filter_proposal_reason_only():
    out = filter_proposal(
        {
            "action": "create_payment_link",
            "reason": "salary window",
            "channel": "sms",
            "amount_paise": 1,
            "send_after": "2099-01-01T00:00:00+05:30",
            "extra": {"send_after": "2099-01-01T00:00:00+05:30", "template_id": "svc_x"},
        }
    )
    assert out == {"action": "create_payment_link", "reason": "salary window"}


def test_advise_reads_fenced_json(monkeypatch):
    monkeypatch.setattr(settings, "openai_api_key", "gsk_test")

    class Resp:
        status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": '```json\n{"action": "suppress_and_stop", "reason": "stop"}\n```'}}]}

    monkeypatch.setattr(httpx, "post", MagicMock(return_value=Resp()))
    out = advise({"id": "c1", "amount_paise": 100}, {"class": "C"})
    assert out["action"] == "suppress_and_stop"
    assert out["reason"] == "stop"


def test_advise_429_falls_back_to_playbook(monkeypatch):
    monkeypatch.setattr(settings, "openai_api_key", "gsk_test")
    post = MagicMock(return_value=SimpleStatus(429))
    monkeypatch.setattr(httpx, "post", post)
    assert advise({"id": "c1"}, {}) is None
    assert post.call_count == 1


def test_advise_timeout_does_not_retry(monkeypatch):
    monkeypatch.setattr(settings, "openai_api_key", "gsk_test")
    post = MagicMock(side_effect=httpx.TimeoutException("slow"))
    monkeypatch.setattr(httpx, "post", post)
    assert advise({"id": "c1"}, {}) is None
    assert post.call_count == 1


def test_advise_drops_json_mode_on_400(monkeypatch):
    monkeypatch.setattr(settings, "openai_api_key", "gsk_test")
    calls = []

    def post(*_a, **kwargs):
        body = kwargs["json"]
        calls.append(body)
        if "response_format" in body:
            return SimpleStatus(400)
        return SimpleStatus(200, '{"action": "suppress_and_stop", "reason": "ok"}')

    monkeypatch.setattr(httpx, "post", post)
    out = advise({"id": "c1"}, {})
    assert out["action"] == "suppress_and_stop"
    assert any("response_format" in c for c in calls)
    assert any("response_format" not in c for c in calls)


def test_advise_fallback_model_after_404(monkeypatch):
    monkeypatch.setattr(settings, "openai_api_key", "gsk_test")
    monkeypatch.setattr(settings, "openai_model", "llama-3.3-70b-versatile")
    models = []

    def post(*_a, **kwargs):
        body = kwargs["json"]
        models.append(body["model"])
        if body["model"] != GROQ_FALLBACK_MODEL:
            return SimpleStatus(404)
        return SimpleStatus(200, '{"action": "escalate_to_merchant", "reason": "8b"}')

    monkeypatch.setattr(httpx, "post", post)
    out = advise({"id": "c1"}, {})
    assert out["reason"] == "8b"
    assert GROQ_FALLBACK_MODEL in models


def test_eval_never_calls_advise(monkeypatch):
    def boom(*_a, **_k):
        raise AssertionError("eval must not call the advisor")

    monkeypatch.setattr("rekha.engine.advise", boom)
    monkeypatch.setattr(settings, "openai_api_key", "gsk_should_not_fire")
    payload = run_eval(seed=42, write=False, write_golden=False)
    assert payload["report"]["n"] == 200
    assert payload["report"]["advisor"] == "off"


def test_persist_false_skips_advisor_when_key_set(monkeypatch):
    def boom(*_a, **_k):
        raise AssertionError("persist=False must not call advise")

    monkeypatch.setattr(settings, "openai_api_key", "gsk_test")
    monkeypatch.setattr("rekha.engine.advise", boom)
    engine = RecoveryEngine(
        payments=RazorpaySandbox(budget=0),
        comms=FileInbox(),
        policy=PolicyEngine(),
        strategy="rekha",
        persist=False,
    )
    result = engine.run_case(_case(), _now())
    assert "advisor" not in result.proposal


def test_live_engine_applies_matching_reason(monkeypatch):
    monkeypatch.setattr(settings, "openai_api_key", "gsk_test")
    monkeypatch.setattr(
        "rekha.engine.propose",
        lambda *_a, **_k: {
            "action": "suppress_and_stop",
            "reason": "playbook",
            "engine": "router",
            "channel": "internal",
        },
    )
    monkeypatch.setattr(
        "rekha.engine.advise",
        lambda *_a, **_k: {
            "action": "suppress_and_stop",
            "reason": "salary window from groq",
            "channel": "sms",
            "send_after": "2099-01-01T00:00:00+05:30",
        },
    )
    result = _live_engine().run_case(_case(), _now())
    assert result.proposal["action"] == "suppress_and_stop"
    assert result.proposal["reason"] == "salary window from groq"
    assert result.proposal["channel"] == "internal"
    assert result.proposal.get("send_after") is None
    assert result.proposal["advisor"]["applied"] is True
    assert result.proposal["advisor"]["suggested"] == "suppress_and_stop"


def test_live_engine_disagreement_keeps_playbook(monkeypatch):
    monkeypatch.setattr(settings, "openai_api_key", "gsk_test")
    monkeypatch.setattr(
        "rekha.engine.propose",
        lambda *_a, **_k: {
            "action": "suppress_and_stop",
            "reason": "playbook",
            "engine": "router",
            "channel": "internal",
        },
    )
    monkeypatch.setattr(
        "rekha.engine.advise",
        lambda *_a, **_k: {"action": "create_payment_link", "reason": "nag them", "channel": "sms"},
    )
    result = _live_engine().run_case(_case(), _now())
    assert result.proposal["action"] == "suppress_and_stop"
    assert result.proposal["reason"] == "playbook"
    assert result.proposal["advisor"]["applied"] is False
    assert result.proposal["advisor"]["suggested"] == "create_payment_link"


def test_live_engine_advisor_raise_keeps_playbook(monkeypatch):
    monkeypatch.setattr(settings, "openai_api_key", "gsk_test")

    def boom(*_a, **_k):
        raise RuntimeError("groq down")

    monkeypatch.setattr("rekha.engine.advise", boom)
    result = _live_engine().run_case(_case(), _now())
    assert result.proposal["action"] == "silent_retry_same_instrument"
    assert result.proposal["advisor"]["called"] is True
    assert result.proposal["advisor"]["applied"] is False
    assert result.proposal["advisor"]["error"] == "RuntimeError"


def test_advise_unexpected_exception_does_not_retry(monkeypatch):
    monkeypatch.setattr(settings, "openai_api_key", "gsk_test")
    post = MagicMock(side_effect=RuntimeError("boom"))
    monkeypatch.setattr(httpx, "post", post)
    assert advise({"id": "c1"}, {}) is None
    assert post.call_count == 1


class SimpleStatus:
    def __init__(self, status_code, content='{"action": "suppress_and_stop"}'):
        self.status_code = status_code
        self._content = content

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError("should not run")

    def json(self):
        return {"choices": [{"message": {"content": self._content}}]}


def _live_engine() -> RecoveryEngine:
    return RecoveryEngine(
        payments=RazorpaySandbox(budget=0),
        comms=FileInbox(),
        policy=PolicyEngine(),
        strategy="rekha",
        persist=True,
    )


def _case() -> dict:
    return {
        "id": "c-adv-1",
        "customer_id": "cust-adv",
        "amount_paise": 129900,
        "loss_class": "payment_failure",
        "error_reason": "insufficient_funds",
        "error_source": "customer",
        "consent_status": "GRANTED",
        "contacts_last_7d": 0,
        "touches_this_case": 0,
        "hours_since_failure": 40,
        "contact": "+919800000009",
    }


def _now():
    from datetime import datetime
    from zoneinfo import ZoneInfo

    return datetime(2026, 8, 22, 11, 30, tzinfo=ZoneInfo("Asia/Kolkata"))
