from __future__ import annotations

from datetime import datetime, timedelta

from rekha.advisor import CLOSED_TOOLS
from rekha.clocks import as_ist
from rekha.compliance import scan_copy
from rekha.constants import CAPS
from rekha.idempotency import IdempotencyStore, receipt, tool_key
from rekha.reservations import ContactReservation, Slot
from rekha.templates import TEMPLATES, render

CUSTOMER_CHANNELS = {"sms", "whatsapp", "email", "voice"}

SAFE_INTERNAL_ACTIONS = {
    "suppress_and_stop",
    "alert_engineering",
    "refuse_legal_step",
    "escalate_to_merchant",
    "recommend_service_hold",
    "capture_promise_to_pay",
    "renegotiate_promise",
}

MONEY_ACTIONS = {
    "silent_retry_same_instrument",
    "schedule_mandate_presentment",
    "create_payment_link",
    "issue_or_notify_invoice",
    "send_subscription_update_method_link",
}

INTERNAL_NOOP_OK = {
    "suppress_and_stop",
    "alert_engineering",
    "refuse_legal_step",
    "recommend_service_hold",
}


class Executor:
    def __init__(self, payments, comms, *, reservations: ContactReservation | None = None) -> None:
        self.payments = payments
        self.comms = comms
        self.reservations = reservations or ContactReservation()
        self.idem = IdempotencyStore()
        self.sends: list[dict] = []
        self.persist_cases = None

    def execute(self, case: dict, proposal: dict, verdict, now) -> dict:
        action = proposal.get("action")
        channel = proposal.get("channel")
        if action in {"silent_retry_same_instrument", "schedule_mandate_presentment"}:
            channel = None

        if action not in CLOSED_TOOLS:
            return {"ok": False, "reason": "tool_not_in_allowlist", "action": action}

        cap_reason = self._channel_cap(case, channel, now)
        if cap_reason:
            return {"ok": False, "reason": cap_reason, "action": action}

        attempt = int(case.get("touches_this_case") or 0) + 1
        notes = {
            "case_id": case["id"],
            "attempt_no": str(attempt),
            "policy_version": verdict.policy_version,
        }
        key = tool_key(tool=action, case_id=case["id"], attempt_no=attempt, policy_version=verdict.policy_version)

        def _run() -> dict:
            slot = None
            if channel in CUSTOMER_CHANNELS:
                bucket = as_ist(now).date().isoformat()
                slot = Slot(case["customer_id"], bucket, channel)
                if not self.reservations.reserve(slot):
                    return {"ok": False, "reason": "slot_already_reserved", "action": action}
            try:
                result = self._dispatch(case, proposal, verdict, notes, attempt, channel)
                if result.get("ok") and slot is not None and hasattr(self.reservations, "confirm"):
                    self.reservations.confirm(slot)
                elif not result.get("ok") and slot is not None:
                    self.reservations.release(slot)
                return result
            except Exception:
                if slot is not None:
                    self.reservations.release(slot)
                raise

        result, first = self.idem.claim(key, _run)
        result = dict(result)
        result["first_execution"] = first
        return result

    def _channel_cap(self, case: dict, channel: str | None, now) -> str | None:
        if channel not in CUSTOMER_CHANNELS:
            return None
        counter = getattr(self.persist_cases, "count_contacts", None)
        if counter is None:
            return None
        cid = case.get("customer_id") or "cust_unknown"
        local = as_ist(now)
        day_start = local.replace(hour=0, minute=0, second=0, microsecond=0)
        week_start = day_start - timedelta(days=local.weekday())
        if channel == "voice" and counter(cid, since=day_start, channel="voice") >= int(CAPS.get("max_voice_per_day", 1)):
            return "cap_voice_per_day"
        if channel == "sms" and counter(cid, since=day_start, channel="sms") >= int(CAPS.get("max_sms_per_day", 2)):
            return "cap_sms_per_day"
        if channel == "whatsapp" and counter(cid, since=week_start, channel="whatsapp") >= int(
            CAPS.get("max_whatsapp_per_week", 3)
        ):
            return "cap_whatsapp_per_week"
        if counter(cid, since=week_start) >= int(CAPS.get("max_cross_channel_per_week", 3)):
            return "cap_cross_channel_per_week"
        return None

    def _dispatch(self, case: dict, proposal: dict, verdict, notes: dict, attempt: int, channel: str | None) -> dict:
        action = proposal.get("action")
        if action in INTERNAL_NOOP_OK:
            return {"ok": True, "action": action, "channel": channel, "notes": notes, "internal": True}
        if action == "escalate_to_merchant":
            self.comms.send(
                channel="internal",
                to=case.get("merchant_id") or "merchant",
                template_id="escalate_internal",
                body=f"Escalate {case['id']} amount {case.get('amount_paise')}",
                case_id=case["id"],
            )
            return {"ok": True, "action": action, "channel": "internal", "notes": notes}
        if action == "apply_merchant_offer":
            offer = case.get("merchant_offer")
            if not offer:
                return {"ok": False, "reason": "no_merchant_offer", "action": action}
            return {"ok": True, "action": action, "offer": offer, "notes": notes}
        if action == "capture_promise_to_pay":
            return self._capture_ptp(case, proposal, notes)
        if action == "renegotiate_promise":
            return self._renegotiate_ptp(case, proposal, notes)

        link = None
        body = None
        if action in {"create_payment_link", "send_subscription_update_method_link"}:
            link = self.payments.create_payment_link(
                amount=int(case["amount_paise"]),
                currency=case.get("currency", "INR"),
                notes=notes,
                reference_id=receipt(case_id=case["id"], attempt_no=attempt),
                accept_partial=bool(proposal.get("accept_partial")),
                upi_link=bool(proposal.get("upi_link")),
            )
        if action == "issue_or_notify_invoice":
            sub_id = (case.get("source_refs") or {}).get("subscription_id")
            unpaid = []
            if sub_id and hasattr(self.payments, "list_unpaid_invoices"):
                unpaid = self.payments.list_unpaid_invoices(sub_id)
            link = self.payments.create_invoice(
                amount=int(case["amount_paise"]),
                notes=notes,
                subscription_id=sub_id,
            )
            medium = "email" if channel in {None, "internal", "email"} else channel
            if hasattr(self.payments, "notify_invoice"):
                self.payments.notify_invoice(link["id"], medium if medium in {"sms", "email"} else "email")
                for inv in unpaid:
                    if inv.get("id") and inv["id"] != link.get("id"):
                        self.payments.notify_invoice(inv["id"], "email")
        if action in {"silent_retry_same_instrument", "schedule_mandate_presentment"}:
            guard = getattr(self, "charge_guard", None)
            if guard is not None and not guard(case["id"], attempt, int(case.get("amount_paise") or 0)):
                return {"ok": False, "reason": "double_charge_guard", "action": action}
            if action == "silent_retry_same_instrument":
                return self._silent_retry(case, notes, channel)
            return {
                "ok": True,
                "action": action,
                "channel": None,
                "notes": notes,
                "silent": True,
            }
        template_id = proposal.get("template_id")
        if template_id and template_id in TEMPLATES and channel in CUSTOMER_CHANNELS:
            values = {
                "amount": str(int(case["amount_paise"]) // 100),
                "ref": case["id"][:20],
                "url": (link or {}).get("short_url", "https://rzp.io/i/demo"),
                "merchant": (case.get("merchant_name") or "Merchant")[:30],
                "issuer": (case.get("issuer") or "card")[:30],
                "last4": str(case.get("last4") or "4242"),
                "date": (proposal.get("send_after") or case.get("due_date") or "soon")[:30],
                "interest": str(proposal.get("msmed_interest_inr") or "")[:30],
            }
            body, scan = render(template_id, values, channel=channel)
            if not scan.ok:
                return {"ok": False, "reason": "compliance_veto", "flags": scan.flags, "action": action}
            extra = case.get("llm_draft") or ""
            if extra:
                extra_scan = scan_copy(extra, channel=channel)
                if not extra_scan.ok:
                    extra = ""
            self.comms.send(
                channel=channel,
                to=case.get("contact") or case["customer_id"],
                template_id=template_id,
                body=body,
                case_id=case["id"],
            )
            self.sends.append({"case_id": case["id"], "channel": channel, "template_id": template_id, "body": body})
            if link and channel in {"sms", "email"} and hasattr(self.payments, "notify_link"):
                self.payments.notify_link(link["id"], "sms" if channel == "sms" else "email")
        elif action == "send_template_message" and not template_id:
            return {"ok": False, "reason": "template_required", "action": action}
        return {
            "ok": True,
            "action": action,
            "channel": channel,
            "link": link,
            "body": body,
            "notes": notes,
        }

    def _silent_retry(self, case: dict, notes: dict, channel: str | None) -> dict:
        retry = getattr(self.payments, "retry_payment", None)
        payment_id = (case.get("source_refs") or {}).get("payment_id")
        if callable(retry) and payment_id:
            out = retry(payment_id, notes=notes)
            return {
                "ok": bool(out.get("ok", True)),
                "action": "silent_retry_same_instrument",
                "channel": channel,
                "notes": notes,
                "simulated": bool(out.get("simulated", False)),
                "retry": out,
            }
        return {
            "ok": True,
            "action": "silent_retry_same_instrument",
            "channel": channel,
            "notes": notes,
            "simulated": True,
            "reason": "adapter_has_no_retry",
        }

    def _capture_ptp(self, case: dict, proposal: dict, notes: dict) -> dict:
        promised_date = str(proposal.get("promised_date") or case.get("promised_date") or "")
        amount = int(proposal.get("promised_amount_paise") or case.get("amount_paise") or 0)
        if not promised_date:
            from datetime import UTC as _UTC

            promised_date = (datetime.now(_UTC).date() + timedelta(days=1)).isoformat()
        row = None
        if self.persist_cases is not None:
            from rekha.store import PromiseStore

            row = PromiseStore.create(case, amount, promised_date, {"channel": proposal.get("channel")})
        ptp = {
            "id": (row or {}).get("id"),
            "promised_date": promised_date,
            "promised_amount_paise": amount,
            "state": "Open",
        }
        case["promise"] = ptp
        case["ptp_active"] = True
        return {"ok": True, "action": "capture_promise_to_pay", "notes": notes, "promise": ptp}

    def _renegotiate_ptp(self, case: dict, proposal: dict, notes: dict) -> dict:
        existing = case.get("promise") or {}
        new_date = str(proposal.get("promised_date") or existing.get("promised_date") or "")
        new_amount = int(proposal.get("promised_amount_paise") or existing.get("promised_amount_paise") or case.get("amount_paise") or 0)
        if self.persist_cases is not None and existing.get("id"):
            from rekha.store import PromiseStore

            PromiseStore.update_state(existing["id"], "Renegotiated")
            row = PromiseStore.create(case, new_amount, new_date, {"parent_promise_id": existing.get("id")})
            case["promise"] = row
        else:
            case["promise"] = {
                "promised_date": new_date,
                "promised_amount_paise": new_amount,
                "state": "Open",
                "parent_promise_id": existing.get("id"),
            }
        case["ptp_active"] = True
        return {"ok": True, "action": "renegotiate_promise", "notes": notes, "promise": case["promise"]}
