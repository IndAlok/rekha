from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError

from rekha.db.models import (
    Approval,
    AuditRow,
    CaseContact,
    ChargeGuard,
    Complaint,
    ContactReservationRow,
    Customer,
    IdempotencyKey,
    PromiseRow,
    RecoveryCase,
    RecoveryLedgerRow,
    RuntimeKV,
    ScheduledJob,
    WebhookInbox,
)
from rekha.db.session import get_session, session_scope
from rekha.db.time import as_utc, coerce_utc

JOB_LEASE_SECONDS = 60
JOB_MAX_ATTEMPTS = 3
RESERVE_LEASE_SECONDS = 300
CONSENT_SILENCE_DAYS = 90
COMPLAINT_WINDOW_DAYS = 10
COMPLAINT_THRESHOLD = 2


def _now() -> datetime:
    return datetime.now(UTC)


def _as_utc(ts: datetime) -> datetime:
    return as_utc(ts)


def _aware(ts: datetime | None) -> datetime | None:
    """SQLite returns naive datetimes regardless of DateTime(timezone=True)."""
    if ts is None:
        return None
    return as_utc(ts)


def _iso(ts: datetime | None) -> str | None:
    return ts.isoformat() if ts else None


def _from_iso(raw) -> datetime | None:
    try:
        return coerce_utc(raw)
    except (TypeError, ValueError):
        return None


def db_json(value) -> str:
    return json.dumps(value, default=str).replace("\x00", "")


class PersistentInbox:
    def accept(self, event_id: str, event_type: str, payload: dict) -> tuple[dict, bool]:
        with session_scope() as session:
            existing = session.get(WebhookInbox, event_id)
            if existing is not None:
                return (
                    {
                        "event_id": existing.event_id,
                        "event_type": existing.event_type,
                        "received_at": _iso(existing.received_at),
                        "processed": existing.processed,
                    },
                    False,
                )
            row = WebhookInbox(
                event_id=event_id,
                event_type=event_type,
                received_at=_now(),
                payload_json=db_json(payload),
            )
            session.add(row)
            try:
                session.flush()
            except IntegrityError:
                session.rollback()
                return ({"event_id": event_id, "event_type": event_type, "processed": True}, False)
        return ({"event_id": event_id, "event_type": event_type, "received_at": _now().isoformat(), "processed": False}, True)

    def mark_processed(self, event_id: str, result: dict | None = None, error: str | None = None) -> None:
        with session_scope() as session:
            row = session.get(WebhookInbox, event_id)
            if row is None:
                return
            row.processed = True
            row.error_text = error.replace("\x00", "") if error else None
            row.result_json = db_json(result) if result else None

    def pending(self) -> list[dict]:
        with session_scope() as session:
            rows = session.scalars(select(WebhookInbox).where(WebhookInbox.processed == False)).all()
            return [
                {"event_id": r.event_id, "event_type": r.event_type, "payload": json.loads(r.payload_json or "{}")}
                for r in rows
            ]

    def recent(self, limit: int = 15) -> list[dict]:
        cap = max(1, min(int(limit), 100))
        with get_session() as session:
            rows = session.scalars(select(WebhookInbox).order_by(WebhookInbox.received_at.desc()).limit(cap)).all()
        return [
            {
                "event_id": r.event_id,
                "event_type": r.event_type,
                "processed": r.processed,
                "received_at": _iso(r.received_at),
                "error_text": r.error_text,
            }
            for r in rows
        ]


