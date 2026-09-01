import pytest
from rekha.idempotency import receipt
from rekha.sandbox import RazorpaySandbox


def test_payment_link_budget():
    psp = RazorpaySandbox(budget=2)
    psp.create_payment_link(amount=100, notes={"case_id": "a", "attempt_no": "1"})
    psp.create_payment_link(amount=100, notes={"case_id": "b", "attempt_no": "1"})
    with pytest.raises(RuntimeError, match="budget"):
        psp.create_payment_link(amount=100, notes={"case_id": "c", "attempt_no": "1"})


def test_link_idempotent_receipt():
    psp = RazorpaySandbox()
    notes = {"case_id": "c1", "attempt_no": "1"}
    ref = receipt(case_id="c1", attempt_no=1)
    a = psp.create_payment_link(amount=100, notes=notes, reference_id=ref)
    b = psp.create_payment_link(amount=100, notes=notes, reference_id=ref)
    assert a["id"] == b["id"]
    assert psp.created_links == 1


def test_upi_link_rejects_partial():
    psp = RazorpaySandbox()
    with pytest.raises(ValueError):
        psp.create_payment_link(amount=100, notes={"case_id": "x"}, upi_link=True, accept_partial=True)
