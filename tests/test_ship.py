from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from rekha.advisor import advise, filter_proposal
from rekha.api import app
from rekha.cli import cmd_audit, main
from rekha.config import cors_origin_list, settings
from rekha.execute import Executor
from rekha.policy import Verdict
from rekha.razorpay_live import RazorpayLive, assert_test_mode
from rekha.runtime import FLAGS
from rekha.sandbox import FileInbox, RazorpaySandbox
from rekha.store import (
    ApprovalStore,
    CaseStore,
    ConsentStore,
    JobStore,
    PromiseStore,
)


def _verdict() -> Verdict:
    return Verdict(effect="ALLOW", reason_code="TEST", matched_rules=[], policy_version="t", policy_hash="h")


def test_cli_audit_missing(tmp_path, monkeypatch):
    monkeypatch.setattr("rekha.cli.ARTIFACTS_DIR", tmp_path)
    assert cmd_audit(None, False) == 1
    assert main(["audit-verify", "--path", str(tmp_path / "nope.json")]) == 1


def test_cli_audit_ok_and_tamper(tmp_path):
    from rekha.audit import AuditChain

    chain = AuditChain()
    chain.append({"actor": "t", "action": "a", "payload": {}})
    chain.append({"actor": "t", "action": "b", "payload": {}})
    chain.append({"actor": "t", "action": "c", "payload": {}})
    chain.append({"actor": "t", "action": "d", "payload": {}})
    path = tmp_path / "audit.json"
    import json

    path.write_text(json.dumps(chain.rows), encoding="utf-8")
    assert cmd_audit(path, False) == 0
    assert cmd_audit(path, True) == 0


def test_cli_eval_returns_zero():
    assert main(["eval"]) == 0


def test_advise_without_key():
    assert advise({"id": "c1"}, {}) is None
    assert filter_proposal(None) is None
    assert filter_proposal({"action": "not_a_tool"}) is None
    assert filter_proposal({"action": "suppress_and_stop"})["action"] == "suppress_and_stop"


def test_advise_with_mocked_httpx(monkeypatch):
    import httpx

    monkeypatch.setattr(settings, "openai_api_key", "sk-test")
    monkeypatch.setattr(settings, "openai_base_url", "")

    class Resp:
        def raise_for_status(self):
            return None

        def json(self):
            return {"choices": [{"message": {"content": '{"action": "suppress_and_stop"}'}}]}

    monkeypatch.setattr(httpx, "post", MagicMock(return_value=Resp()))
    out = advise({"id": "c1", "amount_paise": 100}, {"class": "C"})
    assert out["action"] == "suppress_and_stop"

    monkeypatch.setattr(httpx, "post", MagicMock(side_effect=RuntimeError("down")))
    assert advise({"id": "c1"}, {}) is None


def test_razorpay_live_adapter(monkeypatch):
    monkeypatch.setattr(settings, "razorpay_key_id", "rzp_test_abc")
    monkeypatch.setattr(settings, "razorpay_key_secret", "sec")
    monkeypatch.setattr(settings, "payment_link_budget", 1)
    client = MagicMock()
    client.payment.fetch.return_value = {"id": "pay"}
    client.order.fetch.return_value = {"id": "ord"}
    client.subscription.fetch.return_value = {"id": "sub"}
    client.invoice.fetch.return_value = {"id": "inv"}
    client.payment_link.fetch.return_value = {"id": "pl"}
    client.invoice.all.return_value = {"items": [{"id": "inv1", "status": "issued"}, {"id": "inv2", "status": "paid"}]}
    client.payment_link.create.return_value = {"id": "pl_new"}
    client.payment_link.notify_by.return_value = {"ok": True}
    client.invoice.create.return_value = {"id": "inv_new"}
    client.invoice.notify_by.return_value = {"ok": True}
    mod = SimpleNamespace(Client=MagicMock(return_value=client))
    monkeypatch.setitem(__import__("sys").modules, "razorpay", mod)
    live = RazorpayLive()
    assert live.fetch_payment("p")["id"] == "pay"
    assert live.fetch_order("o")["id"] == "ord"
    assert live.fetch_subscription("s")["id"] == "sub"
    assert live.fetch_invoice("i")["id"] == "inv"
    assert live.fetch_payment_link("l")["id"] == "pl"
    assert [i["id"] for i in live.list_unpaid_invoices("sub")] == ["inv1"]
    assert live.create_payment_link(amount=100)["id"] == "pl_new"
    with pytest.raises(RuntimeError, match="budget"):
        live.create_payment_link(amount=100)
    assert live.notify_link("pl", "sms")["ok"] is True
    assert live.create_invoice(amount=100)["id"] == "inv_new"
    assert live.notify_invoice("inv", "email")["ok"] is True
    with pytest.raises(RuntimeError, match="sandbox-only"):
        live.mark_paid("payment", "p")
    assert live.retry_payment("pay1")["simulated"] is False
    assert assert_test_mode("rzp_test_x") == "rzp_test_x"