class PersistentIdempotency:
    """Claim-check. The first caller writes IN_FLIGHT before running the
    factory. A crash or timeout leaves IN_FLIGHT with an expired lease so
    the next claim retries. SUCCEEDED is the only terminal success state."""

    LEASE_SECONDS = 300

    def claim(self, key: str, factory) -> tuple[dict, bool]:
        now = _now()
        acquired = False
        with session_scope() as session:
            row = session.get(IdempotencyKey, key)
            if row is None:
                session.add(
                    IdempotencyKey(
                        key=key,
                        state="IN_FLIGHT",
                        lock_expires_at=now + timedelta(seconds=self.LEASE_SECONDS),
                    )
                )
                try:
                    session.flush()
                    acquired = True
                except IntegrityError:
                    session.rollback()
                    row = session.get(IdempotencyKey, key)
            if not acquired:
                if row is not None and row.state == "SUCCEEDED":
                    return json.loads(row.result_json or "{}"), False
                lease_ok = (
                    row is not None
                    and row.state == "IN_FLIGHT"
                    and _aware(row.lock_expires_at) is not None
                    and _aware(row.lock_expires_at) > now
                )
                if lease_ok:
                    return {"ok": False, "reason": "concurrent_in_flight"}, False
                if row is None:
                    row = IdempotencyKey(key=key, lock_expires_at=now + timedelta(seconds=self.LEASE_SECONDS))
                    session.add(row)
                row.state = "IN_FLIGHT"
                row.lock_expires_at = now + timedelta(seconds=self.LEASE_SECONDS)
        try:
            value = factory()
        except Exception:
            self._expire_lease(key)
            raise
        self._set_state(key, "SUCCEEDED", value)
        return value, True

    def _expire_lease(self, key: str) -> None:
        with session_scope() as session:
            row = session.get(IdempotencyKey, key)
            if row is None:
                return
            row.state = "IN_FLIGHT"
            row.lock_expires_at = _now()
            row.result_json = None

    def _set_state(self, key: str, state: str, result: dict | None) -> None:
        with session_scope() as session:
            row = session.get(IdempotencyKey, key)
            if row is None:
                row = IdempotencyKey(key=key, lock_expires_at=_now() + timedelta(seconds=self.LEASE_SECONDS))
                session.add(row)
            row.state = state
            row.result_json = db_json(result) if result is not None else None


class PersistentReservations:
    def reserve(self, slot) -> bool:
        now = _now()
        lease = now + timedelta(seconds=RESERVE_LEASE_SECONDS)
        with session_scope() as session:
            existing = session.scalars(
                select(ContactReservationRow).where(
                    ContactReservationRow.customer_id == slot.customer_id,
                    ContactReservationRow.window_bucket == slot.window_bucket,
                    ContactReservationRow.channel == slot.channel,
                )
            ).first()
            if existing is None:
                session.add(
                    ContactReservationRow(
                        customer_id=slot.customer_id,
                        window_bucket=slot.window_bucket,
                        channel=slot.channel,
                        confirmed=False,
                        lease_expires_at=lease,
                    )
                )
                try:
                    session.flush()
                    return True
                except IntegrityError:
                    session.rollback()
                    return False
            if existing.confirmed:
                return False
            exp = _aware(existing.lease_expires_at)
            if exp is not None and exp > now:
                return False
            existing.lease_expires_at = lease
            existing.confirmed = False
            return True

    def confirm(self, slot) -> None:
        with session_scope() as session:
            row = session.scalars(
                select(ContactReservationRow).where(
                    ContactReservationRow.customer_id == slot.customer_id,
                    ContactReservationRow.window_bucket == slot.window_bucket,
                    ContactReservationRow.channel == slot.channel,
                )
            ).first()
            if row is not None:
                row.confirmed = True

    def release(self, slot) -> None:
        with session_scope() as session:
            session.execute(
                delete(ContactReservationRow).where(
                    ContactReservationRow.customer_id == slot.customer_id,
                    ContactReservationRow.window_bucket == slot.window_bucket,
                    ContactReservationRow.channel == slot.channel,
                )
            )

    def contacts_since(self, customer_id: str, since: datetime) -> int:
        cutoff = since.date().isoformat()
        with get_session() as session:
            rows = session.scalars(
                select(ContactReservationRow).where(ContactReservationRow.customer_id == customer_id)
            ).all()
        return sum(1 for r in rows if r.window_bucket >= cutoff)


