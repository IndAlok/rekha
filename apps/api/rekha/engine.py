from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from rekha.advisor import CLOSED_TOOLS, advise, filter_proposal
from rekha.audit import AuditChain, canonical
from rekha.clocks import as_ist, in_contact_window, in_upi_peak, local_hour, nach_gap_elapsed_days
from rekha.compliance import scan_copy
from rekha.degradation import MONITOR
from rekha.diagnose import diagnose
from rekha.execute import SAFE_INTERNAL_ACTIONS, Executor
from rekha.p2p import PromiseToPay, evaluate_promise, freeze_active
from rekha.playbooks import propose
from rekha.policy import PolicyEngine, Verdict, get_engine
from rekha.preflight import preflight
from rekha.recon import ReconciliationGuard
from rekha.runtime import FLAGS
from rekha.sandbox import FileInbox, RazorpaySandbox
from rekha.taxonomy import hard_do_not_contact, mac_forbidden, mac_retry_hours
from rekha.templates import render
from rekha.voice import run_scripted_session

OUTREACH_ACTIONS = {
    "create_payment_link",
    "send_template_message",
    "send_subscription_update_method_link",
    "issue_or_notify_invoice",
    "schedule_mandate_presentment",
}

MONEY_ACTIONS = OUTREACH_ACTIONS | {"silent_retry_same_instrument"}


@dataclass
class CaseResult:
    case_id: str
    strategy: str
    diagnosis: dict
    proposal: dict
    verdict: dict
    executed: bool
    recovered: bool
    recovery_source: str
    amount_paise: int
    violations: list[str] = field(default_factory=list)
    blocked: bool = False
    deferred: bool = False
    scheduled: bool = False
    execution: dict | None = None
    voice: dict | None = None
    approval_id: str | None = None
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "case_id": self.case_id,
            "strategy": self.strategy,
            "diagnosis": self.diagnosis,
            "proposal": self.proposal,
            "verdict": self.verdict,
            "executed": self.executed,
            "recovered": self.recovered,
            "recovery_source": self.recovery_source,
            "amount_paise": self.amount_paise,
            "violations": self.violations,
            "blocked": self.blocked,
            "deferred": self.deferred,
            "scheduled": self.scheduled,
            "execution": self.execution,
            "voice": self.voice,
            "approval_id": self.approval_id,
            "notes": self.notes,
        }


