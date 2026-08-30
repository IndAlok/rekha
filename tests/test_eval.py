from rekha.eval.runner import run_eval


def test_eval_invariants_and_lift():
    payload = run_eval(seed=42, write=False)
    report = payload["report"]
    assert report["n"] == 200
    assert report["invariants_passed"], report["violation_counts"]
    assert report["incremental_paise"] > 0
    assert report["rekha_recovered_paise"] > report["holdout_recovered_paise"]
    assert report["rekha_recovered_paise"] <= report["oracle_recovered_paise"]


def test_scheduled_iff_credits_modeled_payout():
    payload = run_eval(seed=42, write=False)
    hits = [
        row
        for row in payload["cases"]
        if row.get("scheduled")
        and row.get("proposal", {}).get("action") == "silent_retry_same_instrument"
        and row.get("recovered")
    ]
    assert hits, "eval must credit a modeled payout when the persona would pay on send_after"
