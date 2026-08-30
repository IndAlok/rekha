from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def utcnow() -> datetime:
    return datetime.now(UTC)


class Base(DeclarativeBase):
    pass


class Merchant(Base):
    __tablename__ = "merchants"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String)
    vertical: Mapped[str] = mapped_column(String, default="d2c")


class Customer(Base):
    __tablename__ = "customers"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    merchant_id: Mapped[str] = mapped_column(String)
    language: Mapped[str] = mapped_column(String, default="en-IN")
    consent_status: Mapped[str] = mapped_column(String, default="UNKNOWN")
    consent_changed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    consent_withdrawn_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    opt_out: Mapped[bool] = mapped_column(Boolean, default=False)
    dnd: Mapped[bool] = mapped_column(Boolean, default=False)
    strategic_tier: Mapped[str] = mapped_column(String, default="standard")


class RecoveryCase(Base):
    __tablename__ = "recovery_cases"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    customer_id: Mapped[str] = mapped_column(String)
    merchant_id: Mapped[str] = mapped_column(String)
    loss_class: Mapped[str] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, default="open")
    amount_paise: Mapped[int] = mapped_column(Integer)
    currency: Mapped[str] = mapped_column(String, default="INR")
    recoverability_class: Mapped[str | None] = mapped_column(String, nullable=True)
    touches: Mapped[int] = mapped_column(Integer, default=0)
    contacts_last_7d: Mapped[int] = mapped_column(Integer, default=0)
    recovered: Mapped[bool] = mapped_column(Boolean, default=False)
    recovery_source: Mapped[str] = mapped_column(String, default="none")
    stop_reason: Mapped[str | None] = mapped_column(String, nullable=True)
    parent_case_id: Mapped[str | None] = mapped_column(String, nullable=True)
    mandate_attempts_used: Mapped[int] = mapped_column(Integer, default=0)
    nach_representations_used: Mapped[int] = mapped_column(Integer, default=0)
    first_failed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    payload_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class WebhookInbox(Base):
    __tablename__ = "webhook_inbox"
    event_id: Mapped[str] = mapped_column(String, primary_key=True)
    event_type: Mapped[str] = mapped_column(String)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    payload_json: Mapped[str] = mapped_column(Text)
    processed: Mapped[bool] = mapped_column(Boolean, default=False)
    error_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    result_json: Mapped[str | None] = mapped_column(Text, nullable=True)


class IdempotencyKey(Base):
    __tablename__ = "idempotency"
    key: Mapped[str] = mapped_column(String, primary_key=True)
    state: Mapped[str] = mapped_column(String, default="IN_FLIGHT")  # IN_FLIGHT | SUCCEEDED | FAILED
    result_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    lock_expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class ContactReservationRow(Base):
    __tablename__ = "contact_reservations"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    customer_id: Mapped[str] = mapped_column(String)
    window_bucket: Mapped[str] = mapped_column(String)
    channel: Mapped[str] = mapped_column(String)
    confirmed: Mapped[bool] = mapped_column(Boolean, default=False)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    __table_args__ = (UniqueConstraint("customer_id", "window_bucket", "channel", name="uq_contact_slot"),)


class AuditRow(Base):
    __tablename__ = "audit_log"
    seq: Mapped[int] = mapped_column(Integer, primary_key=True)
    prev_hash: Mapped[str] = mapped_column(String)
    entry_hash: Mapped[str] = mapped_column(String, unique=True)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    actor: Mapped[str] = mapped_column(String, default="rekha.engine")
    case_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    action: Mapped[str] = mapped_column(String)
    policy_version: Mapped[str] = mapped_column(String, default="")
    policy_hash: Mapped[str] = mapped_column(String, default="")
    payload_json: Mapped[str] = mapped_column(Text)


class PromiseRow(Base):
    __tablename__ = "promises_to_pay"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    case_id: Mapped[str] = mapped_column(String, index=True)
    customer_id: Mapped[str] = mapped_column(String)
    promised_amount_paise: Mapped[int] = mapped_column(Integer)
    promised_date: Mapped[str] = mapped_column(String)
    state: Mapped[str] = mapped_column(String, default="Open")
    payload_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ScheduledJob(Base):
    __tablename__ = "scheduled_jobs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(String)  # deferred | send_after | approval_timeout_check
    case_id: Mapped[str] = mapped_column(String, index=True)
    run_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    status: Mapped[str] = mapped_column(String, default="pending")  # pending | running | done | cancelled | failed
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    case_json: Mapped[str] = mapped_column(Text, default="{}")
    result_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Approval(Base):
    __tablename__ = "approvals"
    id: Mapped[str] = mapped_column(String, primary_key=True)
    case_id: Mapped[str] = mapped_column(String, index=True)
    status: Mapped[str] = mapped_column(String, default="pending")  # pending | approved | rejected | timed_out | executed
    approver_role: Mapped[str] = mapped_column(String, default="finance_ops")
    approver: Mapped[str | None] = mapped_column(String, nullable=True)
    proposal_json: Mapped[str] = mapped_column(Text, default="{}")
    verdict_json: Mapped[str] = mapped_column(Text, default="{}")
    case_json: Mapped[str] = mapped_column(Text, default="{}")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class RecoveryLedgerRow(Base):
    __tablename__ = "recovery_ledger"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    case_id: Mapped[str] = mapped_column(String, index=True)
    obligation_key: Mapped[str] = mapped_column(String, unique=True)
    intervention_action: Mapped[str | None] = mapped_column(String, nullable=True)
    intervention_channel: Mapped[str | None] = mapped_column(String, nullable=True)
    source_event: Mapped[str] = mapped_column(String)
    amount_paise: Mapped[int] = mapped_column(Integer)
    recovered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    attribution: Mapped[str] = mapped_column(String, default="agent")  # agent | self_cure


class RuntimeKV(Base):
    __tablename__ = "runtime_kv"
    key: Mapped[str] = mapped_column(String, primary_key=True)
    value_json: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class ChargeGuard(Base):
    """One captured charge per case. the database-level double-charge stop."""

    __tablename__ = "charge_guard"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    case_id: Mapped[str] = mapped_column(String)
    attempt_no: Mapped[int] = mapped_column(Integer)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    amount_paise: Mapped[int] = mapped_column(Integer)
    __table_args__ = (UniqueConstraint("case_id", "attempt_no", name="uq_charge_per_attempt"),)


class Complaint(Base):
    """A customer complaint. Durable, because the circuit breaker must
    survive a restart."""

    __tablename__ = "complaints"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    customer_id: Mapped[str] = mapped_column(String, index=True)
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    source: Mapped[str] = mapped_column(String, default="api")


class CaseContact(Base):
    """One customer contact event. The true source for the rolling
    7-day contact window."""

    __tablename__ = "case_contacts"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    case_id: Mapped[str] = mapped_column(String, index=True)
    customer_id: Mapped[str] = mapped_column(String, index=True)
    channel: Mapped[str] = mapped_column(String)
    contacted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