class PersistentAuditSink:
    """Every AuditChain.append also lands here, inside the same call."""

    def __call__(self, row: dict) -> None:
        occurred = _from_iso(row.get("occurred_at"))
        with session_scope() as session:
            session.add(
                AuditRow(
                    seq=row["seq"],
                    prev_hash=row["prev_hash"],
                    entry_hash=row["entry_hash"],
                    occurred_at=occurred or _now(),
                    actor=str(row.get("actor", "rekha.engine")),
                    case_id=row.get("case_id"),
                    action=str(row.get("action", "")),
                    policy_version=str(row.get("policy_version", "")),
                    policy_hash=str(row.get("policy_hash", "")),
                    payload_json=db_json(row),
                )
            )

    @staticmethod
    def last_row() -> dict | None:
        with get_session() as session:
            row = session.scalars(select(AuditRow).order_by(AuditRow.seq.desc()).limit(1)).first()
        return json.loads(row.payload_json) if row else None

    @staticmethod
    def rows(limit: int = 2000) -> list[dict]:
        with get_session() as session:
            db_rows = session.scalars(select(AuditRow).order_by(AuditRow.seq).limit(limit)).all()
        return [json.loads(r.payload_json) for r in db_rows]

    @staticmethod
    def count() -> int:
        with get_session() as session:
            return len(session.scalars(select(AuditRow.seq)).all())


