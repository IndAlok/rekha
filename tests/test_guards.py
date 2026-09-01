from rekha.config import cors_origin_list
from rekha.ingest import event_to_case, verify_webhook_signature, webhook_hmac
from rekha.paths import POLICY_DIR, REPO_ROOT


def test_repo_root_finds_policy():
    assert POLICY_DIR.is_dir()
    assert (REPO_ROOT / "packages" / "policy" / "rules.yaml").is_file()
    assert (REPO_ROOT / "packages" / "policy" / "constants.yaml").is_file()


def test_cors_star():
    assert cors_origin_list() == ["*"]


def test_webhook_secret_empty_allows_in_dev():
    assert verify_webhook_signature(b"{}", "", secret="") is True


def test_webhook_hmac_matches_verify():
    sig = webhook_hmac(b'{"event":"payment.failed"}', "sekrit")
    assert len(sig) == 64
    assert verify_webhook_signature(b'{"event":"payment.failed"}', sig, secret="sekrit") is True
    assert verify_webhook_signature(b'{"event":"payment.failed"}', sig, secret="other") is False
    assert verify_webhook_signature(b"{}", "", secret="sekrit") is False


def test_event_to_case_bad_amount():
    case = event_to_case({"event_id": "e1", "payload": {"amount": "nope"}})
    assert case["amount_paise"] == 0
    assert case["contacts_last_7d"] == 0