def test_runtime_kill_and_complaints():
    FLAGS.engage_kill()
    assert FLAGS.kill_switch is True
    FLAGS.release_kill()
    assert FLAGS.kill_switch is False
    now = datetime.now(UTC)
    FLAGS.record_complaint(now)
    FLAGS.record_complaint(now)
    assert FLAGS.complaint_throttle(now) is True


def test_cors_list():
    settings.cors_origins = "https://a.com, https://b.com"
    assert cors_origin_list() == ["https://a.com", "https://b.com"]
    settings.cors_origins = "*"


def test_sandbox_fetch_and_invoice():
    psp = RazorpaySandbox(budget=0)
    psp.seed_entity("payment", "pay1", {"id": "pay1", "status": "failed"})
    psp.seed_entity("order", "ord1", {"id": "ord1"})
    psp.seed_entity("subscription", "sub1", {"id": "sub1"})
    psp.seed_entity("invoice", "inv_old", {"id": "inv_old", "status": "issued", "subscription_id": "sub1"})
    assert psp.fetch_payment("pay1")["id"] == "pay1"
    assert psp.fetch_order("ord1")
    assert psp.fetch_subscription("sub1")
    assert psp.fetch_invoice("inv_old")
    inv = psp.create_invoice(amount=500, notes={"case_id": "c1"}, subscription_id="sub1")
    assert psp.notify_invoice(inv["id"], "email")["success"] is True
    assert psp.list_unpaid_invoices("sub1")
    paid = psp.mark_paid("invoice", inv["id"])
    assert paid["status"] == "paid"
    retry = psp.retry_payment("pay1", notes={"attempt_no": "2"})
    assert retry["ok"] is True
    with pytest.raises(ValueError):
        psp.notify_link("missing", "fax")
    link = psp.create_payment_link(amount=100, notes={"case_id": "c2", "attempt_no": "1"})
    assert psp.fetch_payment_link(link["id"])
    with pytest.raises(KeyError):
        psp.notify_link("nope", "sms")
    assert psp.notify_link(link["id"], "sms")["success"] is True


def test_executor_tools():
    psp = RazorpaySandbox(budget=0)
    inbox = FileInbox()
    ex = Executor(psp, inbox)
    case = {
        "id": "case-ex",
        "customer_id": "cust-ex",
        "amount_paise": 129900,
        "contact": "+919800000001",
        "source_refs": {"subscription_id": "sub1", "payment_id": "pay1"},
        "merchant_offer": {"code": "SAVE"},
    }
    v = _verdict()
    assert ex.execute(case, {"action": "not_real"}, v, datetime.now(UTC))["ok"] is False
    assert ex.execute(case, {"action": "suppress_and_stop"}, v, datetime.now(UTC))["ok"] is True
    assert ex.execute(case, {"action": "escalate_to_merchant"}, v, datetime.now(UTC))["ok"] is True
    assert ex.execute(case, {"action": "apply_merchant_offer"}, v, datetime.now(UTC))["ok"] is True
    assert ex.execute({"id": "c2", "customer_id": "x", "amount_paise": 1}, {"action": "apply_merchant_offer"}, v, datetime.now(UTC))[
        "ok"
    ] is False
    ptp = ex.execute(case, {"action": "capture_promise_to_pay", "promised_date": "2026-09-01"}, v, datetime.now(UTC))
    assert ptp["ok"] is True
    case["promise"] = ptp["promise"]
    assert ex.execute(case, {"action": "renegotiate_promise", "promised_date": "2026-09-10"}, v, datetime.now(UTC))["ok"] is True
    assert ex.execute(case, {"action": "send_template_message"}, v, datetime.now(UTC))["reason"] == "template_required"
    retry = ex.execute(case, {"action": "silent_retry_same_instrument"}, v, datetime.now(UTC))
    assert retry["ok"] is True
    inv = ex.execute(case, {"action": "issue_or_notify_invoice", "channel": "email"}, v, datetime.now(UTC))
    assert inv["ok"] is True


