"""R T C I B recoverability. Class B never reaches the customer."""

from __future__ import annotations

from enum import StrEnum


class Recoverability(StrEnum):
    R = "R"
    T = "T"
    C = "C"
    I = "I"
    B = "B"


RETRIABLE = {
    "bank_technical_error",
    "gateway_technical_error",
    "issuer_technical_error",
    "bank_cutoff_in_progress",
    "bank_not_available",
    "server_error",
    "verification_failed",
    "payment_declined_due_to_high_traffic",
    "request_timed_out",
    "invalid_response_from_gateway",
    "upi_app_technical_error",
    "psp_app_not_available",
    "psp_not_available",
    "authorisation_declined_by_psp",
}

TERMINAL = {
    "card_number_invalid",
    "incorrect_card_details",
    "bank_account_invalid",
    "beneficiary_account_does_not_exist",
    "compliance_violation",
    "order_already_paid",
    "duplicate_rrn_found",
    "duplicate_request",
    "payment_amount_tampered",
    "merchant_not_activated",
    "live_mode_not_enabled",
    "record_not_found",
}

CUSTOMER_ACTION = {
    "insufficient_funds",
    "incorrect_otp",
    "invalid_otp",
    "authentication_failed",
    "otp_expired",
    "otp_attempts_exceeded",
    "incorrect_cvv",
    "incorrect_pin",
    "incorrect_atm_pin",
    "pin_attempts_exceeded",
    "pin_not_set",
    "payment_cancelled",
    "payment_collect_request_expired",
    "invalid_vpa",
    "user_not_registered_for_netbanking",
    "transaction_daily_limit_exceeded",
    "transaction_daily_count_exceeded",
    "transaction_frequency_limit_exceeded",
    "transaction_limit_exceeded",
    "reqauth_mandate_not_acknowledged",
    "funds_blocked_by_mandate",
    "payment_pending_approval",
    "credit_limit_exceeded",
    "mcc_amount_limit_exceeded",
}

INSTRUMENT_CHANGE = {
    "card_expired",
    "debit_instrument_blocked",
    "debit_instrument_inactive",
    "card_declined",
    "payment_declined",
    "debit_declined",
    "card_not_enrolled",
    "card_type_invalid",
    "card_disabled_for_online_payments",
    "payment_risk_check_failed",
    "transaction_on_vpa_restricted",
    "psp_app_not_supported",
    "psp_not_registered",
    "upi_autopay_not_supported_on_psp",
    "mandate_cancelled",
    "credit_not_permitted",
    "user_not_eligible",
    "vpa_resolution_failed",
}

MERCHANT_FIX = {
    "input_validation_failed",
    "invalid_order_id",
    "order_amount_mismatch",
    "order_payment_method_mismatch",
    "invalid_amount",
    "invalid_currency",
    "invalid_request",
    "invalid_email",
    "invalid_mobile_number",
    "mobile_number_invalid",
    "bank_not_enabled",
    "card_network_not_enabled",
    "payment_method_not_enabled",
    "upi_collect_not_enabled",
    "upi_intent_not_enabled",
    "recurring_payment_not_enabled",
    "collect_on_mcc_blocked",
    "capture_failed",
}

RECONCILE_FIRST = {
    "deemed_transaction",
    "payment_pending",
    "collect_request_pending",
    "duplicate_rrn",
    "duplicate_rrn_found",
}

# Absolute do-not-contact set. Overrides every other rule; any outreach is a
# serious harm event (NACH 60/69 = deceased / insolvent; U16_* = NPCI risk
# blocks; fraud blocks escalate the customer's risk profile on retry).
HARD_DNC_EXACT = {"nach_60", "nach_69", "customer_insolvent", "customer_deceased"}
HARD_DNC_PREFIXES = ("u16",)


def hard_do_not_contact(reason: str | None) -> bool:
    r = (reason or "").strip().lower()
    return r in HARD_DNC_EXACT or r.startswith(HARD_DNC_PREFIXES)

SOURCE_TO_CLASS = {
    "gateway": Recoverability.R,
    "razorpay": Recoverability.R,
    "internal": Recoverability.R,
    "network": Recoverability.R,
    "issuer_bank": Recoverability.R,
    "bank": Recoverability.R,
    "customer": Recoverability.C,
    "business": Recoverability.B,
}

# Reasons whose class depends on error_source: gateway-side transient vs
# customer-side behaviour. Anything else maps via SOURCE_TO_CLASS.
AMBIGUOUS_REASONS = {"payment_failed", "payment_timed_out", "request_timed_out"}


def classify(reason: str | None, source: str | None = None) -> Recoverability:
    reason = (reason or "").strip().lower()
    if reason in MERCHANT_FIX:
        return Recoverability.B
    if reason in TERMINAL:
        return Recoverability.T
    if reason in INSTRUMENT_CHANGE:
        return Recoverability.I
    if reason in CUSTOMER_ACTION:
        return Recoverability.C
    if reason in RETRIABLE or reason in RECONCILE_FIRST:
        return Recoverability.R
    if reason in AMBIGUOUS_REASONS or not reason:
        src = (source or "").lower()
        if not src:
            # Undiagnosed failure: fail safe. silent retry path, never outreach.
            return Recoverability.R
        return SOURCE_TO_CLASS.get(src, Recoverability.R)
    if source:
        return SOURCE_TO_CLASS.get(source.lower(), Recoverability.R)
    return Recoverability.R


def needs_reconcile_first(reason: str | None) -> bool:
    return (reason or "") in RECONCILE_FIRST


# Mastercard Merchant Advice Codes. MAC 03 ("do not try again") and MAC 21
# (payment cancelled / stop recurring) are absolute stops that override every
# other retry rule; MAC 24-30 hand the agent network-authoritative retry
# intervals in hours.
MAC_ABSOLUTE_STOP = {"MAC03", "MAC21"}
MAC_RETRY_HOURS = {"MAC24": 1, "MAC25": 24, "MAC26": 48, "MAC27": 96, "MAC28": 144, "MAC29": 192, "MAC30": 240}


def mac_forbidden(mac: str | None) -> bool:
    return (mac or "").upper().replace(" ", "") in MAC_ABSOLUTE_STOP


def mac_retry_hours(mac: str | None) -> int | None:
    return MAC_RETRY_HOURS.get((mac or "").upper().replace(" ", ""))