class RecoveryEngine:
    """The bounded loop: diagnose -> reconcile -> propose -> policy -> execute.

    `persist=False` (eval) keeps everything in memory and deterministic.
    `persist=True` (live) additionally writes counters, ledger entries,
    approvals and scheduled jobs through rekha.store.
    """

    def __init__(
        self,
        *,
        payments=None,
        comms=None,
        policy: PolicyEngine | None = None,
        audit: AuditChain | None = None,
        strategy: str = "rekha",
        persist: bool = False,
    ) -> None:
        self.payments = payments or RazorpaySandbox()
        self.comms = comms or FileInbox()
        self.policy = policy or get_engine()
        self.audit = audit or AuditChain()
        self.strategy = strategy
        self.persist = persist
        self.executor = Executor(self.payments, self.comms)
        self.recon = ReconciliationGuard(self.payments)
        self._store = None
        if persist:
            from rekha import store as store_module
            from rekha.store import CaseStore, ChargeGuardStore, PersistentIdempotency, PersistentReservations

            self._store = store_module
            self._cases = CaseStore
            self.executor.reservations = PersistentReservations()
            self.executor.idem = PersistentIdempotency()
            self.executor.charge_guard = ChargeGuardStore.try_capture
            self.executor.persist_cases = CaseStore


    def run_case(self, case: dict, now: datetime) -> CaseResult:
        if not case.get("id") and case.get("case_id"):
            case = {**case, "id": case["case_id"]}
        if not case.get("id"):
            case = {**case, "id": "unknown"}
        self._seed_world(case)

        if case.get("loss_class") == "recovery_event":
            return self._handle_recovery_event(case, now)

        if self.persist:
            from rekha.store import ConsentStore

            case = ConsentStore.overlay(case, as_ist(now))
            self._cases.upsert(case)
            touches, contacts = self._cases.counters(case["id"])
            stored = self._cases.get(case["id"]) or {}
            hours = self._cases.hours_since_failure(case["id"], now)
            case = {
                **case,
                "touches_this_case": max(int(case.get("touches_this_case") or 0), touches),
                "contacts_last_7d": max(int(case.get("contacts_last_7d") or 0), contacts),
                "mandate_attempts_used": max(
                    int(case.get("mandate_attempts_used") or 0), int(stored.get("mandate_attempts_used") or 0)
                ),
                "nach_representations_used": max(
                    int(case.get("nach_representations_used") or 0), int(stored.get("nach_representations_used") or 0)
                ),
            }
            if hours is not None:
                case["hours_since_failure"] = hours
            ptp = self._store.PromiseStore.for_case(case["id"])
            if ptp:
                case["promise"] = ptp
                case["ptp_active"] = ptp.get("state") in {"Open", "Reminded"}

        diagnosis = diagnose(case)
        self._audit("diagnose", case, {"diagnosis": diagnosis.to_dict()})

        if case.get("customer_complaint"):
            if self.persist:
                self._store.ComplaintStore.record(case.get("customer_id") or "unknown", as_ist(now), source="case")
            else:
                FLAGS.record_complaint(as_ist(now))

        recon = self.recon.check(case)
        self._audit(
            "reconcile",
            case,
            {"already_paid": recon.already_paid, "live_status": recon.live_status, "unknown": recon.unknown, "source": recon.source},
        )
        if recon.unknown:
            return self._finish(
                case,
                diagnosis.to_dict(),
                {"action": "suppress_and_stop", "reason": "recon_unknown", "engine": "reconciliation_guard"},
                _deny_verdict("RECON_FETCH_UNKNOWN"),
                executed=False,
                recovered=False,
                recovery_source="none",
                blocked=True,
                notes=["recon_fetch_unknown_fail_closed"],
            )
        if recon.already_paid:
            return self._finish(
                case,
                diagnosis.to_dict(),
                {"action": "suppress_and_stop", "reason": "late_auth_or_already_paid", "engine": "reconciliation_guard"},
                _deny_verdict("LATE_AUTH_ALREADY_PAID"),
                executed=False,
                recovered=self._attribute_recovery(case, source_event="recon", attribution="self_cure", action=None, channel=None),
                recovery_source="self_cure",
                notes=["credited_to_self_cure_not_agent"],
            )

        # Reconcile-first reasons (deemed / pending / duplicate RRN): a fetch
        # that comes back "unpaid" is NOT a settlement-level reconciliation.
        # reconciled stays False unless the case carries proof, so the policy
        # rule blocks the blind retry.
        if diagnosis.reconcile_first and not case.get("reconciled"):
            deep = self.recon.deep_check(case)
            self._audit("reconcile_deep", case, {"settled": deep})
            if deep:
                return self._finish(
                    case,
                    diagnosis.to_dict(),
                    {"action": "suppress_and_stop", "reason": "deemed_settled_upstream", "engine": "reconciliation_guard"},
                    _deny_verdict("LATE_AUTH_ALREADY_PAID"),
                    executed=False,
                    recovered=self._attribute_recovery(case, source_event="deep_recon", attribution="self_cure", action=None, channel=None),
                    recovery_source="self_cure",
                    notes=["duplicate_rrn_settled"],
                )

        pf = preflight(case)
        proposal = propose(case, diagnosis, pf, now)
        if proposal.get("action") not in SAFE_INTERNAL_ACTIONS | CLOSED_TOOLS:
            proposal = {"action": "suppress_and_stop", "reason": "action_not_in_allowlist", "engine": "router"}
        advised = filter_proposal(advise(case, diagnosis.to_dict()))
        if advised and advised.get("action") == proposal.get("action"):
            proposal = {**proposal, **advised}

        if case.get("llm_draft"):
            scan = scan_copy(case["llm_draft"], channel=proposal.get("channel") or "email")
            if not scan.ok:
                proposal = {**proposal, "llm_draft_blocked": scan.flags}
                self._audit("compliance_veto_llm", case, {"flags": scan.flags})

        if self.persist:
            throttled = self._store.ComplaintStore.throttled(case.get("customer_id") or "unknown", as_ist(now))
        else:
            throttled = FLAGS.complaint_throttle(as_ist(now))
        if throttled and proposal.get("channel") not in (None, "internal"):
            self._audit("complaint_circuit", case, {"reason": "complaint_rate"})
            return self._finish(
                case,
                diagnosis.to_dict(),
                {**proposal, "throttled": True},
                _deny_verdict("COMPLAINT_CIRCUIT"),
                executed=False,
                recovered=False,
                recovery_source="none",
                blocked=True,
                notes=["complaint_circuit_breaker"],
            )
        if FLAGS.kill_switch and proposal.get("action") not in SAFE_INTERNAL_ACTIONS:
            return self._finish(
                case,
                diagnosis.to_dict(),
                proposal,
                _deny_verdict("KILL_SWITCH"),
                executed=False,
                recovered=False,
                recovery_source="none",
                blocked=True,
                notes=["kill_switch_engaged"],
            )

        if self.strategy == "holdout":
            return self._run_holdout(case, diagnosis.to_dict(), now)

        try:
            ctx = self._context(case, diagnosis, recon, now)
            verdict = self.policy.evaluate(proposal, ctx, now)
        except (ValueError, TypeError) as exc:
            verdict = _deny_verdict("FAIL_CLOSED_MISSING_FACTS")
            self._audit("fail_closed", case, {"error": str(exc)})
            return self._finish(
                case,
                diagnosis.to_dict(),
                proposal,
                verdict,
                executed=False,
                recovered=False,
                recovery_source="none",
                blocked=True,
                notes=[str(exc)],
            )

        self._audit(
            "policy",
            case,
            {"proposal": proposal, "verdict": verdict.to_dict(), "ctx_keys": sorted(ctx)},
        )

        if proposal.get("template_id") and proposal.get("channel"):
            try:
                _, scan = render(
                    proposal["template_id"],
                    self._render_values(case, proposal, url="https://rzp.io/i/preview", send_after="soon"),
                    channel=proposal["channel"],
                )
                if not scan.ok:
                    verdict = _deny_verdict("COMPLIANCE_COPY_VETO")
                    self._audit("compliance_veto", case, {"flags": scan.flags})
            except ValueError as exc:
                verdict = _deny_verdict("TEMPLATE_GUARD")
                self._audit("template_guard", case, {"error": str(exc)})

        voice_out = None
        if proposal.get("engine") == "awaaz" and case.get("voice_lines"):
            session = run_scripted_session(case, case["voice_lines"], now)
            voice_out = {
                "stopped": session.stopped,
                "stop_reason": session.stop_reason,
                "turns": len(session.turns),
                "ptp": session.captured_ptp,
            }
            if session.stopped:
                verdict = _deny_verdict("VOICE_HARD_STOP")
                proposal = {**proposal, "action": "suppress_and_stop", "reason": session.stop_reason}

        executed = False
        execution = None
        approval_id = None
        scheduled = False
        if verdict.effect == "ALLOW" and proposal.get("action") not in {None}:
            send_at = _parse_dt(proposal.get("send_after"))
            mac_wait = mac_retry_hours(case.get("mac_code"))
            hours_since = float(case.get("hours_since_failure") or 0)
            if mac_wait is not None and hours_since < mac_wait and proposal.get("action") in MONEY_ACTIONS:
                mac_at = now + timedelta(hours=mac_wait - hours_since)
                send_at = mac_at if send_at is None or mac_at > send_at else send_at
            waiting = send_at is not None and send_at > now and not case.get("dispatch_now")
            if waiting:
                scheduled = True
                if self.persist:
                    job_id = self._store.JobStore.schedule("send_after", case, send_at)
                    execution = {
                        "ok": True,
                        "scheduled_job": job_id,
                        "run_at": send_at.isoformat(),
                        "action": proposal.get("action"),
                    }
                    self._audit("scheduled", case, {"job_id": job_id, "run_at": send_at.isoformat(), "action": proposal.get("action")})
                else:
                    execution = {
                        "ok": True,
                        "scheduled": True,
                        "run_at": send_at.isoformat(),
                        "action": proposal.get("action"),
                        "modeled_payout": proposal.get("action") in set(case.get("winning_actions") or []),
                    }
                    self._audit("scheduled_eval", case, execution)
            else:
                execution = self.executor.execute(case, proposal, verdict, now)
                executed = bool(execution.get("ok"))
                self._audit("execute", case, execution)
                if executed and self.persist:
                    MONITOR.record(
                        issuer=case.get("issuer"),
                        method=case.get("method") or (case.get("mandate") or {}).get("rail"),
                        psp=case.get("psp"),
                        success=True,
                        amount_paise=int(case.get("amount_paise") or 0),
                        attempt_no=int(case.get("touches_this_case") or 0) + 1,
                    )
                    contacted = proposal.get("channel") not in (None, "internal")
                    self._cases.record_touch(
                        case["id"],
                        contacted=contacted,
                        channel=proposal.get("channel") or "internal",
                        customer_id=case.get("customer_id"),
                    )
                    if proposal.get("action") == "schedule_mandate_presentment":
                        rail = (case.get("mandate") or {}).get("rail")
                        self._cases.bump_mandate(case["id"], upi=rail == "upi", nach=rail == "nach")
                    if proposal.get("action") == "capture_promise_to_pay" and execution.get("promise"):
                        case["promise"] = execution["promise"]
                        case["ptp_active"] = True
        elif verdict.effect == "DEFER" and self.persist and verdict.defer_until:
            run_at = datetime.fromisoformat(verdict.defer_until)
            job_id = self._store.JobStore.schedule("deferred", case, run_at)
            scheduled = True
            self._audit("deferred_scheduled", case, {"job_id": job_id, "run_at": verdict.defer_until})
        elif verdict.effect == "REQUIRE_APPROVAL" and self.persist:
            approval_id = self._store.ApprovalStore.create(case, proposal, verdict.to_dict(), verdict.approver_role or "finance_ops")
            self._audit("approval_requested", case, {"approval_id": approval_id, "approver_role": verdict.approver_role})

        recovered, source = self._recovery(case, proposal, verdict, executed, scheduled=scheduled)
        violations = self._violations(case, proposal, verdict, executed, now, recovered)
        result = self._finish(
            case,
            diagnosis.to_dict(),
            proposal,
            verdict,
            executed=executed,
            recovered=recovered,
            recovery_source=source,
            blocked=verdict.effect == "DENY",
            deferred=verdict.effect == "DEFER",
            scheduled=scheduled,
            execution=execution,
            notes=[],
        )
        result.voice = voice_out
        result.approval_id = approval_id
        result.violations = violations
        if self.persist:
            self._cases.stash_payload(case)
            if recovered:
                self._cases.close(case["id"], recovered=True, source=source)
            elif result.blocked and verdict.reason_code in {"HARD_DO_NOT_CONTACT", "CONSENT_REVOKED", "CONSENT_NOT_ON_FILE", "SUPPRESSED"}:
                self._cases.close(case["id"], recovered=False, stop_reason=verdict.reason_code)
        return result


    def _handle_recovery_event(self, case: dict, now: datetime) -> CaseResult:
        """payment.captured & friends: never dun, close the case, attribute."""
        attribution = "self_cure"
        action = channel = None
        target = case["id"]
        if self.persist:
            open_id = self._cases.open_case_for_refs(case.get("source_refs") or {})
            target = open_id or case["id"]
            last = self._last_intervention(open_id) if open_id else None
            if last and last.get("action"):
                attribution = "agent"
                action, channel = last.get("action"), last.get("channel")
            self._cases.close(target, recovered=True, source=attribution)
            self._resolve_promise(target, case, now)
        recovered = self._attribute_recovery(case, source_event=case.get("event_type", "recovery"), attribution=attribution, action=action, channel=channel)
        self._audit(
            "recovery_event",
            case,
            {"event": case.get("event_type"), "attributed_to": attribution, "case": target},
        )
        return self._finish(
            case,
            {"recoverability_class": "T", "root_cause": "payment_succeeded", "error_reason": ""},
            {"action": "suppress_and_stop", "reason": "recovery_event_close", "engine": "ingest"},
            _deny_verdict("LATE_AUTH_ALREADY_PAID"),
            executed=False,
            recovered=recovered,
            recovery_source=attribution,
            notes=[f"closed_case={target}"],
        )

    def _last_intervention(self, case_id: str) -> dict | None:
        if not self.persist:
            return None
        with_self = None
        for row in reversed(self.audit.rows):
            if row.get("case_id") == case_id and row.get("action") == "execute":
                payload = row.get("payload") or {}
                with_self = {"action": payload.get("action"), "channel": payload.get("channel")}
                break
        return with_self

    def _resolve_promise(self, case_id: str, case: dict, now: datetime) -> None:
        row = self._store.PromiseStore.for_case(case_id)
        if not row or row.get("state") not in {"Open", "Reminded"}:
            return
        today = as_ist(now).date().isoformat()
        ptp = PromiseToPay(
            id=row["id"],
            customer_id=row["customer_id"],
            case_id=case_id,
            promised_amount_paise=int(row.get("promised_amount_paise") or 0),
            promised_date=str(row.get("promised_date") or today),
            state=row.get("state") or "Open",
        )
        evaluate_promise(ptp, int(case.get("amount_paise") or 0), today)
        self._store.PromiseStore.update_state(row["id"], ptp.state)

    def _attribute_recovery(self, case: dict, *, source_event: str, attribution: str, action: str | None, channel: str | None) -> bool:
        if self.persist and not case.get("already_attributed"):
            refs = case.get("source_refs") or {}
            key = f"{case['id']}:{refs.get('payment_id') or refs.get('order_id') or refs.get('invoice_id') or refs.get('payment_link_id') or source_event}"
            self._store.LedgerStore.record(
                case["id"],
                int(case.get("amount_paise") or 0),
                source_event=source_event,
                attribution=attribution,
                action=action,
                channel=channel,
                obligation_key=key,
            )
            case["already_attributed"] = True
            return True
        return True

    def _recovery(self, case: dict, proposal: dict, verdict: Verdict, executed: bool, scheduled: bool = False) -> tuple[bool, str]:
        winning = set(case.get("winning_actions") or [])
        action = proposal.get("action")
        if verdict.effect != "ALLOW":
            return False, "none"
        if action in winning and action in MONEY_ACTIONS:
            if executed:
                return True, "agent"
            if scheduled and not self.persist:
                return True, "agent"
        return False, "none"

    def _run_holdout(self, case: dict, diagnosis: dict, now: datetime) -> CaseResult:
        action = (
            "silent_retry_same_instrument"
            if diagnosis.get("recoverability_class") == "R"
            else "create_payment_link"
        )
        proposal = {
            "action": action,
            "channel": None if action.startswith("silent") else "email",
            "template_id": None if action.startswith("silent") else "svc_pay_link_email",
            "engine": "razorpay_default",
            "reason": "status_quo_t1_t2_t3_email",
        }
        executed = False
        execution = None
        if proposal["channel"]:
            execution = self.executor.execute(case, proposal, _allow_verdict(), now)
            executed = bool(execution.get("ok"))
        recovered = proposal["action"] in set(case.get("winning_actions") or []) and not case.get("already_paid")
        return self._finish(
            case,
            diagnosis,
            proposal,
            _allow_verdict(),
            executed=executed,
            recovered=recovered,
            recovery_source="agent" if recovered else "none",
            execution=execution,
            notes=["holdout_ignores_pdp"],
        )

    def _violations(self, case: dict, proposal: dict, verdict: Verdict, executed: bool, now: datetime, recovered: bool) -> list[str]:
        if self.strategy != "rekha":
            return []
        flags: list[str] = []
        channel = proposal.get("channel")
        action = proposal.get("action")
        contacted = executed and channel not in (None, "internal") and verdict.effect == "ALLOW"
        if contacted and case.get("consent_status") in {"REVOKED", "UNKNOWN"}:
            flags.append("contacted_without_consent")
        if contacted and (case.get("suppressed") or case.get("dnd")):
            flags.append("contacted_dnd")
        if contacted and not in_contact_window(now):
            flags.append("outside_hours")
        if contacted and diagnose(case).recoverability_class.value == "B":
            flags.append("class_b_outreach")
        if contacted and hard_do_not_contact(diagnose(case).error_reason):
            flags.append("hard_dnc_contact")
        if case.get("already_paid") and executed and action in MONEY_ACTIONS:
            flags.append("double_charge")
        if executed and case.get("would_pause_authenticated_sub") and action != "suppress_and_stop":
            flags.append("paused_authenticated_sub")
        if contacted and channel == "sms" and case.get("has_coupon"):
            flags.append("coupon_on_service_sms")
        attempts = int(case.get("mandate_attempts_used") or 0)
        if executed and action == "schedule_mandate_presentment":
            attempts += 1
        if (case.get("mandate") or {}).get("rail") == "upi" and attempts > 4:
            flags.append("upi_over_budget")
        if recovered and not case.get("oracle_recoverable") and not case.get("already_paid"):
            flags.append("beat_oracle")
        return flags


    def _context(self, case: dict, diagnosis, recon, now: datetime) -> dict:
        for key in ("contacts_last_7d", "touches_this_case", "consent_status"):
            if key not in case:
                raise ValueError(f"fail-closed: missing facts ['{key}']")
        mandate = case.get("mandate") or {}
        ptp = case.get("promise")
        pdn_elapsed = case.get("pdn_elapsed_hours")
        pdn_ready = isinstance(pdn_elapsed, (int, float)) and pdn_elapsed >= 24
        gap_days = nach_gap_elapsed_days(case.get("nach_last_return_at"), now)
        if case.get("nach_gap_ok") is not None:
            nach_gap_ok = bool(case["nach_gap_ok"])
        elif gap_days is not None:
            nach_gap_ok = gap_days >= 3
        else:
            nach_gap_ok = None  # unknown -> policy fails closed
        return {
            "contacts_last_7d": case["contacts_last_7d"],
            "touches_this_case": case["touches_this_case"],
            "consent_status": case["consent_status"],
            "suppressed": bool(case.get("suppressed") or case.get("dnd")),
            "legal_hold": bool(case.get("legal_hold")),
            "recoverability_class": diagnosis.recoverability_class.value,
            "error_reason": diagnosis.error_reason,
            "hard_dnc": hard_do_not_contact(diagnosis.error_reason),
            "mac_code": case.get("mac_code"),
            "mac_forbidden": mac_forbidden(case.get("mac_code")),
            "hours_since_failure": case.get("hours_since_failure", 48),
            "reconciled": bool(case.get("reconciled", False)),
            "already_paid": recon.already_paid,
            "ptp_active": bool(case.get("ptp_active") or (ptp and freeze_active(ptp, as_ist(now)))),
            "dispute_open": bool(case.get("dispute_open")),
            "local_hour": local_hour(now),
            "mandate_rail": mandate.get("rail"),
            "in_upi_peak": in_upi_peak(now),
            "mandate_attempts_used": case.get("mandate_attempts_used", mandate.get("attempts_used", 0)),
            "nach_gap_ok": nach_gap_ok,
            "nach_representations_used": int(case.get("nach_representations_used", mandate.get("representations_used", 0))),
            "customer_confirmed_funds": bool(case.get("customer_confirmed_funds")),
            "pdn_elapsed_hours": pdn_elapsed,
            "pdn_ready": pdn_ready,
            "has_coupon": bool(case.get("has_coupon")),
            "amount_mismatch": bool(case.get("amount_mismatch")),
            "amount_paise": case.get("amount_paise", 0),
            "strategic_tier": case.get("strategic_tier", "standard"),
            "requested_legal_step": bool(case.get("requested_legal_step")),
            "portability_nudge": bool(case.get("portability_nudge")),
            "would_pause_authenticated_sub": bool(case.get("would_pause_authenticated_sub")),
        }


    @staticmethod
    def _render_values(case: dict, proposal: dict, *, url: str, send_after: str | None) -> dict[str, str]:
        return {
            "amount": str(int(case.get("amount_paise") or 0) // 100),
            "ref": str(case.get("id") or "case")[:20],
            "url": url,
            "merchant": (case.get("merchant_name") or "Merchant")[:30],
            "issuer": (case.get("issuer") or "card")[:30],
            "last4": str(case.get("last4") or "4242"),
            "date": (send_after or proposal.get("send_after") or "soon")[:30],
        }

    def _seed_world(self, case: dict) -> None:
        refs = case.get("source_refs") or {}
        live = case.get("live_statuses") or {}
        if not hasattr(self.payments, "seed_entity"):
            return

        def _merge(kind: str, entity_id: str, patch: dict) -> None:
            store = getattr(self.payments, f"{kind}s")
            existing = store.get(entity_id) or {}
            store[entity_id] = {**existing, **patch}

        if refs.get("payment_id"):
            status = live.get("payment") or ("authorized" if case.get("already_paid") else "failed")
            _merge("payment", refs["payment_id"], {"id": refs["payment_id"], "status": status})
        if refs.get("order_id"):
            status = live.get("order") or ("paid" if case.get("already_paid") else "attempted")
            _merge("order", refs["order_id"], {"id": refs["order_id"], "status": status})
        if refs.get("invoice_id"):
            status = live.get("invoice") or ("paid" if case.get("already_paid") else "issued")
            _merge(
                "invoice",
                refs["invoice_id"],
                {
                    "id": refs["invoice_id"],
                    "status": status,
                    "subscription_id": refs.get("subscription_id"),
                    "amount": case.get("amount_paise"),
                },
            )

    def _finish(self, case, diagnosis, proposal, verdict, **kwargs) -> CaseResult:
        return CaseResult(
            case_id=str(case.get("id") or "unknown"),
            strategy=self.strategy,
            diagnosis=diagnosis,
            proposal=proposal,
            verdict=verdict.to_dict() if hasattr(verdict, "to_dict") else verdict,
            amount_paise=int(case.get("amount_paise") or 0),
            **kwargs,
        )

    def _audit(self, action: str, case: dict, payload: dict) -> None:
        inputs_hash = hashlib.sha256(canonical({k: v for k, v in case.items() if k not in ("voice_lines",)}).encode()).hexdigest()[:16]
        self.audit.append(
            {
                "actor": "rekha.engine",
                "case_id": case.get("id"),
                "action": action,
                "inputs_hash": inputs_hash,
                "payload": payload,
                "policy_version": getattr(self.policy, "doc", {}).get("version") if hasattr(self.policy, "doc") else "",
                "policy_hash": getattr(self.policy, "policy_hash", ""),
            }
        )


def _parse_dt(raw) -> datetime | None:
    if raw is None:
        return None
    if isinstance(raw, datetime):
        return raw
    try:
        return datetime.fromisoformat(str(raw))
    except ValueError:
        return None


def _deny_verdict(reason: str) -> Verdict:
    return Verdict(effect="DENY", reason_code=reason, matched_rules=[{"id": reason, "effect": "DENY", "reason_code": reason}])


def _allow_verdict() -> Verdict:
    return Verdict(effect="ALLOW", reason_code="HOLDOUT_NO_PDP", matched_rules=[])
