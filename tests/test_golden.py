"""Golden replay: the frozen cohort + golden.json is a real regression
oracle. Any drift in diagnosis, policy or playbooks fails CI with the exact
case ids that moved. Also pins eval reproducibility (same seed, same rupees)."""

from __future__ import annotations

import json

from rekha.engine import RecoveryEngine
from rekha.eval.cohort import generate_cohort, parse_eval_now
from rekha.eval.runner import run_eval
from rekha.paths import FIXTURES_DIR
from rekha.policy import PolicyEngine
from rekha.sandbox import FileInbox, RazorpaySandbox


def _golden_rows() -> list[dict]:
    path = FIXTURES_DIR / "golden.json"
    assert path.exists(), "run `rekha seed` to generate golden.json"
    return json.loads(path.read_text(encoding="utf-8"))


def test_golden_replay_no_drift():
    rows = _golden_rows()
    # Every trap must be present. the old truncation bug silently dropped
    # the last three traps from the golden file.
    traps = {r["trap"] for r in rows if r.get("trap")}
    for expected in (
        "dnd",
        "consent_revoked",
        "hard_decline",
        "late_auth",
        "deemed_transaction",
        "downtime_woodpecker",
        "input_validation",
        "card_invalid_2",
    ):
        assert expected in traps, f"golden.json lost trap {expected}"

    cohort = {c["id"]: c for c in generate_cohort(42)}
    engine = RecoveryEngine(payments=RazorpaySandbox(budget=0), comms=FileInbox(), policy=PolicyEngine(), strategy="rekha")
    drifted = []
    for row in rows:
        case = cohort[row["case_id"]]
        if case.get("duplicate_of"):
            # The runner short-circuits duplicates at ingest with a synthetic
            # DEDUPED verdict before the engine is ever consulted.
            if row["expected_reason"] != "DEDUPED":
                drifted.append({"case_id": row["case_id"], "trap": row.get("trap"), "expected": row["expected_reason"], "actual": "not-deduped"})
            continue
        result = engine.run_case(case, parse_eval_now(case))
        if result.verdict.get("effect") != row["expected_effect"] or result.verdict.get("reason_code") != row["expected_reason"]:
            drifted.append(
                {
                    "case_id": row["case_id"],
                    "trap": row.get("trap"),
                    "expected": (row["expected_effect"], row["expected_reason"]),
                    "actual": (result.verdict.get("effect"), result.verdict.get("reason_code")),
                }
            )
    assert not drifted, f"policy drift detected: {json.dumps(drifted[:10], indent=2)}"


def test_eval_reproducible_same_seed():
    a = run_eval(seed=42, write=False)["report"]
    b = run_eval(seed=42, write=False)["report"]
    assert a["rekha_recovered_paise"] == b["rekha_recovered_paise"]
    assert a["incremental_paise"] == b["incremental_paise"]
    assert a["violation_counts"] == b["violation_counts"]


def test_holdout_arms_disjoint_and_complete():
    cases = generate_cohort(42)
    arms = [c.get("experiment_arm") for c in cases]
    assert set(arms) == {"rekha", "holdout"}
    again = generate_cohort(42)
    assert [c.get("experiment_arm") for c in again] == arms
    scored = [c for c in cases if not c.get("duplicate_of")]
    treat = sum(c["amount_paise"] for c in scored if c["experiment_arm"] == "rekha")
    ctrl = sum(c["amount_paise"] for c in scored if c["experiment_arm"] == "holdout")
    bigger = max(treat, ctrl)
    assert bigger > 0
    assert abs(treat - ctrl) / bigger < 0.12


def test_deferred_not_counted_as_recovered():
    payload = run_eval(seed=42, write=False)
    for row in payload["cases"]:
        if row.get("deferred"):
            assert row["recovered"] is False, f"{row['case_id']} deferred but recovered"
