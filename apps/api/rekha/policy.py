from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import yaml

from rekha import constants
from rekha.clocks import as_ist, next_upi_offpeak, next_window_open
from rekha.paths import POLICY_DIR

PRECEDENCE = {"DENY": 0, "REQUIRE_APPROVAL": 1, "DEFER": 2, "ALLOW": 3}


@dataclass(frozen=True)
class Verdict:
    effect: str
    reason_code: str
    matched_rules: list[dict] = field(default_factory=list)
    policy_version: str = ""
    policy_hash: str = ""
    defer_until: str | None = None
    approver_role: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


def _pred(value: Any, cond: dict) -> bool:
    op, arg = next(iter(cond.items()))
    if op == "eq":
        return value == arg
    if op == "gt":
        return value is not None and value > arg
    if op == "gte":
        return value is not None and value >= arg
    if op == "lt":
        return value is not None and value < arg
    if op == "in":
        return value in arg
    if op == "not_in":
        return value not in arg
    if op == "not_in_range":
        # A missing fact (None) is outside every allowed range. fail closed.
        lhs = -1 if value is None else value
        return not (arg[0] <= lhs < arg[1])
    raise ValueError(f"unknown predicate {op}")


class PolicyEngine:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or (POLICY_DIR / "rules.yaml")
        raw = self.path.read_bytes()
        self.policy_hash = hashlib.sha256(raw + constants.constants_hash().encode()).hexdigest()[:16]
        self.doc = yaml.safe_load(raw)
        self.default_effect = str(self.doc.get("default_effect", "ALLOW")).upper()
        if self.default_effect not in PRECEDENCE:
            raise ValueError(f"invalid default_effect {self.default_effect}")

    def evaluate(self, proposal: dict, ctx: dict, now: datetime) -> Verdict:
        required = {"contacts_last_7d", "touches_this_case", "consent_status"}
        missing = required - set(ctx)
        if missing:
            raise ValueError(f"fail-closed: missing facts {sorted(missing)}")

        facts = {
            **ctx,
            "amount_paise": proposal.get("amount_paise", ctx.get("amount_paise", 0)),
            "channel": proposal.get("channel"),
            "error_reason": ctx.get("error_reason"),
        }
        action = proposal.get("action")
        matched: list[dict] = []
        worst = self.default_effect
        worst_rule: dict | None = None
        defer_until = None
        approver = None

        for rule in self.doc.get("rules", []):
            applies = rule.get("applies_to", ["*"])
            if applies != ["*"] and action not in applies and facts.get("channel") not in applies:
                continue
            try:
                ok = all(_pred(facts.get(k), c) for k, c in rule.get("when", {}).items())
            except TypeError as exc:
                raise ValueError(f"fail-closed: type error evaluating {rule['id']}") from exc
            if not ok:
                continue
            matched.append(
                {
                    "id": rule["id"],
                    "effect": rule["effect"],
                    "reason_code": rule["reason_code"],
                    "overridable": rule.get("overridable", True),
                }
            )
            if PRECEDENCE[rule["effect"]] < PRECEDENCE[worst]:
                worst = rule["effect"]
                worst_rule = rule
                if rule["effect"] == "DEFER":
                    defer_until = self._defer_target(rule, ctx, now)
                approver = rule.get("approver_role", approver)

        top = worst_rule or (matched[0] if matched else None)
        if top is None:
            reason = f"NO_RULE_MATCHED_DEFAULT_{self.default_effect}"
        else:
            reason = top["reason_code"]
        return Verdict(
            effect=worst,
            reason_code=reason,
            matched_rules=matched,
            policy_version=self.doc["version"],
            policy_hash=self.policy_hash,
            defer_until=defer_until,
            approver_role=approver if worst == "REQUIRE_APPROVAL" else None,
        )

    @staticmethod
    def _defer_target(rule: dict, ctx: dict, now: datetime) -> str:
        raw = rule.get("defer_to") or "next_local_time:09:00"
        if raw == "upi_next_allowed":
            return next_upi_offpeak(now).isoformat()
        if raw == "pdn_ready_at":
            elapsed = ctx.get("pdn_elapsed_hours")
            if isinstance(elapsed, (int, float)) and elapsed >= 0:
                wait = max(0.0, constants.PDN_MIN_HOURS - elapsed)
            else:
                wait = float(constants.PDN_MIN_HOURS)
            return (as_ist(now) + timedelta(hours=wait + 0.25)).isoformat()
        if raw.startswith("next_local_time:"):
            try:
                hour, minute = raw.split(":", 1)[1].split(":")
                local = as_ist(now).replace(hour=int(hour), minute=int(minute), second=0, microsecond=0)
                if local <= as_ist(now):
                    local += timedelta(days=1)
                return local.isoformat()
            except (ValueError, IndexError):
                pass
        return next_window_open(now).isoformat()


_ENGINE: PolicyEngine | None = None


def get_engine() -> PolicyEngine:
    global _ENGINE
    if _ENGINE is None:
        _ENGINE = PolicyEngine()
    return _ENGINE
