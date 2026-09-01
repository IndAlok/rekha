import json

from rekha.ingest import Inbox, event_to_case, verify_webhook_signature


def test_hmac_roundtrip():
    body = b'{"event":"payment.failed"}'
    import hashlib
    import hmac

    secret = "whsec_test"
    sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    assert verify_webhook_signature(body, sig, secret)
    assert not verify_webhook_signature(body, "deadbeef", secret)


def test_event_id_dedupe():
    inbox = Inbox()
    _, first = inbox.accept("evt_1", "payment.failed", {"x": 1})
    _, second = inbox.accept("evt_1", "payment.failed", {"x": 1})
    assert first and not second


def test_event_to_case_maps_error():
    raw = json.loads(
        '{"event":"payment.failed","payload":{"payment":{"entity":{"id":"pay_1","amount":100,"error_reason":"insufficient_funds","error_source":"customer","entity":"payment"}}}}'
    )
    case = event_to_case({"event_id": "e1", "event_type": raw["event"], "payload": raw["payload"]})
    assert case["error_reason"] == "insufficient_funds"
    assert case["amount_paise"] == 100