def test_stores_consent_jobs_neighbors():
    CaseStore.upsert(
        {
            "id": "case-a",
            "customer_id": "cust-a",
            "amount_paise": 100,
            "loss_class": "payment_failure",
            "source_refs": {"order_id": "ord-a"},
        }
    )
    CaseStore.upsert(
        {
            "id": "case-b",
            "customer_id": "cust-b",
            "amount_paise": 200,
            "loss_class": "payment_failure",
            "source_refs": {"order_id": "ord-b"},
        }
    )
    CaseStore.bump_mandate("case-a", upi=True, nach=True)
    CaseStore.record_touch("case-a", contacted=True, channel="sms", customer_id="cust-a")
    nav = CaseStore.neighbors("case-a")
    assert "prev" in nav and "next" in nav
    ConsentStore.upsert("cust-a", status="GRANTED")
    ConsentStore.withdraw("cust-a")
    row = ConsentStore.get("cust-a")
    assert row is not None
    overlay = ConsentStore.overlay({"customer_id": "cust-a", "consent_status": "GRANTED"})
    assert overlay["consent_status"] in {"REVOKED", "GRANTED", "UNKNOWN"}
    p = PromiseStore.create({"id": "case-a", "customer_id": "cust-a"}, 100, "2026-09-01", {})
    assert PromiseStore.get(p["id"])
    assert PromiseStore.for_case("case-a")
    PromiseStore.update_state(p["id"], "Kept")
    assert PromiseStore.list_live() is not None
    jid = JobStore.schedule("defer", {"id": "case-a"}, datetime.now(UTC) + timedelta(hours=1))
    assert JobStore.get(jid)
    cancelled = JobStore.cancel(jid)
    assert cancelled and cancelled.get("cancelled")
    assert JobStore.cancel(jid)["cancelled"] is False
    assert JobStore.cancel(99999) is None
    ApprovalStore.create(
        {"id": "case-a", "customer_id": "cust-a", "amount_paise": 100},
        {"action": "create_payment_link"},
        {"effect": "REQUIRE_APPROVAL", "reason_code": "X"},
        "ops",
    )
    assert ApprovalStore.pending()
    assert ApprovalStore.list_by_status("all")


def test_api_product_routes():
    with TestClient(app) as client:
        assert client.get("/cases?trap=late_auth").status_code == 200
        assert client.get("/cases?blocked=true").status_code == 200
        assert client.get("/ptp").status_code == 200
        assert client.get("/ledger?attribution=agent").status_code == 200
        assert client.get("/approvals?status=all").status_code == 200
        assert client.get("/kill-switch").status_code == 200
        assert client.get("/complaints/state").status_code == 200
        assert client.get("/customers/nope").status_code == 404
        granted = client.post("/customers/cust-ship/consent", json={"status": "GRANTED"})
        assert granted.status_code == 200
        assert client.get("/customers/cust-ship").status_code == 200
        assert client.post("/eval/run?seed=-1").status_code == 400
        run = client.post("/cases/run", json={"case_id": "does-not-exist-id"})
        assert run.status_code == 404
        assert client.post("/cases/run", json={}).status_code == 400
        assert client.post("/approvals/missing/decide", json={"decision": "reject"}).status_code == 404
        assert client.post("/jobs/999/cancel").status_code == 404
        assert client.post("/batch/ingest", json={"path": "/etc/passwd"}).status_code == 400
        assert client.post("/batch/ingest", json={"path": "packages/fixtures/nope.jsonl"}).status_code == 404
        queued = client.post(
            "/webhooks/razorpay",
            headers={"X-Razorpay-Event-Id": "evt-queued-1"},
            json={"event": "payment.failed", "payload": {"payment": {"entity": {"id": "p", "amount": 100, "status": "failed"}}}},
        )
        assert queued.status_code == 200
        tick = client.post("/scheduler/tick")
        assert tick.status_code == 200
        assert client.get("/cases/c-0001/neighbors").status_code == 200
