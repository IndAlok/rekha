from __future__ import annotations

import hashlib
from typing import Any


def tool_key(*, tool: str, case_id: str, attempt_no: int, policy_version: str) -> str:
    raw = f"{tool}:{case_id}:{attempt_no}:{policy_version}"
    return hashlib.sha1(raw.encode()).hexdigest()


def receipt(*, case_id: str, attempt_no: int) -> str:
    return hashlib.sha1(f"{case_id}:{attempt_no}".encode()).hexdigest()[:40]


class IdempotencyStore:
    def __init__(self) -> None:
        self._seen: dict[str, Any] = {}

    def claim(self, key: str, factory) -> tuple[Any, bool]:
        if key in self._seen:
            return self._seen[key], False
        value = factory()
        self._seen[key] = value
        return value, True
