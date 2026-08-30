from rekha.compliance import scan_copy
from rekha.templates import render


def test_criminal_lexicon():
    scan = scan_copy("We will file a section 138 case if you do not pay")
    assert not scan.ok
    assert any("CRIMINAL" in f for f in scan.flags)


def test_dark_pattern():
    scan = scan_copy("Last chance! Expires in 1 hour")
    assert not scan.ok


def test_coupon_on_sms():
    scan = scan_copy("Pay now and get 10% off https://rzp.io/i/x", channel="sms")
    assert not scan.ok
    assert any("PROMO" in f for f in scan.flags)


def test_template_slot_limit():
    try:
        render("svc_pay_link_sms", {"amount": "100", "ref": "x" * 40, "url": "https://rzp.io/i/ab"})
        raise AssertionError("expected slot overflow")
    except ValueError as exc:
        assert "30" in str(exc)


def test_url_whitelist():
    try:
        render("svc_pay_link_sms", {"amount": "100", "ref": "inv1", "url": "https://bit.ly/evil"})
        raise AssertionError("expected whitelist miss")
    except ValueError as exc:
        assert "whitelist" in str(exc)
