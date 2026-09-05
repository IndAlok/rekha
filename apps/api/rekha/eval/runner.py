from __future__ import annotations

import json
from collections import Counter
from datetime import UTC, datetime

from rekha.audit import AuditChain, verify_rows
from rekha.engine import CaseResult, RecoveryEngine
from rekha.eval.cohort import generate_cohort, parse_eval_now
from rekha.eval.stats import bca_bootstrap_sum_diff, mde_two_proportion, newcombe_diff, wilson
from rekha.paths import ARTIFACTS_DIR, FIXTURES_DIR
from rekha.policy import get_engine
from rekha.sandbox import FileInbox, RazorpaySandbox


def run_eval(*, seed: int = 42, write: bool = True, write_golden: bool = False) -> dict:
    """200-case holdout. persist=False, so Groq is never called."""
    cases = generate_cohort(seed)
    if write_golden:
        FIXTURES_DIR.mkdir(parents=True, exist_ok=True)
        _write_jsonl(FIXTURES_DIR / "cohort_200.jsonl", cases)

    policy = get_engine()
    inbox = FileInbox()
    sandbox = RazorpaySandbox(budget=0)
    audit = AuditChain()
    rekha_engine = RecoveryEngine(
        payments=sandbox, comms=inbox, policy=policy, audit=audit, strategy="rekha", persist=False
    )
    holdout_engine = RecoveryEngine(
        payments=RazorpaySandbox(budget=0),
        comms=FileInbox(),
        policy=policy,
        audit=AuditChain(),
        strategy="holdout",
        persist=False,
    )

    rekha_rows = []
    holdout_rows = []
    skipped = 0
    for case in cases:
        if case.get("duplicate_of"):
            skipped += 1
            rekha_rows.append(_deduped(case, "rekha"))
            holdout_rows.append(_deduped(case, "holdout"))
            continue
        now = parse_eval_now(case)
        rekha_rows.append(rekha_engine.run_case(case, now))
        holdout_rows.append(holdout_engine.run_case(case, now))

    by_id = {c["id"]: c for c in cases}

    treat_idx = [i for i, c in enumerate(cases) if c.get("experiment_arm") == "rekha" and not c.get("duplicate_of")]
    ctrl_idx = [i for i, c in enumerate(cases) if c.get("experiment_arm") == "holdout" and not c.get("duplicate_of")]

    treat_wins = sum(1 for i in treat_idx if rekha_rows[i].recovered)
    ctrl_wins = sum(1 for i in ctrl_idx if holdout_rows[i].recovered)
    n_t, n_c = len(treat_idx), len(ctrl_idx)
    treat_amt = [rekha_rows[i].amount_paise if rekha_rows[i].recovered else 0 for i in treat_idx]
    ctrl_amt = [holdout_rows[i].amount_paise if holdout_rows[i].recovered else 0 for i in ctrl_idx]
    treat_rupees, ctrl_rupees = sum(treat_amt), sum(ctrl_amt)

    rekha_amt = [r.amount_paise if r.recovered else 0 for r in rekha_rows]
    holdout_amt = [r.amount_paise if r.recovered else 0 for r in holdout_rows]
    oracle_amt = []
    for r in rekha_rows:
        case = by_id[r.case_id]
        oracle_amt.append(case["amount_paise"] if case.get("oracle_recoverable") or case.get("already_paid") else 0)

    n = len(rekha_rows)
    rekha_wins = sum(1 for r in rekha_rows if r.recovered)
    holdout_wins = sum(1 for r in holdout_rows if r.recovered)
    oracle_wins = sum(1 for a in oracle_amt if a > 0)
    at_risk = sum(c["amount_paise"] for c in cases if not c.get("duplicate_of") and not c.get("already_paid"))
    rekha_rupees = sum(rekha_amt)
    holdout_rupees = sum(holdout_amt)
    oracle_rupees = sum(oracle_amt)

    _, rec_lo, rec_hi = wilson(rekha_wins, n)
    rate_diff, rate_lo, rate_hi = newcombe_diff(treat_wins, max(1, n_t), ctrl_wins, max(1, n_c))
    lift, lift_lo, lift_hi = bca_bootstrap_sum_diff(treat_amt, ctrl_amt)
    mde = mde_two_proportion(max(1, min(n_t, n_c)))

    violations = [v for r in rekha_rows for v in r.violations]
    beat_oracle = rekha_rupees > oracle_rupees
    if beat_oracle:
        violations.append("beat_oracle_rupees")

    blocked = [
        {
            "case_id": r.case_id,
            "action": r.proposal.get("action"),
            "rule": r.verdict.get("reason_code"),
            "matched": r.verdict.get("matched_rules"),
            "trap": by_id[r.case_id].get("trap"),
        }
        for r in rekha_rows
        if r.blocked
    ]

    attempts = sum(1 for r in rekha_rows if r.executed)
    scheduled = sum(1 for r in rekha_rows if r.scheduled or r.deferred)
    report = {
        "generated_at": datetime.now(UTC).isoformat(),
        "seed": seed,
        "n": n,
        "skipped_duplicates": skipped,
        "policy_version": policy.doc["version"],
        "policy_hash": policy.policy_hash,
        "at_risk_paise": at_risk,
        "design": {
            "primary": "hash_arm_holdout",
            "assignment": "amount-stratified lighter-arm greedy, hash(customer_id) on ties, fixed at cohort build",
            "treatment_n": n_t,
            "control_n": n_c,
            "treatment_recovered_paise": treat_rupees,
            "control_recovered_paise": ctrl_rupees,
            "treatment_recoveries": treat_wins,
            "control_recoveries": ctrl_wins,
            "note": (
                "Primary numbers compare disjoint arms: agent vs status-quo on "
                "different customers. The paired all-cases run below is a "
                "diagnostic only."
            ),
        },
        "rekha_recovered_paise": rekha_rupees,
        "holdout_recovered_paise": holdout_rupees,
        "oracle_recovered_paise": oracle_rupees,
        "incremental_paise": treat_rupees - ctrl_rupees,
        "incremental_scope": "treatment_arm_minus_control_arm",
        "rekha_recoveries": rekha_wins,
        "holdout_recoveries": holdout_wins,
        "oracle_recoveries": oracle_wins,
        "rekha_rate": rekha_wins / n if n else 0,
        "holdout_rate": holdout_wins / n if n else 0,
        "treatment_rate": treat_wins / n_t if n_t else 0,
        "control_rate": ctrl_wins / n_c if n_c else 0,
        "rekha_rate_wilson": [rec_lo, rec_hi],
        "rate_lift_newcombe": {"diff": rate_diff, "lo": rate_lo, "hi": rate_hi},
        "rupee_lift_bca": {"obs": lift, "lo": lift_lo, "hi": lift_hi},
        "oracle_ceiling_pct": (rekha_rupees / oracle_rupees) if oracle_rupees else 0,
        "scheduled_cases": scheduled,
        "scheduled_note": (
            "Quiet-hour DEFER is not recovered. A future send_after is scheduled. "
            "Eval credits a modeled payout only when the persona would pay on that date. "
            "The rupee BCa resamples each arm independently."
        ),
        "mde_honesty": {
            "n_per_arm": min(n_t, n_c),
            "mde_abs_rate": mde,
            "note": (
                f"Disjoint arms: n={n_t} treatment / {n_c} control. The smaller arm "
                f"can detect roughly {mde:.0%} absolute recovery-rate difference at "
                "80% power, not 4pp. Do not claim p<0.05 on this synthetic batch."
            ),
        },
        "attempts": attempts,
        "paise_per_attempt": (rekha_rupees / attempts) if attempts else 0,
        "violations": violations,
        "violation_counts": dict(Counter(violations)),
        "invariants_passed": not violations and not beat_oracle,
        "engines": dict(Counter(r.proposal.get("engine") for r in rekha_rows)),
        "blocked_actions": blocked,
        "exception_list": _exceptions(rekha_rows, by_id),
        "replay_case_id": next(
            (r.case_id for r in rekha_rows if r.recovered and r.proposal.get("engine") == "payment_doctor"),
            rekha_rows[0].case_id if rekha_rows else None,
        ),
        "advisor": "off",
    }

    cases_out = []
    for r, h in zip(rekha_rows, holdout_rows, strict=True):
        case = by_id[r.case_id]
        cases_out.append(
            {
                **r.to_dict(),
                "holdout_recovered": h.recovered,
                "holdout_action": h.proposal.get("action"),
                "oracle_recoverable": case.get("oracle_recoverable"),
                "trap": case.get("trap"),
                "persona": case.get("persona"),
                "experiment_arm": case.get("experiment_arm"),
                "loss_class": case.get("loss_class"),
            }
        )

    ok, audit_msg = verify_rows(audit.rows)
    payload = {
        "report": report,
        "cases": cases_out,
        "audit": audit.rows,
        "audit_ok": ok,
        "audit_msg": audit_msg,
        "promises": [c for c in cases if c.get("loss_class") == "promise_to_pay"],
    }

    if write:
        out = ARTIFACTS_DIR / "eval"
        out.mkdir(parents=True, exist_ok=True)
        (out / "latest.json").write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
        (out / "report.md").write_text(_markdown(report), encoding="utf-8")
        (out / "audit.json").write_text(json.dumps(audit.rows, indent=2, default=str), encoding="utf-8")
    if write_golden:
        _write_golden(cases, rekha_rows)
    return payload


