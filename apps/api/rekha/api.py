from __future__ import annotations

import hashlib
import json
import threading
from contextlib import asynccontextmanager, suppress
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from fastapi import BackgroundTasks, FastAPI, Header, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from starlette.exceptions import HTTPException as StarletteHTTPException

from rekha.audit import AuditChain, verify_rows
from rekha.config import cors_origin_list, settings
from rekha.engine import RecoveryEngine
from rekha.eval.cohort import generate_cohort
from rekha.eval.runner import run_eval
from rekha.ingest import event_to_case, verify_webhook_signature
from rekha.paths import FIXTURES_DIR, REPO_ROOT
from rekha.runtime import FLAGS
from rekha.sandbox import FileInbox, RazorpaySandbox
from rekha.status import eval_artifact_path
from rekha.store import (
    ApprovalStore,
    CaseStore,
    ComplaintStore,
    ConsentStore,
    JobStore,
    LedgerStore,
    PersistentAuditSink,
    PersistentInbox,
    PromiseStore,
    RuntimeKVStore,
)

IST = ZoneInfo("Asia/Kolkata")
_LOCK = threading.Lock()

STATE: dict = {
    "inbox": None,  # PersistentInbox, bound at startup
    "sandbox": RazorpaySandbox(),
    "comms": FileInbox(),
    "audit": AuditChain(),
    "latest": None,
    "mtime": None,
    "engine": None,  # singleton live engine
}


def wall_now() -> datetime:
    return datetime.now(IST)


def _payments():
    if settings.payments_adapter == "razorpay_test":
        try:
            from rekha.razorpay_live import RazorpayLive

            return RazorpayLive()
        except Exception:  # noqa: BLE001
            return STATE["sandbox"]
    return STATE["sandbox"]


def _live_engine() -> RecoveryEngine:
    if STATE["engine"] is None:
        STATE["engine"] = RecoveryEngine(
            payments=_payments(),
            comms=STATE["comms"],
            audit=STATE["audit"],
            strategy="rekha",
            persist=True,
        )
    return STATE["engine"]


def _http(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "message": message})


def _require_ops(x_ops_token: str | None) -> None:
    if settings.ops_token:
        if x_ops_token != settings.ops_token:
            raise _http(401, "UNAUTHORIZED", "valid X-Ops-Token required")
    elif settings.rekha_env != "dev":
        raise _http(401, "UNAUTHORIZED", "X-Ops-Token required outside dev")


def _payload_ok(data: object) -> bool:
    return isinstance(data, dict) and isinstance(data.get("report"), dict) and isinstance(data.get("cases"), list)


def _load_from_disk() -> dict | None:
    path = eval_artifact_path()
    if not path.exists():
        return None
    mtime = path.stat().st_mtime
    cached = STATE["latest"]
    if _payload_ok(cached) and STATE["mtime"] == mtime:
        return cached
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        STATE["latest"] = None
        STATE["mtime"] = None
        return None
    if not _payload_ok(data):
        STATE["latest"] = None
        STATE["mtime"] = None
        return None
    STATE["latest"] = data
    STATE["mtime"] = mtime
    return data


def _ensure_latest(*, run_if_missing: bool) -> dict:
    with _LOCK:
        loaded = _load_from_disk()
        if loaded is not None:
            return loaded
        if not run_if_missing:
            raise _http(404, "EVAL_MISSING", "No eval report yet. Use Run eval.")
        payload = run_eval(seed=42, write=True, write_golden=False)
        if not _payload_ok(payload):
            raise _http(500, "EVAL_BROKEN", "Eval finished but the report was unreadable.")
        STATE["latest"] = payload
        path = eval_artifact_path()
        STATE["mtime"] = path.stat().st_mtime if path.exists() else None
        return payload


def _process_event(event_id: str, event_type: str, payload: dict) -> dict:
    engine = _live_engine()
    inner = payload.get("payload") if isinstance(payload.get("payload"), dict) else payload
    case = event_to_case({"event_id": event_id, "event_type": event_type, "payload": inner})
    return engine.run_case(case, wall_now()).to_dict()


def _drain_pending() -> None:
    inbox = STATE["inbox"]
    if inbox is None:
        return
    for rec in inbox.pending():
        try:
            result = _process_event(rec["event_id"], rec["event_type"], rec["payload"])
            inbox.mark_processed(rec["event_id"], result)
        except Exception as exc:  # noqa: BLE001
            inbox.mark_processed(rec["event_id"], None, error=str(exc))


