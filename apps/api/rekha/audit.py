from __future__ import annotations

import hashlib
import json
import threading
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any


def canonical(payload: dict[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def chain_hash(prev_hash: str, payload: dict[str, Any]) -> str:
    material = prev_hash + canonical(payload)
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


GENESIS = "0" * 64


class AuditChain:
    """Append-only hash chain. `sink` (optional) is called with every row so
    live traffic can persist to the audit_log table inside the same append."""

    def __init__(self, sink: Callable[[dict[str, Any]], None] | None = None) -> None:
        self.prev = GENESIS
        self.seq = 0
        self.rows: list[dict[str, Any]] = []
        self.sink = sink
        self._lock = threading.Lock()

    def resume(self, last_seq: int, last_hash: str, rows: list[dict[str, Any]] | None = None) -> None:
        """Continue an existing chain after a restart. the DB's last row is
        the new genesis, so seq numbers and prev-hash links never collide.
        Pass persisted rows so `_last_intervention` still sees executes."""
        with self._lock:
            self.seq = int(last_seq)
            self.prev = last_hash
            if rows is not None:
                self.rows = list(rows)

    def append(self, event: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            self.seq += 1
            body = {
                **event,
                "seq": self.seq,
                "prev_hash": self.prev,
                "occurred_at": event.get("occurred_at") or datetime.now(UTC).isoformat(),
            }
            body.pop("entry_hash", None)
            entry_hash = chain_hash(self.prev, body)
            row = {**body, "entry_hash": entry_hash}
            self.rows.append(row)
            self.prev = entry_hash
            if self.sink is not None:
                self.sink(row)
            return row


def verify_rows(rows: list[dict[str, Any]]) -> tuple[bool, str]:
    prev = GENESIS
    for expected_seq, row in enumerate(rows, start=1):
        if row.get("seq") != expected_seq:
            return False, f"seq_gap at {expected_seq}"
        if row.get("prev_hash") != prev:
            return False, f"prev_hash_mismatch at seq={expected_seq}"
        body = {k: v for k, v in row.items() if k != "entry_hash"}
        recomputed = chain_hash(prev, body)
        if recomputed != row.get("entry_hash"):
            return False, f"entry_hash_mismatch at seq={expected_seq}"
        prev = row["entry_hash"]
    return True, "ok"