def _exceptions(rows, by_id) -> list[dict]:
    out = []
    for r in rows:
        case = by_id[r.case_id]
        if case.get("trap") or r.blocked or r.deferred or r.scheduled or r.violations:
            out.append(
                {
                    "case_id": r.case_id,
                    "trap": case.get("trap"),
                    "effect": r.verdict.get("effect"),
                    "reason": r.verdict.get("reason_code"),
                    "proposal": r.proposal.get("action"),
                    "recovered": r.recovered,
                    "scheduled": r.scheduled,
                    "violations": r.violations,
                }
            )
    return out


def _write_jsonl(path, rows: list) -> None:
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, default=str) + "\n")


def _write_golden(cases: list[dict], rows: list) -> None:
    """Every case, traps guaranteed. No silent truncation."""
    labels = []
    for case, row in zip(cases, rows, strict=True):
        labels.append(
            {
                "case_id": case["id"],
                "trap": case.get("trap"),
                "persona": case.get("persona"),
                "expected_effect": row.verdict.get("effect"),
                "expected_reason": row.verdict.get("reason_code"),
                "action": row.proposal.get("action"),
            }
        )
    FIXTURES_DIR.mkdir(parents=True, exist_ok=True)
    (FIXTURES_DIR / "golden.json").write_text(json.dumps(labels, indent=2), encoding="utf-8")