_SCHEDULER = None


@asynccontextmanager
async def lifespan(_app: FastAPI):
    global _SCHEDULER
    with suppress(OSError, ImportError, RuntimeError):
        from rekha.db.session import init_db

        init_db()
    with suppress(Exception):  # best-effort in dev
        saved_kill = RuntimeKVStore.get("kill_switch")
        if isinstance(saved_kill, bool):
            FLAGS.kill_switch = saved_kill
    with suppress(Exception):  # best-effort in dev
        STATE["inbox"] = PersistentInbox()
        chain = AuditChain(sink=PersistentAuditSink())
        last = PersistentAuditSink.last_row()
        rows = PersistentAuditSink.rows()
        if last:
            chain.resume(last["seq"], last["entry_hash"], rows=rows)
        STATE["audit"] = chain
        _live_engine()
        _drain_pending()
        from rekha.scheduler import Scheduler

        _SCHEDULER = Scheduler(_live_engine)
        await _SCHEDULER.start()
    if settings.auto_eval_on_boot:
        try:
            _ensure_latest(run_if_missing=True)
        except (OSError, RuntimeError, ValueError, KeyError, TypeError, json.JSONDecodeError):
            with _LOCK:
                _load_from_disk()
    else:
        with _LOCK:
            _load_from_disk()
    yield
    if _SCHEDULER is not None:
        await _SCHEDULER.stop()