class CaseStore:
    @staticmethod
    def upsert(case: dict) -> None:
        with session_scope() as session:
            row = session.get(RecoveryCase, case["id"])
            if row is None:
                row = RecoveryCase(
                    id=case["id"],
                    customer_id=case.get("customer_id", "cust_unknown"),
                    merchant_id=case.get("merchant_id", "merch_demo"),
                    loss_class=case.get("loss_class", "payment_failure"),
                    amount_paise=int(case.get("amount_paise") or 0),
                )
                session.add(row)
            row.loss_class = case.get("loss_class", row.loss_class)
            row.amount_paise = int(case.get("amount_paise") or row.amount_paise)
            row.customer_id = case.get("customer_id", row.customer_id)
            if case.get("mandate_attempts_used") is not None:
                row.mandate_attempts_used = int(case["mandate_attempts_used"])
            if case.get("nach_representations_used") is not None:
                row.nach_representations_used = int(case["nach_representations_used"])
            if row.first_failed_at is None:
                hours = case.get("hours_since_failure")
                if hours is not None:
                    try:
                        row.first_failed_at = _now() - timedelta(hours=float(hours))
                    except (TypeError, ValueError):
                        row.first_failed_at = _now()
                else:
                    row.first_failed_at = _now()
            row.updated_at = _now()

    @staticmethod
    def bump_mandate(case_id: str, *, upi: bool = False, nach: bool = False) -> None:
        with session_scope() as session:
            row = session.get(RecoveryCase, case_id)
            if row is None:
                return
            if upi:
                row.mandate_attempts_used += 1
            if nach:
                row.nach_representations_used += 1

    @staticmethod
    def record_touch(case_id: str, *, contacted: bool = False, channel: str = "internal", customer_id: str | None = None) -> int:
        now = _now()
        with session_scope() as session:
            row = session.get(RecoveryCase, case_id)
            if row is None:
                row = RecoveryCase(
                    id=case_id,
                    customer_id=customer_id or "cust_unknown",
                    merchant_id="merch_demo",
                    loss_class="payment_failure",
                    amount_paise=0,
                )
                session.add(row)
            row.touches += 1
            if contacted:
                session.add(
                    CaseContact(
                        case_id=case_id,
                        customer_id=customer_id or row.customer_id,
                        channel=channel or "internal",
                        contacted_at=now,
                    )
                )
            cutoff = now - timedelta(days=7)
            contacts = session.scalars(
                select(CaseContact).where(CaseContact.case_id == case_id, CaseContact.contacted_at >= cutoff)
            ).all()
            # SQLite may compare naive/aware poorly; count in python.
            n = 0
            for c in contacts:
                ts = _aware(c.contacted_at)
                if ts is not None and ts >= cutoff:
                    n += 1
            row.contacts_last_7d = n
            row.updated_at = now
            return row.touches

    @staticmethod
    def count_contacts(customer_id: str, *, since: datetime, channel: str | None = None) -> int:
        with get_session() as session:
            q = select(CaseContact).where(CaseContact.customer_id == customer_id)
            if channel:
                q = q.where(CaseContact.channel == channel)
            rows = session.scalars(q).all()
        since_a = as_utc(since)
        n = 0
        for r in rows:
            ts = _aware(r.contacted_at)
            if ts is not None and ts >= since_a:
                n += 1
        return n

    @staticmethod
    def counters(case_id: str) -> tuple[int, int]:
        now = _now()
        cutoff = now - timedelta(days=7)
        with get_session() as session:
            row = session.get(RecoveryCase, case_id)
            if row is None:
                return (0, 0)
            contacts = session.scalars(select(CaseContact).where(CaseContact.case_id == case_id)).all()
            n = 0
            for c in contacts:
                ts = _aware(c.contacted_at)
                if ts is not None and ts >= cutoff:
                    n += 1
            return (row.touches, n)

    @staticmethod
    def hours_since_failure(case_id: str, now: datetime | None = None) -> float | None:
        now = as_utc(now or _now())
        with get_session() as session:
            row = session.get(RecoveryCase, case_id)
            if row is None or row.first_failed_at is None:
                return None
            start = _aware(row.first_failed_at)
            if start is None:
                return None
            return max(0.0, (now - start).total_seconds() / 3600.0)

    @staticmethod
    def close(case_id: str, *, recovered: bool, source: str, stop_reason: str | None = None) -> None:
        with session_scope() as session:
            row = session.get(RecoveryCase, case_id)
            if row is None:
                return
            row.recovered = recovered
            row.recovery_source = source
            row.status = "recovered" if recovered else (stop_reason or "closed")
            row.stop_reason = stop_reason
            row.updated_at = _now()

    @staticmethod
    def open_case_for_refs(refs: dict) -> str | None:
        """Find a still-open case sharing any source ref (for attribution)."""
        keys = [v for v in refs.values() if v]
        if not keys:
            return None
        keyset = set(keys)
        with get_session() as session:
            rows = session.scalars(
                select(RecoveryCase).where(RecoveryCase.status == "open", RecoveryCase.recovered == False)
            ).all()
        for row in rows:
            payload = json.loads(row.payload_json or "{}")
            case_refs = payload.get("source_refs") or {}
            if any(v in keyset for v in case_refs.values() if v):
                return row.id
        return None

    @staticmethod
    def stash_payload(case: dict) -> None:
        with session_scope() as session:
            row = session.get(RecoveryCase, case["id"])
            if row is not None:
                row.updated_at = _now()
                row.payload_json = db_json(
                    {
                        k: case.get(k)
                        for k in (
                            "source_refs",
                            "customer_id",
                            "amount_paise",
                            "loss_class",
                            "hours_since_failure",
                            "mandate_attempts_used",
                            "nach_representations_used",
                            "consent_status",
                        )
                    },
                )

    @staticmethod
    def _as_dict(r: RecoveryCase) -> dict:
        payload = json.loads(r.payload_json or "{}")
        return {
            "case_id": r.id,
            "status": r.status,
            "loss_class": r.loss_class,
            "amount_paise": r.amount_paise,
            "touches": r.touches,
            "contacts_last_7d": r.contacts_last_7d,
            "mandate_attempts_used": r.mandate_attempts_used,
            "nach_representations_used": r.nach_representations_used,
            "recovered": r.recovered,
            "recovery_source": r.recovery_source,
            "stop_reason": r.stop_reason,
            "updated_at": _iso(r.updated_at),
            "source_refs": payload.get("source_refs") or {},
        }

    @staticmethod
    def get(case_id: str) -> dict | None:
        with get_session() as session:
            row = session.get(RecoveryCase, case_id)
        return CaseStore._as_dict(row) if row else None

    @staticmethod
    def live_cases(limit: int = 100) -> list[dict]:
        with get_session() as session:
            rows = session.scalars(select(RecoveryCase).order_by(RecoveryCase.updated_at.desc()).limit(limit)).all()
        return [CaseStore._as_dict(r) for r in rows]

    @staticmethod
    def neighbors(case_id: str) -> dict:
        ids = [r["case_id"] for r in CaseStore.live_cases(200)]
        try:
            i = ids.index(case_id)
        except ValueError:
            return {"prev": None, "next": None}
        return {"prev": ids[i - 1] if i > 0 else None, "next": ids[i + 1] if i < len(ids) - 1 else None}


