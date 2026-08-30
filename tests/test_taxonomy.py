from rekha.taxonomy import Recoverability, classify, needs_reconcile_first


def test_class_b_never_customer():
    assert classify("payment_method_not_enabled", "business") is Recoverability.B
    assert classify("order_amount_mismatch") is Recoverability.B


def test_iff_is_customer():
    assert classify("insufficient_funds", "customer") is Recoverability.C


def test_deemed_reconcile_first():
    assert classify("deemed_transaction") is Recoverability.R
    assert needs_reconcile_first("deemed_transaction")


def test_hard_decline_terminal():
    assert classify("card_number_invalid") is Recoverability.T


def test_instrument():
    assert classify("card_expired") is Recoverability.I
    assert classify("mandate_cancelled") is Recoverability.I


def test_sparse_payment_failed_uses_source():
    assert classify("payment_failed", "gateway") is Recoverability.R
    assert classify("payment_failed", "customer") is Recoverability.C
