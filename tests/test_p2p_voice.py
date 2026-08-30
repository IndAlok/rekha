from datetime import datetime
from zoneinfo import ZoneInfo

from rekha.p2p import PromiseToPay, evaluate_promise, freeze_active, renegotiate
from rekha.voice import run_scripted_session

IST = ZoneInfo("Asia/Kolkata")


def test_ptp_freeze_and_breach():
    p = PromiseToPay("p1", "cust", "c1", 10000, "2026-08-25")
    assert freeze_active(p, datetime(2026, 8, 22, 11, tzinfo=IST))
    # Inside the +2 day grace the promise is neither broken nor chaseable.
    not_yet = evaluate_promise(p, 0, "2026-08-26")
    assert not_yet.state != "Broken"
    broken = evaluate_promise(p, 0, "2026-08-28")
    assert broken.state == "Broken"


def test_renegotiate_does_not_mutate_amount_in_place():
    old = PromiseToPay("p1", "cust", "c1", 10000, "2026-08-25")
    new = renegotiate(old, "2026-09-01", 8000, "p2")
    assert old.state == "Renegotiated"
    assert new.parent_promise_id == "p1"
    assert new.promised_amount_paise == 8000


def test_voice_distress_stops():
    session = run_scripted_session(
        {"id": "c1", "merchant_name": "NoonCart", "first_name": "Riya", "amount_paise": 100000},
        ["don't call me"],
    )
    assert session.stopped
    assert session.stop_reason == "DISTRESS_OR_OPT_OUT"