class LedgerStore:
    @staticmethod
    def record(
        case_id: str,
        amount_paise: int,
        *,
        source_event: str,
        attribution: str,
        action: str | None,
        channel: str | None,
        obligation_key: str | None = None,
    ) -> bool:
        key = obligation_key or f"{case_id}:{source_event}"
        with session_scope() as session:
            session.add(
                RecoveryLedgerRow(
                    case_id=case_id,
                    obligation_key=key,
                    intervention_action=action,
                    intervention_channel=channel,
                    source_event=source_event,
                    amount_paise=int(amount_paise),
                    recovered_at=_now(),
                    attribution=attribution,
                )
            )
            try:
                session.flush()
                return True
            except IntegrityError:
                session.rollback()
                return False

    @staticmethod
    def total() -> dict:
        with get_session() as session:
            rows = session.scalars(select(RecoveryLedgerRow)).all()
        agent = sum(r.amount_paise for r in rows if r.attribution == "agent")
        selfc = sum(r.amount_paise for r in rows if r.attribution == "self_cure")
        return {"agent_paise": agent, "self_cure_paise": selfc, "entries": len(rows)}

    @staticmethod
    def rows(limit: int = 100, attribution: str | None = None) -> list[dict]:
        with get_session() as session:
            q = select(RecoveryLedgerRow).order_by(RecoveryLedgerRow.id.desc())
            if attribution and attribution != "all":
                q = q.where(RecoveryLedgerRow.attribution == attribution)
            rows = session.scalars(q.limit(limit)).all()
        out = [
            {
                "case_id": r.case_id,
                "action": r.intervention_action,
                "channel": r.intervention_channel,
                "source_event": r.source_event,
                "amount_paise": r.amount_paise,
                "attribution": r.attribution,
                "recovered_at": _iso(r.recovered_at),
                "obligation_key": r.obligation_key,
            }
            for r in rows
        ]
        return out


class ChargeGuardStore:
    @staticmethod
    def try_capture(case_id: str, attempt_no: int, amount_paise: int) -> bool:
        with session_scope() as session:
            session.add(ChargeGuard(case_id=case_id, attempt_no=attempt_no, amount_paise=int(amount_paise)))
            try:
                session.flush()
                return True
            except IntegrityError:
                session.rollback()
                return False


class ApprovalStore:
    TIMEOUT_DAYS = 2

    @staticmethod
    def create(case: dict, proposal: dict, verdict: dict, approver_role: str) -> str:
        approval_id = f"appr-{case['id']}-{_now().strftime('%H%M%S%f')}"
        with session_scope() as session:
            session.add(
                Approval(
                    id=approval_id,
                    case_id=case["id"],
                    approver_role=approver_role,
                    proposal_json=db_json(proposal),
                    verdict_json=db_json(verdict),
                    case_json=db_json(case),
                    expires_at=_now() + timedelta(days=ApprovalStore.TIMEOUT_DAYS),
                )
            )
        return approval_id

    @staticmethod
    def get(approval_id: str) -> dict | None:
        with get_session() as session:
            row = session.get(Approval, approval_id)
            if row is None:
                return None
            return ApprovalStore._as_dict(row)

    @staticmethod
    def _as_dict(row: Approval) -> dict:
        return {
            "id": row.id,
            "case_id": row.case_id,
            "status": row.status,
            "approver_role": row.approver_role,
            "approver": row.approver,
            "proposal": json.loads(row.proposal_json or "{}"),
            "verdict": json.loads(row.verdict_json or "{}"),
            "case": json.loads(row.case_json or "{}"),
            "expires_at": _iso(row.expires_at),
            "decided_at": _iso(row.decided_at),
            "amount_paise": json.loads(row.case_json or "{}").get("amount_paise", 0),
        }

    @staticmethod
    def decide(approval_id: str, decision: str, approver: str) -> dict | None:
        with session_scope() as session:
            row = session.get(Approval, approval_id)
            if row is None or row.status != "pending":
                return None
            row.status = "approved" if decision == "approve" else "rejected"
            row.approver = approver
            row.decided_at = _now()
            return {"id": row.id, "status": row.status, "case_id": row.case_id}

    @staticmethod
    def pending() -> list[dict]:
        return ApprovalStore.list_by_status("pending")

    @staticmethod
    def list_by_status(status: str | None = "pending") -> list[dict]:
        with get_session() as session:
            q = select(Approval).order_by(Approval.created_at.desc())
            if status and status != "all":
                q = q.where(Approval.status == status)
            rows = session.scalars(q).all()
        return [ApprovalStore._as_dict(r) for r in rows]

    @staticmethod
    def expire_due() -> list[str]:
        now = _now()
        expired: list[str] = []
        with session_scope() as session:
            rows = session.scalars(select(Approval).where(Approval.status == "pending")).all()
            for row in rows:
                if _aware(row.expires_at) and _aware(row.expires_at) < now:
                    row.status = "timed_out"
                    row.decided_at = now
                    expired.append(row.id)
        return expired


