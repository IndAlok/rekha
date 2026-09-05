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


def test_webhook_unpaid_when_live_fetch_fails():
    class Boom:
        def fetch_payment(self, _id):
            raise RuntimeError("timeout")

        def fetch_order(self, _id):
            raise RuntimeError("timeout")

    guard = ReconciliationGuard(Boom())
    result = guard.check(
        {
            "source_refs": {"payment_id": "pay_demo_failed", "order_id": "order_demo"},
            "live_statuses": {"payment": "failed"},
        }
    )
    assert result.unknown is False
    assert result.already_paid is False
    assert result.live_status == "unpaid"


def test_already_paid_flag():
    result = ReconciliationGuard(RazorpaySandbox()).check({"already_paid": True})
    assert result.already_paid is True
    assert result.source == "case_flag"


def test_webhook_paid_when_fetch_fails():
    class Boom:
        def fetch_payment(self, _id):
            raise RuntimeError("timeout")

    result = ReconciliationGuard(Boom()).check(
        {"source_refs": {"payment_id": "pay_late"}, "live_statuses": {"payment": "authorized"}}
    )
    assert result.already_paid is True
    assert result.source == "payment_webhook"


def test_recon_outer_guard_on_bad_refs():
    result = ReconciliationGuard(RazorpaySandbox()).check({"source_refs": "not-a-dict"})
    assert result.unknown is True
    assert result.source == "recon_error"


def test_fetch_coerces_mapping_and_rejects_junk():
    class Mapping:
        def keys(self):
            return ["status"]

        def __getitem__(self, key):
            return "failed"

    class Junk:
        pass

    class Adapter:
        def fetch_payment(self, pid):
            return Mapping() if pid == "ok" else Junk()

    guard = ReconciliationGuard(Adapter())
    ok = guard.check({"source_refs": {"payment_id": "ok"}})
    assert ok.already_paid is False
    bad = guard.check({"source_refs": {"payment_id": "bad"}})
    assert bad.unknown is True
