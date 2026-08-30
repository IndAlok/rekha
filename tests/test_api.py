from fastapi.testclient import TestClient
from rekha.api import app


def test_root_health_and_status():
    with TestClient(app) as client:
        root = client.get("/")
        assert root.status_code == 200
        assert root.json()["name"] == "rekha"
        health = client.get("/health")
        assert health.status_code == 200
        assert health.json()["ok"] is True
        status = client.get("/status")
        assert status.status_code == 200
        body = status.json()
        assert body["ok"] is True
        assert body["eval_ready"] is True
        assert "scheduler" in body
        assert "live_audit_rows" in body


def test_eval_latest_after_boot():
    with TestClient(app) as client:
        report = client.get("/eval/latest")
        assert report.status_code == 200
        body = report.json()
        assert body["n"] == 200
        assert body["invariants_passed"] is True


def test_webhook_sample_authorized():
    with TestClient(app) as client:
        res = client.get("/webhooks/sample?name=payment_authorized")
        assert res.status_code == 200
        body = res.json()
        assert body.get("event") == "payment.authorized" or "authorized" in str(body).lower()


def test_unknown_case():
    with TestClient(app) as client:
        res = client.get("/cases/does-not-exist")
        assert res.status_code == 404
        assert res.json()["detail"]["code"] == "CASE_NOT_FOUND"


def test_webhook_sample_unknown():
    with TestClient(app) as client:
        res = client.get("/webhooks/sample?name=not_a_fixture")
        assert res.status_code == 404
        assert res.json()["detail"]["code"] == "SAMPLE_NOT_FOUND"


def test_webhook_sample_cart_abandoned():
    with TestClient(app) as client:
        res = client.get("/webhooks/sample?name=cart_abandoned")
        assert res.status_code == 200
        assert "event" in res.json()


def test_webhook_recent_and_live_case_lookup():
    with TestClient(app) as client:
        sent = client.post(
            "/webhooks/razorpay?wait=true",
            headers={"X-Razorpay-Event-Id": "evt-recent-live-1"},
            json={
                "event": "payment.failed",
                "payload": {
                    "customer": {"id": "cust-live-ui", "consent": True},
                    "payment": {
                        "entity": {
                            "id": "pay-live-ui",
                            "entity": "payment",
                            "status": "failed",
                            "amount": 77700,
                            "order_id": "order-live-ui",
                            "error_reason": "insufficient_funds",
                            "error_source": "customer",
                        }
                    },
                },
            },
        )
        assert sent.status_code == 200
        case_id = sent.json()["result"]["case_id"]
        recent = client.get("/webhooks/recent?limit=15")
        assert recent.status_code == 200
        ids = [r["event_id"] for r in recent.json()["rows"]]
        assert "evt-recent-live-1" in ids
        got = client.get(f"/cases/{case_id}")
        assert got.status_code == 200
        body = got.json()
        assert body["case_id"] == case_id
        assert body.get("source") == "live"
        assert body["amount_paise"] == 77700


def test_webhook_unsigned_when_secret_empty():
    with TestClient(app) as client:
        res = client.post(
            "/webhooks/razorpay",
            headers={"X-Razorpay-Event-Id": "evt-api-test-1"},
            json={
                "event": "payment.failed",
                "payload": {
                    "payment": {
                        "entity": {
                            "id": "pay_api_test",
                            "entity": "payment",
                            "amount": 129900,
                            "error_reason": "insufficient_funds",
                            "customer_id": "cust_api",
                        }
                    }
                },
            },
        )
        assert res.status_code == 200
        body = res.json()
        assert body["ok"] is True
        assert body["event_id"] == "evt-api-test-1"
        again = client.post(
            "/webhooks/razorpay",
            headers={"X-Razorpay-Event-Id": "evt-api-test-1"},
            json={"event": "payment.failed"},
        )
        assert again.status_code == 200
        assert again.json()["deduped"] is True


def test_webhook_rejects_non_object():
    with TestClient(app) as client:
        res = client.post(
            "/webhooks/razorpay",
            content=b"[1,2]",
            headers={"content-type": "application/json"},
        )
        assert res.status_code == 400
        assert res.json()["detail"]["code"] == "BAD_JSON"


def test_batch_path_stays_in_repo():
    with TestClient(app) as client:
        res = client.post("/batch/ingest", json={"path": "/etc/passwd"})
        assert res.status_code == 400
        assert res.json()["detail"]["code"] == "PATH_DENIED"


def test_kill_switch_roundtrip():
    with TestClient(app) as client:
        on = client.post("/kill-switch", json={"engaged": True})
        assert on.status_code == 200
        assert on.json()["kill_switch"] is True
        off = client.post("/kill-switch", json={"engaged": False})
        assert off.json()["kill_switch"] is False


def test_webhook_case_comes_out_right():
    """The full envelope must unwrap: real refs, real amount, real consent . 
    not a garbage fallback case (regression for the double-nesting bug)."""
    with TestClient(app) as client:
        res = client.post(
            "/webhooks/razorpay?wait=true",
            headers={"X-Razorpay-Event-Id": "evt-envelope-1"},
            json={
                "event": "payment.failed",
                "payload": {
                    "customer": {"id": "cust-env", "consent": True},
                    "payment": {
                        "entity": {
                            "id": "pay-env",
                            "entity": "payment",
                            "status": "failed",
                            "amount": 129900,
                            "order_id": "order-env",
                            "error_reason": "bank_technical_error",
                            "error_source": "gateway",
                        }
                    },
                },
            },
        )
        assert res.status_code == 200
        result = res.json()["result"]
        assert result["amount_paise"] == 129900
        assert result["case_id"] == "case-order-order-env"
        assert result["verdict"]["effect"] == "ALLOW"
        assert result["executed"] is True
        # Live recovery is attributed later by the recovery-event/ledger path
        # (see test_recovery_events.py), never inline on the failure case.