class JobStore:
    @staticmethod
    def schedule(kind: str, case: dict, run_at: datetime) -> int:
        when = _as_utc(run_at)
        with session_scope() as session:
            row = ScheduledJob(kind=kind, case_id=case["id"], run_at=when, case_json=db_json(case))
            session.add(row)
            session.flush()
            return row.id

    @staticmethod
    def _reclaim_stale(session, now: datetime) -> None:
        now_a = as_utc(now)
        rows = session.scalars(select(ScheduledJob).where(ScheduledJob.status == "running")).all()
        for row in rows:
            exp = _aware(row.lease_expires_at)
            expired = exp is None or exp <= now_a
            if not expired:
                continue
            if row.attempts >= JOB_MAX_ATTEMPTS:
                row.status = "failed"
            else:
                row.status = "pending"
                row.lease_expires_at = None

    @staticmethod
    def due(now: datetime, limit: int = 20) -> list[dict]:
        now_a = _as_utc(now)
        lease = now_a + timedelta(seconds=JOB_LEASE_SECONDS)
        with session_scope() as session:
            JobStore._reclaim_stale(session, now_a)
            rows = session.scalars(
                select(ScheduledJob).where(ScheduledJob.status == "pending").order_by(ScheduledJob.run_at)
            ).all()
            due_rows = []
            for row in rows:
                run_at = _aware(row.run_at)
                if run_at is None:
                    continue
                if run_at <= now_a:
                    due_rows.append(row)
                if len(due_rows) >= limit:
                    break
            out = []
            for row in due_rows:
                row.status = "running"
                row.lease_expires_at = lease
                out.append(
                    {
                        "id": row.id,
                        "kind": row.kind,
                        "case": json.loads(row.case_json or "{}"),
                        "run_at": _iso(row.run_at),
                        "attempts": row.attempts,
                    }
                )
            return out

    @staticmethod
    def finish(job_id: int, status: str, result: dict | None = None) -> None:
        with session_scope() as session:
            row = session.get(ScheduledJob, job_id)
            if row is None:
                return
            row.attempts += 1
            row.result_json = db_json(result) if result else None
            row.lease_expires_at = None
            if status == "failed" and row.attempts < JOB_MAX_ATTEMPTS:
                row.status = "pending"
            else:
                row.status = status

    @staticmethod
    def cancel(job_id: int) -> dict | None:
        with session_scope() as session:
            row = session.get(ScheduledJob, job_id)
            if row is None:
                return None
            if row.status not in {"pending", "running"}:
                return {"id": row.id, "status": row.status, "cancelled": False}
            row.status = "cancelled"
            row.lease_expires_at = None
            return {"id": row.id, "status": "cancelled", "cancelled": True}

    @staticmethod
    def get(job_id: int) -> dict | None:
        with get_session() as session:
            row = session.get(ScheduledJob, job_id)
        return JobStore._as_dict(row) if row else None

    @staticmethod
    def _as_dict(r: ScheduledJob) -> dict:
        return {
            "id": r.id,
            "kind": r.kind,
            "case_id": r.case_id,
            "run_at": _iso(r.run_at),
            "attempts": r.attempts,
            "status": r.status,
            "lease_expires_at": _iso(r.lease_expires_at),
            "result": json.loads(r.result_json) if r.result_json else None,
        }

    @staticmethod
    def list_jobs(status: str | None = None, limit: int = 100) -> list[dict]:
        with get_session() as session:
            q = select(ScheduledJob).order_by(ScheduledJob.run_at.desc()).limit(limit)
            if status and status != "all":
                q = q.where(ScheduledJob.status == status)
            rows = session.scalars(q).all()
        return [JobStore._as_dict(r) for r in rows]

    @staticmethod
    def upcoming(limit: int = 20) -> list[dict]:
        with get_session() as session:
            rows = session.scalars(
                select(ScheduledJob).where(ScheduledJob.status == "pending").order_by(ScheduledJob.run_at).limit(limit)
            ).all()
        return [JobStore._as_dict(r) for r in rows]


