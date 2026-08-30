from __future__ import annotations

import re
from dataclasses import dataclass

PAN_RE = re.compile(r"\b[A-Z]{5}[0-9]{4}[A-Z]\b")
CARD_RE = re.compile(r"\b\d[\d -]{11,17}\d\b")

# Phrases matched on word boundaries so "confirm" never trips "fir" and
# "ibecko" never trips "ibc".
CRIMINAL_LEXICON = [
    "arrest",
    "police",
    "jail",
    "prison",
    "cheque bounce",
    "cheque-bounce",
    "section 138",
    "s.138",
    "s138",
    "ibc",
    "insolvency",
    "criminal",
    "fir",
    "employer",
    "your family",
    "aapke ghar",
    "giraftar",
    "police complaint",
    "court case",
]

DARK_PATTERNS = [
    "last chance",
    "expires in 24",
    "expires in 1 hour",
    "only 2 left",
    "act now or lose",
    "we will take legal action",
    "you should be ashamed",
    "don't be irresponsible",
    "hurry",
    "limited slots",
]

PROMO_LEXICON = [
    "10% off",
    "discount",
    "coupon",
    "cashback",
    "save now",
    "offer expires",
    "free gift",
]


def _phrase_pattern(phrase: str) -> re.Pattern[str]:
    return re.compile(r"(?<![\w])" + re.escape(phrase) + r"(?![\w])", re.IGNORECASE)


_CRIMINAL_PATTERNS = [(p, _phrase_pattern(p)) for p in CRIMINAL_LEXICON]
_DARK_PATTERNS = [(p, _phrase_pattern(p)) for p in DARK_PATTERNS]
_PROMO_PATTERNS = [(p, _phrase_pattern(p)) for p in PROMO_LEXICON]


@dataclass
class ScanResult:
    ok: bool
    flags: list[str]


def scan_copy(text: str, *, offer_expires_is_real: bool = False, channel: str = "email") -> ScanResult:
    flags: list[str] = []
    if PAN_RE.search(text):
        flags.append("PAN_LEAK")
    if CARD_RE.search(text):
        # PAN-shaped digit runs are blocked outright. "Card ending 4242" is
        # safe because last4 sits far below the 13-digit floor.
        flags.append("PAN_SHAPED_DIGITS")
    for phrase, pattern in _CRIMINAL_PATTERNS:
        if pattern.search(text):
            flags.append(f"CRIMINAL_LEXICON:{phrase}")
    for phrase, pattern in _DARK_PATTERNS:
        if pattern.search(text):
            if phrase.startswith("expires") and offer_expires_is_real:
                continue
            flags.append(f"DARK_PATTERN:{phrase}")
    if channel == "sms":
        for phrase, pattern in _PROMO_PATTERNS:
            if pattern.search(text):
                flags.append(f"PROMO_ON_SERVICE_SMS:{phrase}")
    return ScanResult(ok=not flags, flags=flags)


def redact(text: str) -> str:
    text = PAN_RE.sub("[PAN_REDACTED]", text)
    return CARD_RE.sub("[CARD_REDACTED]", text)


def identity_ok(text: str) -> bool:
    lowered = text.lower()
    return "automated" in lowered or "assistant" in lowered
