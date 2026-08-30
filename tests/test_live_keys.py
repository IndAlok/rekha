import pytest
from rekha.razorpay_live import assert_test_mode


def test_live_keys_forbidden():
    with pytest.raises(RuntimeError, match="live_keys_forbidden"):
        assert_test_mode("rzp_live_not_allowed")


def test_empty_key():
    with pytest.raises(RuntimeError, match="no_razorpay_key"):
        assert_test_mode("")
