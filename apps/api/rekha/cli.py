from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from rekha.audit import verify_rows
from rekha.eval.cohort import generate_cohort
from rekha.eval.runner import run_eval
from rekha.paths import ARTIFACTS_DIR, FIXTURES_DIR


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="rekha", description="Rekha bounded recovery kernel")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("seed", help="Write frozen cohort_200.jsonl and holiday fixtures")
    ev = sub.add_parser("eval", help="Run the 200-case holdout eval (Groq off, no Razorpay keys)")
    ev.add_argument("--seed", type=int, default=42)
    av = sub.add_parser("audit-verify", help="Verify the hash-chained audit log")
    av.add_argument("--path", type=Path, default=None)
    av.add_argument("--tamper", action="store_true", help="Mutate one row then re-verify (demo)")

    args = parser.parse_args(argv)
    if args.cmd == "seed":
        return cmd_seed()
    if args.cmd == "eval":
        return cmd_eval(args.seed)
    if args.cmd == "audit-verify":
        return cmd_audit(args.path, args.tamper)
    return 1


def cmd_seed() -> int:
    FIXTURES_DIR.mkdir(parents=True, exist_ok=True)
    cases = generate_cohort(42)
    path = FIXTURES_DIR / "cohort_200.jsonl"
    with path.open("w", encoding="utf-8") as fh:
        for case in cases:
            fh.write(json.dumps(case, default=str) + "\n")
    holidays = FIXTURES_DIR / "holidays_in_2026.json"
    if not holidays.exists():
        holidays.write_text(
            json.dumps(
                {
                    "timezone": "Asia/Kolkata",
                    "dates": [
                        "2026-01-26",
                        "2026-03-03",
                        "2026-03-31",
                        "2026-04-03",
                        "2026-08-15",
                        "2026-10-02",
                        "2026-10-20",
                        "2026-11-08",
                        "2026-12-25",
                    ],
                    "note": "Settlement-holiday subset for eval. Confirm against NPCI/RBI calendar before live use.",
                    "grade": "secondary",
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
    sample = FIXTURES_DIR / "webhooks" / "payment_failed.json"
    sample.parent.mkdir(parents=True, exist_ok=True)
    sample.write_text(
        json.dumps(
            {
                "event": "payment.failed",
                "payload": {
                    "customer": {
                        "id": "cust_demo_failed",
                        "name": "Riya",
                        "contact": "+919800000001",
                        "consent": True,
                    },
                    "payment": {
                        "entity": {
                            "id": "pay_demo_failed",
                            "entity": "payment",
                            "amount": 129900,
                            "currency": "INR",
                            "status": "failed",
                            "error_reason": "insufficient_funds",
                            "error_source": "customer",
                            "order_id": "order_demo",
                        }
                    },
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"wrote {path} ({len(cases)} cases)")
    payload = run_eval(seed=42, write=True, write_golden=True)
    print(f"golden + eval report n={payload['report']['n']} incremental_inr={payload['report']['incremental_paise']/100:.2f}")
    return 0


def cmd_eval(seed: int) -> int:
    payload = run_eval(seed=seed, write=True, write_golden=False)
    report = payload["report"]
    print(f"n={report['n']} incremental_inr={report['incremental_paise']/100:.2f}")
    print(f"rekha={report['rekha_recovered_paise']/100:.2f} holdout={report['holdout_recovered_paise']/100:.2f} oracle={report['oracle_recovered_paise']/100:.2f}")
    print(f"invariants={'PASS' if report['invariants_passed'] else 'FAIL'} violations={report['violation_counts']}")
    print(f"report: {ARTIFACTS_DIR / 'eval' / 'report.md'}")
    if not report["invariants_passed"]:
        return 2
    if report["incremental_paise"] < 0:
        print("warning: incremental lift is negative. holdout beat treatment")
        return 3
    return 0


def cmd_audit(path: Path | None, tamper: bool) -> int:
    target = path or (ARTIFACTS_DIR / "eval" / "audit.json")
    if not target.exists():
        print("no audit file. run `rekha eval` first", file=sys.stderr)
        return 1
    rows = json.loads(target.read_text(encoding="utf-8"))
    ok, msg = verify_rows(rows)
    print(f"verify: {ok} ({msg}) rows={len(rows)}")
    if tamper and rows:
        rows[min(3, len(rows) - 1)]["action"] = "TAMPERED"
        ok2, msg2 = verify_rows(rows)
        print(f"after tamper: {ok2} ({msg2})")
        return 0 if ok and not ok2 else 4
    return 0 if ok else 5


if __name__ == "__main__":
    raise SystemExit(main())
