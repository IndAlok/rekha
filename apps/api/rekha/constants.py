"""Single source of truth for regulatory clocks.

Loads packages/policy/constants.yaml once. Every module that needs a
regulated number reads it from here; policy.py folds the file's hash into
policy_hash so an audit row proves which constants were in force.
"""

from __future__ import annotations

import hashlib
from functools import lru_cache

import yaml

from rekha.paths import POLICY_DIR

CONSTANTS_PATH = POLICY_DIR / "constants.yaml"


@lru_cache(maxsize=1)
def _doc() -> dict:
    return yaml.safe_load(CONSTANTS_PATH.read_bytes())


def constants_hash() -> str:
    return hashlib.sha256(CONSTANTS_PATH.read_bytes()).hexdigest()[:16]


def _hour(raw: str) -> int:
    return int(raw.split(":")[0])


def _minute(raw: str) -> int:
    return int(raw.split(":")[1])


def _minutes(raw: str) -> int:
    h, m = raw.split(":")
    return int(h) * 60 + int(m)


def _windows(raw: list) -> list[tuple[int, int]]:
    # Minutes since midnight; a 24:00 end becomes 1440 so the last minute
    # of the day is inside the window.
    return [(_minutes(start), _minutes(end)) for start, end in raw]


# contact window (TRAI x RBI intersection)
CONTACT_WINDOW_START = _hour(_doc()["contact_window"]["default_start"])
CONTACT_WINDOW_END = _hour(_doc()["contact_window"]["default_end"])

# RBI e-mandate framework 2026
AFA_FREE_PAISE = int(_doc()["emandate"]["afa_free_ceiling_paise"])
AFA_1L_CATEGORIES = frozenset(_doc()["emandate"]["afa_free_1lakh_categories"])
AFA_1L_CEILING_PAISE = int(_doc()["emandate"].get("afa_1lakh_ceiling_paise", 10_000_000))
PDN_MIN_HOURS = int(_doc()["emandate"]["pdn_min_hours"])

# NPCI UPI Autopay (grade: secondary. confirm with the PA)
_upi = _doc()["upi_autopay"]
UPI_PEAK_WINDOWS = _windows(_upi["peak_windows_ist"])
UPI_ALLOWED_WINDOWS = _windows(_upi["allowed_windows_ist"])
UPI_TOTAL_ATTEMPTS = int(_upi["attempt_budget"]["original"]) + int(_upi["attempt_budget"]["retries"])

# NACH re-presentation caps
_nach = _doc()["nach"]
NACH_MAX_REPRESENTATIONS = int(_nach["max_representations"])
NACH_MIN_GAP_DAYS = int(_nach["min_gap_days"])

# contact caps
CAPS: dict = dict(_doc()["caps"])

# SMS / template rules
SMS_RULES: dict = dict(_doc()["sms"])
URL_WHITELIST: tuple[str, ...] = tuple(_doc()["sms"]["url_whitelist"])
VARIABLE_MAX_CHARS = int(_doc()["sms"]["variable_max_chars"])
