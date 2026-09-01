from rekha.recon import ReconciliationGuard
from rekha.sandbox import RazorpaySandbox


def test_late_auth_stops_outreach():
    psp = RazorpaySandbox()
    psp.seed_entity("payment", "pay_late", {"id": "pay_late", "status": "authorized"})
    guard = ReconciliationGuard(psp)
    result = guard.check({"source_refs": {"payment_id": "pay_late"}})
    assert result.already_paid
    assert result.live_status == "authorized"


def test_unpaid_continues():
    psp = RazorpaySandbox()
    psp.seed_entity("payment", "pay_fail", {"id": "pay_fail", "status": "failed"})
    guard = ReconciliationGuard(psp)
    result = guard.check({"source_refs": {"payment_id": "pay_fail"}})
    assert not result.already_paid