class RuntimeKVStore:
    @staticmethod
    def get(key: str, default=None):
        with get_session() as session:
            row = session.get(RuntimeKV, key)
            if row is None:
                return default
            return json.loads(row.value_json)

    @staticmethod
    def set(key: str, value) -> None:
        with session_scope() as session:
            row = session.get(RuntimeKV, key)
            if row is None:
                session.add(RuntimeKV(key=key, value_json=db_json(value)))
            else:
                row.value_json = db_json(value)
                row.updated_at = _now()


class ComplaintStore:
    @staticmethod
    def record(customer_id: str, when: datetime | None = None, source: str = "api") -> None:
        ts = as_utc(when) if when is not None else _now()
        with session_scope() as session:
            session.add(Complaint(customer_id=customer_id, recorded_at=ts, source=source))

    @staticmethod
    def throttled(customer_id: str, now: datetime, window_days: int = COMPLAINT_WINDOW_DAYS, threshold: int = COMPLAINT_THRESHOLD) -> bool:
        cutoff_a = as_utc(now) - timedelta(days=window_days)
        with get_session() as session:
            rows = session.scalars(select(Complaint).where(Complaint.customer_id == customer_id)).all()
        recent = [r for r in rows if (_aware(r.recorded_at) or _now()) >= cutoff_a]
        return len(recent) >= threshold

    @staticmethod
    def state(customer_id: str | None = None, now: datetime | None = None) -> dict:
        now = as_utc(now or _now())
        cutoff = now - timedelta(days=COMPLAINT_WINDOW_DAYS)
        with get_session() as session:
            q = select(Complaint)
            if customer_id:
                q = q.where(Complaint.customer_id == customer_id)
            rows = session.scalars(q).all()
        recent = [r for r in rows if (_aware(r.recorded_at) or _now()) >= cutoff]
        return {
            "customer_id": customer_id,
            "window_days": COMPLAINT_WINDOW_DAYS,
            "count": len(recent),
            "threshold": COMPLAINT_THRESHOLD,
            "throttled": len(recent) >= COMPLAINT_THRESHOLD if customer_id else False,
        }