def _deduped(case: dict, strategy: str) -> CaseResult:
    return CaseResult(
        case_id=case["id"],
        strategy=strategy,
        diagnosis={},
        proposal={"action": "suppress_and_stop", "reason": "duplicate_webhook", "engine": "ingest"},
        verdict={"effect": "DENY", "reason_code": "DEDUPED"},
        executed=False,
        recovered=False,
        recovery_source="none",
        amount_paise=int(case.get("amount_paise") or 0),
        blocked=True,
        notes=["duplicate_webhook"],
    )


def _markdown(report: dict) -> str:
    inv = "PASS" if report["invariants_passed"] else "FAIL"
    d = report["design"]
    return f"""# Rekha eval report

Generated {report["generated_at"]}
Policy `{report["policy_version"]}` hash `{report["policy_hash"]}`
Seed {report["seed"]}. n={report["n"]}. Duplicate webhooks scored as no-ops: {report["skipped_duplicates"]}.

## Design

Primary: hash-arm holdout. {d["treatment_n"]} customers see the agent, {d["control_n"]} see the status-quo
strategy (assignment amount-stratified, hash tie-break, fixed at cohort build).
{d["note"]}

## Money (primary, disjoint arms)

| | paise | INR |
|---|---:|---:|
| Treatment (agent) recovered | {d["treatment_recovered_paise"]} | {d["treatment_recovered_paise"]/100:.2f} |
| Control (status quo) recovered | {d["control_recovered_paise"]} | {d["control_recovered_paise"]/100:.2f} |
| Incremental lift | {report["incremental_paise"]} | {report["incremental_paise"]/100:.2f} |

## Money (paired diagnostic, all cases)

| | paise | INR |
|---|---:|---:|
| At risk | {report["at_risk_paise"]} | {report["at_risk_paise"]/100:.2f} |
| Rekha recovered | {report["rekha_recovered_paise"]} | {report["rekha_recovered_paise"]/100:.2f} |
| Razorpay default holdout | {report["holdout_recovered_paise"]} | {report["holdout_recovered_paise"]/100:.2f} |
| Oracle ceiling | {report["oracle_recovered_paise"]} | {report["oracle_recovered_paise"]/100:.2f} |
| Rekha / oracle | | {report["oracle_ceiling_pct"]:.1%} |

## Rates

- Treatment {d["treatment_recoveries"]}/{d["treatment_n"]} ({report["treatment_rate"]:.1%}) vs control {d["control_recoveries"]}/{d["control_n"]} ({report["control_rate"]:.1%})
- Rate lift, Newcombe {report["rate_lift_newcombe"]["diff"]:.1%} [{report["rate_lift_newcombe"]["lo"]:.1%}, {report["rate_lift_newcombe"]["hi"]:.1%}]
- Rupee lift, two-sample BCa ₹{report["rupee_lift_bca"]["obs"]/100:.2f} [₹{report["rupee_lift_bca"]["lo"]/100:.2f}, ₹{report["rupee_lift_bca"]["hi"]/100:.2f}]. Arms are resampled independently. The rupee interval can include zero.
- Scheduled or deferred, not recovered: {report["scheduled_cases"]}

## Honesty

{report["mde_honesty"]["note"]}

## Advisor

Off. This batch never called Groq. Live cases may attach a reason if the model agrees with the playbook. The tool still came from the playbook.

## Invariants

{inv}. violations={report["violation_counts"] or 0}

## Engines

{json.dumps(report["engines"], indent=2)}

Replay case `{report["replay_case_id"]}`
"""


def verify_audit_file(path=None) -> tuple[bool, str]:

    path = path or (ARTIFACTS_DIR / "eval" / "audit.json")
    if not path.exists():
        return False, f"missing {path}"
    rows = json.loads(path.read_text(encoding="utf-8"))
    return verify_rows(rows)
