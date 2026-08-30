from datetime import datetime
from zoneinfo import ZoneInfo

from rekha.clocks import in_contact_window, in_upi_peak, next_upi_offpeak

IST = ZoneInfo("Asia/Kolkata")


def test_contact_window():
    assert in_contact_window(datetime(2026, 8, 22, 11, 0, tzinfo=IST))
    assert not in_contact_window(datetime(2026, 8, 22, 19, 1, tzinfo=IST))
    assert not in_contact_window(datetime(2026, 8, 22, 20, 59, tzinfo=IST))


def test_upi_peak_2059_vs_2131():
    peak = datetime(2026, 8, 22, 20, 59, tzinfo=IST)
    off = datetime(2026, 8, 22, 21, 31, tzinfo=IST)
    assert in_upi_peak(peak)
    assert not in_upi_peak(off)
    nxt = next_upi_offpeak(peak)
    assert nxt.hour == 21 and nxt.minute == 30
