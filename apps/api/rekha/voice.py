"""Awaaz. Hinglish voice. Every agent line is compliance-scanned before TTS.
Identity verification is asymmetric. The caller states the secret. The agent
never reads it out. PII-shaped output is redacted while VERIFYING."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from rekha.clocks import as_ist
from rekha.compliance import redact, scan_copy

OPENER = (
    "Namaste, main Asha bol rahi hoon, {merchant} ki automated AI assistant. "
    "Yeh call recorded hai. Kya main {first_name} se baat kar rahi hoon?"
)

VERIFY_PROMPT = "Security ke liye, apne last bill ke last do digit bataiye. Main aapka card number nahi poochungi."

TURN_CAP = 15

DISTRESS = {"lawyer", "suicide", "harass", "police", "don't call", "dnc", "stop calling", "baat nahi"}
ESCALATE_WORDS = {"human", "agent se", "baat karao", "manager", "representative"}
COMPLAINT_WORDS = {"shikayat", "complaint", "harassment"}


@dataclass
class VoiceTurn:
    state: str
    agent: str
    user: str | None = None
    tool: str | None = None


@dataclass
class VoiceSession:
    case_id: str
    turns: list[VoiceTurn] = field(default_factory=list)
    captured_ptp: dict | None = None
    stopped: bool = False
    stop_reason: str | None = None
    verified: bool = False
    compliance_flags: list[str] = field(default_factory=list)


def _safe_line(session: VoiceSession, line: str) -> str:
    """Compliance gate between the script and TTS: scan, then redact. A scan
    fail vetoes the line instead of speaking a redacted version."""
    scan = scan_copy(line, channel="voice")
    if not scan.ok:
        session.compliance_flags.extend(scan.flags)
        session.stopped = True
        session.stop_reason = "COMPLIANCE_VETO"
        return "[blocked]"
    return redact(line)


def _expected_secret(case: dict) -> str:
    return str(case.get("last4") or "")[-2:]


def run_scripted_session(case: dict, user_lines: list[str], now: datetime | None = None) -> VoiceSession:
    session = VoiceSession(case_id=case["id"])
    opener = OPENER.format(
        merchant=case.get("merchant_name", "the merchant"),
        first_name=case.get("first_name", "aap"),
    )
    session.turns.append(VoiceTurn("GREETING", _safe_line(session, opener)))
    if session.stopped:
        return session
    state = "VERIFYING"
    verify_attempts = 0
    for line in user_lines[:TURN_CAP]:
        if session.stopped:
            break
        lowered = line.lower()
        if any(w in lowered for w in DISTRESS):
            session.stopped = True
            session.stop_reason = "DISTRESS_OR_OPT_OUT"
            session.turns.append(VoiceTurn("OPT_OUT", _safe_line(session, "Theek hai, main aapko nahi call karungi. Alvida."), line))
            return session
        if any(w in lowered for w in COMPLAINT_WORDS):
            session.stopped = True
            session.stop_reason = "COMPLAINT"
            session.turns.append(
                VoiceTurn("OPT_OUT", _safe_line(session, "Aapki baat note kar li gayi hai. Hum aapko dobara call nahi karenge."), line)
            )
            return session
        if any(w in lowered for w in ESCALATE_WORDS):
            session.stopped = True
            session.stop_reason = "ESCALATE_HUMAN"
            session.turns.append(VoiceTurn("ESCALATE", _safe_line(session, "Bilkul, main aapko humare team member se connect kar deti hoon."), line))
            return session
        if state == "VERIFYING":
            expected = _expected_secret(case)
            if not expected:
                session.stopped = True
                session.stop_reason = "VERIFY_FAILED"
                session.verified = False
                session.turns.append(
                    VoiceTurn("VERIFYING", _safe_line(session, "Suraksha ke liye main aage baat nahi kar sakti. Dhanyavaad."), line)
                )
                return session
            if expected not in line:
                verify_attempts += 1
                if verify_attempts >= 2:
                    session.stopped = True
                    session.stop_reason = "VERIFY_FAILED"
                    session.turns.append(
                        VoiceTurn("VERIFYING", _safe_line(session, "Suraksha ke liye main aage baat nahi kar sakti. Dhanyavaad."), line)
                    )
                    return session
                session.turns.append(VoiceTurn("VERIFYING", _safe_line(session, VERIFY_PROMPT), line))
                continue
            session.verified = True
            session.turns.append(VoiceTurn("VERIFYING", _safe_line(session, VERIFY_PROMPT), line))
            state = "INTENT"
            continue
        if state == "INTENT":
            try:
                amount_rupees = int(case["amount_paise"]) // 100
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError("amount_paise is required") from exc
            session.turns.append(
                VoiceTurn(
                    "INTENT",
                    _safe_line(session, f"Aapka INR {amount_rupees} pending hai. Kab pay kar paoge?"),
                    line,
                    tool="capture_promise_to_pay" if _is_commitment(lowered) else None,
                )
            )
            if _is_commitment(lowered):
                session.captured_ptp = {
                    "date": _promise_date(lowered, now),
                    "amount_paise": int(case["amount_paise"]),
                }
                state = "CONFIRM"
            else:
                state = "NEGOTIATE"
            continue
        if state in {"NEGOTIATE", "CONFIRM"}:
            session.turns.append(
                VoiceTurn(
                    "CONFIRM",
                    _safe_line(session, "Main aapko ek secure payment link bhej rahi hoon. Yeh Razorpay checkout hai."),
                    line,
                    tool="create_payment_link",
                )
            )
            state = "CLOSE"
            break
    session.turns.append(VoiceTurn("CLOSE", _safe_line(session, "Dhanyavaad. Alvida.")))
    return session


def _is_commitment(lowered: str) -> bool:
    return "kal" in lowered or "tomorrow" in lowered or "parso" in lowered


def _promise_date(lowered: str, now: datetime | None) -> str:
    base = as_ist(now) if now is not None else as_ist(datetime.now(UTC))
    days = 2 if "parso" in lowered else 1
    return (base + timedelta(days=days)).date().isoformat()