class ConsentStore:
    @staticmethod
    def upsert(customer_id: str, *, status: str, merchant_id: str = "merch_demo") -> dict:
        now = _now()
        with session_scope() as session:
            row = session.get(Customer, customer_id)
            if row is None:
                row = Customer(id=customer_id, merchant_id=merchant_id, consent_status=status, consent_changed_at=now)
                session.add(row)
            else:
                if row.consent_status != status:
                    row.consent_changed_at = now
                row.consent_status = status
                if status == "REVOKED":
                    row.consent_withdrawn_at = now
                    row.opt_out = True
            return ConsentStore._as_dict(row)

    @staticmethod
    def withdraw(customer_id: str) -> dict:
        return ConsentStore.upsert(customer_id, status="REVOKED")

    @staticmethod
    def get(customer_id: str, now: datetime | None = None) -> dict | None:
        with get_session() as session:
            row = session.get(Customer, customer_id)
        if row is None:
            return None
        view = ConsentStore._as_dict(row)
        now = as_utc(now or _now())
        withdrawn = _aware(row.consent_withdrawn_at)
        if withdrawn is not None:
            silence_until = withdrawn + timedelta(days=CONSENT_SILENCE_DAYS)
            view["silence_until"] = silence_until.isoformat()
            view["silent"] = now <= silence_until
            if view["silent"]:
                view["consent_status"] = "REVOKED"
        else:
            view["silence_until"] = None
            view["silent"] = False
        return view

    @staticmethod
    def overlay(case: dict, now: datetime | None = None) -> dict:
        cid = case.get("customer_id")
        if not cid:
            return case
        stored = ConsentStore.get(cid, now)
        if not stored:
            return case
        out = {**case, "consent_status": stored["consent_status"]}
        if stored.get("silent") or stored.get("opt_out") or stored.get("dnd"):
            out["suppressed"] = True
        if stored.get("dnd"):
            out["dnd"] = True
        if stored.get("legal_hold"):
            out["legal_hold"] = True
        return out

    @staticmethod
    def set_flags(
        customer_id: str,
        *,
        dnd: bool | None = None,
        legal_hold: bool | None = None,
        opt_out: bool | None = None,
        merchant_id: str = "merch_demo",
    ) -> dict:
        with session_scope() as session:
            row = session.get(Customer, customer_id)
            if row is None:
                row = Customer(id=customer_id, merchant_id=merchant_id)
                session.add(row)
            if dnd is not None:
                row.dnd = bool(dnd)
            if legal_hold is not None:
                row.legal_hold = bool(legal_hold)
            if opt_out is not None:
                row.opt_out = bool(opt_out)
            return ConsentStore._as_dict(row)

    @staticmethod
    def _as_dict(row: Customer) -> dict:
        return {
            "id": row.id,
            "merchant_id": row.merchant_id,
            "consent_status": row.consent_status,
            "consent_changed_at": _iso(row.consent_changed_at),
            "consent_withdrawn_at": _iso(row.consent_withdrawn_at),
            "opt_out": row.opt_out,
            "dnd": row.dnd,
            "legal_hold": bool(getattr(row, "legal_hold", False)),
        }


class PromiseStore:
    @staticmethod
    def create(case: dict, amount_paise: int, promised_date: str, extra: dict | None = None) -> dict:
        pid = f"ptp-{case['id']}-{_now().strftime('%H%M%S%f')}"
        payload = extra or {}
        with session_scope() as session:
            row = PromiseRow(
                id=pid,
                case_id=case["id"],
                customer_id=case.get("customer_id", "cust_unknown"),
                promised_amount_paise=int(amount_paise),
                promised_date=promised_date,
                state="Open",
                payload_json=db_json(payload),
            )
            session.add(row)
        return PromiseStore.get(pid) or {}

    @staticmethod
    def get(promise_id: str) -> dict | None:
        with get_session() as session:
            row = session.get(PromiseRow, promise_id)
        return PromiseStore._as_dict(row) if row else None

    @staticmethod
    def for_case(case_id: str) -> dict | None:
        with get_session() as session:
            row = session.scalars(
                select(PromiseRow).where(PromiseRow.case_id == case_id).order_by(PromiseRow.created_at.desc())
            ).first()
        return PromiseStore._as_dict(row) if row else None

    @staticmethod
    def update_state(promise_id: str, state: str, extra: dict | None = None) -> dict | None:
        with session_scope() as session:
            row = session.get(PromiseRow, promise_id)
            if row is None:
                return None
            row.state = state
            row.updated_at = _now()
            if extra:
                payload = json.loads(row.payload_json or "{}")
                payload.update(extra)
                row.payload_json = db_json(payload)
            return PromiseStore._as_dict(row)

    @staticmethod
    def list_live(limit: int = 100) -> list[dict]:
        with get_session() as session:
            rows = session.scalars(select(PromiseRow).order_by(PromiseRow.created_at.desc()).limit(limit)).all()
        return [PromiseStore._as_dict(r) for r in rows]

    @staticmethod
    def _as_dict(row: PromiseRow) -> dict:
        payload = json.loads(row.payload_json or "{}")
        return {
            "id": row.id,
            "case_id": row.case_id,
            "customer_id": row.customer_id,
            "promised_amount_paise": row.promised_amount_paise,
            "amount_paise": row.promised_amount_paise,
            "promised_date": row.promised_date,
            "state": row.state,
            "ptp_breached": row.state == "Broken",
            **payload,
        }