app = FastAPI(title="Rekha", version="0.2.0", description="Bounded revenue recovery", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origin_list() or ["*"],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def _ops_guard(request: Request, call_next):
    if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
        path = request.url.path.rstrip("/") or "/"
        if path != "/webhooks/razorpay":
            try:
                _require_ops(request.headers.get("x-ops-token"))
            except HTTPException as exc:
                detail = exc.detail if isinstance(exc.detail, dict) else {"code": "UNAUTHORIZED", "message": str(exc.detail)}
                return JSONResponse(status_code=exc.status_code, content={"detail": detail})
    return await call_next(request)


@app.exception_handler(StarletteHTTPException)
async def _http_exc(_request: Request, exc: StarletteHTTPException) -> JSONResponse:
    detail = exc.detail
    if not isinstance(detail, dict):
        detail = {"code": "HTTP_ERROR", "message": str(detail)}
    return JSONResponse(status_code=exc.status_code, content={"detail": detail})


@app.exception_handler(RequestValidationError)
async def _validation(_request: Request, _exc: RequestValidationError) -> JSONResponse:
    return JSONResponse(status_code=422, content={"detail": {"code": "BAD_REQUEST", "message": "invalid request"}})


@app.exception_handler(Exception)
async def _unhandled(_request: Request, exc: Exception) -> JSONResponse:
    if isinstance(exc, StarletteHTTPException):
        return await _http_exc(_request, exc)
    return JSONResponse(status_code=500, content={"detail": {"code": "INTERNAL", "message": "internal error"}})


def _latest() -> dict:
    return _ensure_latest(run_if_missing=False)


@app.get("/")
def root() -> dict:
    return {"name": "rekha", "ok": True, "health": "/health", "status": "/status", "docs": "/docs"}


@app.get("/health")
def health() -> dict:
    return {"ok": True, "kill_switch": FLAGS.kill_switch, "name": "rekha"}


@app.get("/status")
def status() -> dict:
    path = eval_artifact_path()
    with _LOCK:
        latest = _load_from_disk()
    from rekha.degradation import MONITOR

    scheduler_up = _SCHEDULER is not None and not _SCHEDULER._stop.is_set()
    db_url = settings.database_url
    return {
        "ok": True,
        "eval_ready": latest is not None,
        "eval_path": str(path),
        "kill_switch": FLAGS.kill_switch,
        "live_audit_rows": PersistentAuditSink.count(),
        "scheduler": {"up": scheduler_up, "upcoming_jobs": JobStore.upcoming(5)},
        "env": settings.rekha_env,
        "ops_auth_required": not (settings.rekha_env == "dev" and not settings.ops_token),
        "webhook_secret_set": bool(settings.razorpay_webhook_secret),
        "payments_adapter": settings.payments_adapter,
        "database": "postgres" if "postgres" in db_url else "sqlite",
        "degradation": MONITOR.ranked_by_rupees()[:8],
    }


@app.get("/eval/latest")
def eval_latest() -> dict:
    return _latest()["report"]


@app.get("/cases")
def list_cases(trap: str | None = None, blocked: bool | None = None) -> list[dict]:
    rows = _latest()["cases"]
    if trap:
        rows = [r for r in rows if r.get("trap") == trap]
    if blocked is True:
        rows = [r for r in rows if r.get("blocked")]
    return rows


@app.get("/cases/live")
def live_cases() -> list[dict]:
    return CaseStore.live_cases()


def _live_case_view(live: dict) -> dict:
    case_id = live["case_id"]
    ledger = [r for r in LedgerStore.rows(200) if r.get("case_id") == case_id]
    audit = [r for r in PersistentAuditSink.rows() if r.get("case_id") == case_id][-40:]
    return {
        **live,
        "source": "live",
        "strategy": "live",
        "diagnosis": {
            "recoverability_class": live.get("loss_class"),
            "error_reason": live.get("stop_reason"),
        },
        "proposal": {},
        "verdict": {},
        "blocked": False,
        "deferred": False,
        "violations": [],
        "ledger": ledger,
        "audit": audit,
    }


@app.get("/cases/{case_id}")
def get_case(case_id: str) -> dict:
    latest = None
    try:
        latest = _latest()
    except HTTPException as exc:
        detail = exc.detail if isinstance(exc.detail, dict) else {}
        if detail.get("code") not in {"EVAL_MISSING", "EVAL_BROKEN"}:
            raise
    if latest:
        for row in latest["cases"]:
            if row.get("case_id") == case_id:
                return row
    live = CaseStore.get(case_id)
    if live is None:
        raise _http(404, "CASE_NOT_FOUND", "case not found")
    return _live_case_view(live)


@app.get("/cases/{case_id}/neighbors")
def case_neighbors(case_id: str) -> dict:
    try:
        latest = _latest()
        ids = [r.get("case_id") for r in latest["cases"]]
        if case_id in ids:
            i = ids.index(case_id)
            return {"prev": ids[i - 1] if i else None, "next": ids[i + 1] if i < len(ids) - 1 else None}
    except HTTPException:
        pass
    return CaseStore.neighbors(case_id)


@app.get("/compliance/blocked")
def blocked() -> list[dict]:
    return _latest()["report"].get("blocked_actions") or []


@app.get("/ptp")
def ptp() -> list[dict]:
    live = PromiseStore.list_live()
    if live:
        return live
    return _latest().get("promises") or []


@app.get("/ledger")
def ledger(attribution: str | None = None) -> dict:
    return {"totals": LedgerStore.total(), "rows": LedgerStore.rows(attribution=attribution)}


@app.get("/audit")
def audit_log() -> dict:
    live = PersistentAuditSink.rows()
    if live:
        ok, msg = verify_rows(live)
        return {"ok": ok, "msg": msg, "rows": live, "source": "live"}
    payload = _latest()
    return {"ok": payload.get("audit_ok"), "msg": payload.get("audit_msg"), "rows": payload.get("audit") or [], "source": "eval"}


@app.post("/audit/verify")
def audit_verify() -> dict:
    live = PersistentAuditSink.rows()
    rows = live if live else (_latest().get("audit") or [])
    ok, msg = verify_rows(rows)
    return {"ok": ok, "msg": msg, "rows": len(rows), "source": "live" if live else "eval"}


@app.post("/audit/tamper")
def audit_tamper() -> dict:
    rows = json.loads(json.dumps(PersistentAuditSink.rows() or _latest().get("audit") or []))
    if not rows:
        raise _http(400, "EMPTY_AUDIT", "empty audit")
    idx = min(3, len(rows) - 1)
    rows[idx]["action"] = "TAMPERED"
    ok, msg = verify_rows(rows)
    return {"ok": ok, "msg": msg, "tampered_seq": rows[idx].get("seq")}


class KillBody(BaseModel):
    engaged: bool


@app.post("/kill-switch")
def kill_switch(body: KillBody, x_ops_token: str | None = Header(default=None, alias="X-Ops-Token")) -> dict:
    _require_ops(x_ops_token)
    FLAGS.kill_switch = body.engaged
    with suppress(Exception):
        RuntimeKVStore.set("kill_switch", body.engaged)
    STATE["audit"].append({"actor": "ops", "action": "kill_switch", "payload": {"engaged": body.engaged}})
    return {"kill_switch": FLAGS.kill_switch}


@app.get("/kill-switch")
def kill_get() -> dict:
    return {"kill_switch": FLAGS.kill_switch}


@app.get("/approvals")
def approvals_pending(status: str | None = "pending") -> list[dict]:
    return ApprovalStore.list_by_status(status or "pending")


class ApprovalDecision(BaseModel):
    decision: str = Field(pattern="^(approve|reject)$")
    approver: str = "ops"


@app.post("/approvals/{approval_id}/decide")
def approval_decide(
    approval_id: str,
    body: ApprovalDecision,
    x_ops_token: str | None = Header(default=None, alias="X-Ops-Token"),
) -> dict:
    _require_ops(x_ops_token)
    record = ApprovalStore.get(approval_id)
    if record is None:
        raise _http(404, "APPROVAL_NOT_FOUND", "unknown approval")
    if body.decision == "approve" and FLAGS.kill_switch:
        raise _http(409, "KILL_SWITCH", "kill switch is engaged")
    engine = _live_engine()
    if body.decision == "approve":
        from rekha.diagnose import diagnose

        case = record["case"]
        proposal = record["proposal"]
        try:
            ctx = engine._context(case, diagnose(case), engine.recon.check(case), wall_now())
            fresh = engine.policy.evaluate(proposal, ctx, wall_now())
        except (ValueError, TypeError):
            fresh = None
        if fresh is not None and fresh.effect == "DENY":
            ApprovalStore.decide(approval_id, "reject", body.approver)
            engine.audit.append(
                {
                    "actor": f"human:{body.approver}",
                    "case_id": case.get("id"),
                    "action": "approval_policy_changed",
                    "payload": {"approval_id": approval_id, "reason": fresh.reason_code},
                }
            )
            raise _http(409, "POLICY_CHANGED", fresh.reason_code)
    decided = ApprovalStore.decide(approval_id, body.decision, body.approver)
    if decided is None:
        raise _http(409, "APPROVAL_CLOSED", "approval already decided")
    if body.decision == "approve":
        case = record["case"]
        proposal = record["proposal"]
        execution = engine.executor.execute(case, proposal, _approved_verdict(record), wall_now())
        engine.audit.append(
            {
                "actor": f"human:{body.approver}",
                "case_id": case.get("id"),
                "action": "approval_executed",
                "payload": {"approval_id": approval_id, "execution": execution},
            }
        )
        if execution.get("ok"):
            contacted = proposal.get("channel") not in (None, "internal")
            CaseStore.record_touch(
                case["id"],
                contacted=contacted,
                channel=proposal.get("channel") or "internal",
                customer_id=case.get("customer_id"),
            )
        return {"ok": True, "status": "approved", "execution": execution}
    engine.audit.append(
        {
            "actor": f"human:{body.approver}",
            "case_id": record["case"].get("id"),
            "action": "approval_rejected",
            "payload": {"approval_id": approval_id},
        }
    )
    return {"ok": True, "status": "rejected"}


def _approved_verdict(record: dict):
    from rekha.policy import Verdict

    stored = record.get("verdict") or {}
    return Verdict(
        effect="ALLOW",
        reason_code=f"APPROVED_{stored.get('reason_code', 'MANUAL')}",
        matched_rules=[{"id": "human_approval", "effect": "ALLOW", "reason_code": "HUMAN_APPROVED"}],
        policy_version=stored.get("policy_version", ""),
        policy_hash=stored.get("policy_hash", ""),
    )


def _inside_repo(path: Path) -> bool:
    try:
        path.resolve().relative_to(REPO_ROOT.resolve())
        return True
    except ValueError:
        return False


@app.post("/webhooks/razorpay")
async def razorpay_webhook(
    background: BackgroundTasks,
    request: Request,
    x_razorpay_signature: str | None = Header(default=None, alias="X-Razorpay-Signature"),
    x_razorpay_event_id: str | None = Header(default=None, alias="X-Razorpay-Event-Id"),
    wait: bool = False,
) -> dict:
    raw = await request.body()
    if not verify_webhook_signature(raw, x_razorpay_signature or ""):
        reason = (
            "SECRET_UNSET"
            if not settings.razorpay_webhook_secret and settings.rekha_env != "dev"
            else "BAD_SIGNATURE"
        )
        STATE["audit"].append(
            {"actor": "ingest", "action": "webhook_rejected", "payload": {"reason": reason, "event_id": x_razorpay_event_id}}
        )
        raise _http(400, reason, "invalid signature")
    try:
        payload = json.loads(raw.decode() or "{}")
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise _http(400, "BAD_JSON", "invalid json") from exc
    if not isinstance(payload, dict):
        raise _http(400, "BAD_JSON", "body must be an object")
    inbox = STATE["inbox"]
    event_id = str(x_razorpay_event_id or payload.get("event_id") or hashlib.sha256(raw).hexdigest())
    if inbox is not None:
        _rec, first = inbox.accept(event_id, payload.get("event") or "unknown", payload)
        if not first:
            return {"ok": True, "deduped": True, "event_id": event_id}
    else:  # tests without DB
        first = True
    if not first:
        return {"ok": True, "deduped": True, "event_id": event_id}
    if wait or inbox is None:
        result = _process_event(event_id, payload.get("event") or "unknown", payload)
        if inbox is not None:
            inbox.mark_processed(event_id, result)
        return {"ok": True, "event_id": event_id, "result": result}
    background.add_task(_process_and_mark, event_id, payload.get("event") or "unknown", payload)
    return {"ok": True, "queued": True, "event_id": event_id}


def _process_and_mark(event_id: str, event_type: str, payload: dict) -> None:
    inbox = STATE["inbox"]
    try:
        result = _process_event(event_id, event_type, payload)
        if inbox is not None:
            inbox.mark_processed(event_id, result)
    except Exception as exc:  # noqa: BLE001
        if inbox is not None:
            inbox.mark_processed(event_id, None, error=str(exc))


class BatchIngest(BaseModel):
    path: str | None = None
    cases: list[dict] = Field(default_factory=list)


@app.post("/batch/ingest")
def batch_ingest(body: BatchIngest) -> dict:
    rows = list(body.cases)
    if body.path:
        target = Path(body.path).expanduser()
        if not _inside_repo(target):
            raise _http(400, "PATH_DENIED", "path must stay inside the repo")
        if not target.is_file():
            raise _http(404, "FILE_NOT_FOUND", "file not found")
        text = target.read_text(encoding="utf-8")
        try:
            rows.extend(json.loads(line) for line in text.splitlines() if line.strip())
        except json.JSONDecodeError as exc:
            raise _http(400, "BAD_JSON", "file is not JSONL") from exc
    if not rows:
        rows = generate_cohort(42)[:10]
    engine = _live_engine()
    out = [engine.run_case(case, wall_now()).to_dict() for case in rows]
    return {"ok": True, "n": len(out), "results": out}


@app.post("/eval/run")
def eval_run(seed: int = 42) -> dict:
    if seed < 0:
        raise _http(400, "BAD_SEED", "seed must be zero or greater")
    try:
        payload = run_eval(seed=seed, write=True, write_golden=False)
    except Exception as exc:
        raise _http(500, "EVAL_FAILED", "eval failed") from exc
    if not _payload_ok(payload):
        raise _http(500, "EVAL_BROKEN", "Eval finished but the report was unreadable.")
    with _LOCK:
        STATE["latest"] = payload
        path = eval_artifact_path()
        STATE["mtime"] = path.stat().st_mtime if path.exists() else None
    return payload["report"]


class RunCaseBody(BaseModel):
    case_id: str | None = None
    case: dict | None = None


@app.post("/cases/run")
def run_one(body: RunCaseBody) -> dict:
    case = body.case
    if case is None:
        if not body.case_id:
            raise _http(400, "BAD_REQUEST", "case or case_id is required")
        cohort = generate_cohort(42)
        case = next((c for c in cohort if c["id"] == body.case_id), None)
        if case is None:
            raise _http(404, "CASE_NOT_FOUND", "unknown case_id")
    engine = _live_engine()
    return engine.run_case(case, wall_now()).to_dict()


class AwaazBody(BaseModel):
    case: dict
    lines: list[str] = Field(default_factory=list)


@app.post("/awaaz/session")
def awaaz_session(body: AwaazBody) -> dict:
    """Run the scripted Hinglish session server-side and return the full
    transcript, disposition and captured PTP. This is a transcript fixture
    driven by the real FSM. no audio pipeline is claimed."""
    from rekha.voice import run_scripted_session

    case = body.case
    if not case.get("id"):
        raise _http(400, "BAD_REQUEST", "case.id is required")
    try:
        int(case["amount_paise"])
    except (KeyError, TypeError, ValueError) as exc:
        raise _http(400, "BAD_REQUEST", "amount_paise is required") from exc
    try:
        session = run_scripted_session(case, body.lines, wall_now())
    except ValueError as exc:
        raise _http(400, "BAD_REQUEST", str(exc)) from exc
    return {
        "case_id": case["id"],
        "verified": session.verified,
        "stopped": session.stopped,
        "stop_reason": session.stop_reason,
        "compliance_flags": session.compliance_flags,
        "captured_ptp": session.captured_ptp,
        "turns": [{"state": t.state, "agent": t.agent, "user": t.user, "tool": t.tool} for t in session.turns],
    }


class ComplaintBody(BaseModel):
    customer_id: str


@app.post("/complaints")
def complaint(body: ComplaintBody) -> dict:
    now = wall_now()
    FLAGS.record_complaint(now)
    ComplaintStore.record(body.customer_id, now, source="api")
    STATE["audit"].append({"actor": "customer", "action": "complaint", "payload": {"customer_id": body.customer_id}})
    return {"ok": True, "throttled": ComplaintStore.throttled(body.customer_id, now)}


@app.post("/scheduler/tick")
def scheduler_tick() -> dict:
    from rekha.scheduler import Scheduler

    return Scheduler(_live_engine).tick()


@app.get("/webhooks/recent")
def webhook_recent(limit: int = 15) -> dict:
    inbox = STATE["inbox"]
    rows = inbox.recent(limit) if inbox is not None else []
    return {"rows": rows}


@app.get("/webhooks/sample")
def webhook_sample(name: str = "payment_failed") -> dict:
    safe = "".join(ch for ch in name if ch.isalnum() or ch in {"_", "-"}) or "payment_failed"
    path = FIXTURES_DIR / "webhooks" / f"{safe}.json"
    if not path.exists():
        raise _http(404, "SAMPLE_NOT_FOUND", "unknown sample")
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise _http(404, "SAMPLE_NOT_FOUND", "sample unreadable") from exc


@app.get("/policy")
def policy_view() -> dict:
    import yaml

    from rekha.constants import CAPS, CONSTANTS_PATH
    from rekha.policy import get_engine

    engine = get_engine()
    constants = yaml.safe_load(CONSTANTS_PATH.read_bytes())
    blocked = []
    try:
        blocked = _latest()["report"].get("blocked_actions") or []
    except HTTPException:
        pass
    counts: dict[str, int] = {}
    for row in blocked:
        key = str(row.get("rule") or "unknown")
        counts[key] = counts.get(key, 0) + 1
    return {
        "version": engine.doc["version"],
        "policy_hash": engine.policy_hash,
        "rules": engine.doc.get("rules") or [],
        "constants": constants,
        "caps": CAPS,
        "blocked_counts": counts,
    }


@app.get("/jobs")
def list_jobs(status: str | None = None, limit: int = 100) -> dict:
    return {"jobs": JobStore.list_jobs(status=status, limit=limit)}


@app.post("/jobs/{job_id}/cancel")
def cancel_job(job_id: int) -> dict:
    row = JobStore.cancel(job_id)
    if row is None:
        raise _http(404, "JOB_NOT_FOUND", "unknown job")
    if not row.get("cancelled"):
        raise _http(409, "JOB_CLOSED", f"job is {row.get('status')}")
    STATE["audit"].append({"actor": "ops", "action": "job_cancelled", "payload": {"job_id": job_id}})
    return row


@app.get("/complaints/state")
def complaints_state(customer_id: str | None = None) -> dict:
    return ComplaintStore.state(customer_id, wall_now())


@app.get("/customers/{customer_id}")
def customer_get(customer_id: str) -> dict:
    row = ConsentStore.get(customer_id, wall_now())
    if row is None:
        raise _http(404, "CUSTOMER_NOT_FOUND", "unknown customer")
    return row


class ConsentBody(BaseModel):
    status: str = Field(pattern="^(GRANTED|REVOKED|UNKNOWN)$")


@app.post("/customers/{customer_id}/consent")
def customer_consent(customer_id: str, body: ConsentBody) -> dict:
    row = ConsentStore.upsert(customer_id, status=body.status)
    STATE["audit"].append(
        {"actor": "ops", "action": "consent_set", "payload": {"customer_id": customer_id, "status": body.status}}
    )
    return row
