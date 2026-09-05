"""Desk Send: failed sample, blank event id, blank signature."""

from json import loads

from fastapi.testclient import TestClient
from rekha.api import app
from rekha.config import settings
from rekha.paths import FIXTURES_DIR
from rekha.sandbox import UnavailablePayments


def _failed_sample() -> dict:
    return loads((FIXTURES_DIR / "webhooks" / "payment_failed.json").read_text(encoding="utf-8"))


def test_unavailable_payments_hasattr_seed_entity():
    pay = UnavailablePayments()
    assert hasattr(pay, "seed_entity") is True
    assert pay.fetch_payment("pay_demo_failed") is None
    assert pay.fetch_order("order_demo") is None
    assert pay.fetch_subscription("sub") is None
    assert pay.fetch_invoice("inv") is None
    assert pay.fetch_payment_link("plink") is None
    assert pay.list_unpaid_invoices("sub") == []
    assert pay.retry_payment("pay_demo_failed")["ok"] is False
    assert getattr(pay, "notify_link", None) is None


def test_failed_sample_blank_fields_sign_then_wait(monkeypatch):
    monkeypatch.setattr(settings, "rekha_env", "prod")
    monkeypatch.setattr(settings, "ops_token", "ops-secret")
    monkeypatch.setattr(settings, "razorpay_webhook_secret", "whsec")
    payload = _failed_sample()
    with TestClient(app) as client:
        sample = client.get("/webhooks/sample?name=payment_failed")
        assert sample.status_code == 200
        body = sample.json()
        assert body["event"] == "payment.failed"
        signed = client.post("/webhooks/sign", json=body, headers={"X-Ops-Token": "ops-secret"})
        assert signed.status_code == 200
        res = client.post(
            "/webhooks/razorpay?wait=true",
            headers={
                "X-Razorpay-Event-Id": "sim-blank-failed-1",
                "X-Razorpay-Signature": signed.json()["signature"],
            },
            json=body,
        )
        assert res.status_code == 200
        out = res.json()
        assert out["ok"] is True
        result = out["result"]
        assert result["verdict"]["reason_code"] != "PROCESS_ERROR"
        assert result["proposal"]["action"] == "silent_retry_same_instrument"
        assert result["scheduled"] is True
        assert result["verdict"]["effect"] == "ALLOW"
        assert payload["payload"]["payment"]["entity"]["error_reason"] == "insufficient_funds"


def test_failed_sample_when_payments_unavailable(monkeypatch):
    monkeypatch.setattr(settings, "rekha_env", "prod")
    monkeypatch.setattr(settings, "payments_adapter", "razorpay_test")
    monkeypatch.setattr(settings, "razorpay_key_id", "")
    monkeypatch.setattr(settings, "ops_token", "ops-secret")
    monkeypatch.setattr(settings, "razorpay_webhook_secret", "whsec")
    with TestClient(app) as client:
        body = client.get("/webhooks/sample?name=payment_failed").json()
        sig = client.post("/webhooks/sign", json=body, headers={"X-Ops-Token": "ops-secret"}).json()["signature"]
        res = client.post(
            "/webhooks/razorpay?wait=true",
            headers={"X-Razorpay-Event-Id": "sim-blank-unavail-1", "X-Razorpay-Signature": sig},
            json=body,
        )
        assert res.status_code == 200
        result = res.json()["result"]
        assert result["verdict"]["reason_code"] != "PROCESS_ERROR"
        assert result["proposal"]["action"] == "silent_retry_same_instrument"
        assert result["scheduled"] is True


def test_advisor_exception_still_returns_playbook(monkeypatch):
    monkeypatch.setattr(settings, "openai_api_key", "gsk_test")

    def boom(*_a, **_k):
        raise RuntimeError("groq down")

    monkeypatch.setattr("rekha.engine.advise", boom)
    with TestClient(app) as client:
        res = client.post(
            "/webhooks/razorpay?wait=true",
            headers={"X-Razorpay-Event-Id": "sim-adv-boom-1"},
            json=_failed_sample(),
        )
        assert res.status_code == 200
        result = res.json()["result"]
        assert result["proposal"]["action"] == "silent_retry_same_instrument"
        assert result["proposal"]["advisor"]["called"] is True
        assert result["proposal"]["advisor"]["applied"] is False
        assert result["proposal"]["advisor"]["error"] == "RuntimeError"
        assert result["scheduled"] is True


def test_process_crash_is_fail_closed_200(monkeypatch):
    from rekha import api as api_mod

    class Boom:
        def run_case(self, *_a, **_k):
            raise RuntimeError("store down")

    with TestClient(app) as client:
        monkeypatch.setattr(api_mod, "_live_engine", lambda: Boom())
        res = client.post(
            "/webhooks/razorpay?wait=true",
            headers={"X-Razorpay-Event-Id": "sim-process-boom-1"},
            json=_failed_sample(),
        )
        assert res.status_code == 200
        result = res.json()["result"]
        assert result["verdict"]["reason_code"] == "PROCESS_ERROR"
        assert result["blocked"] is True
        assert "RuntimeError" in result["notes"]
        assert any("store down" in str(n) for n in result["notes"])
