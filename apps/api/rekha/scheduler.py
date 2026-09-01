from __future__ import annotations

import asyncio
import logging
from datetime import UTC, datetime

from rekha.store import JOB_MAX_ATTEMPTS, ApprovalStore, JobStore

log = logging.getLogger("rekha.scheduler")

TICK_SECONDS = 5
MAX_ATTEMPTS = JOB_MAX_ATTEMPTS


class Scheduler:
    def __init__(self, engine_factory) -> None:
        self._engine_factory = engine_factory
        self._task: asyncio.Task | None = None
        self._stop = asyncio.Event()

    async def start(self) -> None:
        self._stop.clear()
        self._task = asyncio.create_task(self._loop(), name="rekha-scheduler")

    async def stop(self) -> None:
        self._stop.set()
        if self._task:
            try:
                await asyncio.wait_for(self._task, timeout=TICK_SECONDS * 2)
            except (TimeoutError, asyncio.CancelledError):
                self._task.cancel()

    async def _loop(self) -> None:
        while not self._stop.is_set():
            try:
                await asyncio.to_thread(self.tick)
            except Exception:
                log.exception("scheduler tick failed")
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=TICK_SECONDS)
            except TimeoutError:
                pass

    def tick(self, *, now: datetime | None = None) -> dict:
        now = now or datetime.now(UTC)
        fired = 0
        engine = None
        for expired in ApprovalStore.expire_due():
            fired += 1
            if engine is None:
                engine = self._engine_factory()
            engine.audit.append(
                {
                    "actor": "rekha.scheduler",
                    "action": "approval_timeout",
                    "payload": {"approval_id": expired},
                }
            )
            log.info("approval %s timed out, auto-denied", expired)
        for job in JobStore.due(now):
            try:
                result = self._run_job(job, now)
                JobStore.finish(job["id"], "done", result)
                fired += 1
            except Exception as exc:
                log.exception("job %s failed", job["id"])
                JobStore.finish(job["id"], "failed", {"error": str(exc)})
        return {"fired": fired}

    def _run_job(self, job: dict, now: datetime) -> dict:
        engine = self._engine_factory()
        case = {**job["case"], "dispatch_now": True}
        result = engine.run_case(case, now)
        return {"case_id": result.case_id, "effect": result.verdict.get("effect"), "executed": result.executed}


def run_due_jobs(engine_factory) -> dict:
    """Synchronous one-shot drain. used by tests and the CLI."""
    return Scheduler(engine_factory).tick()
