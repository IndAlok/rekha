"""Pin the honesty math: Wilson, Newcombe, BCa bootstrap, MDE. against
hand-computed reference values so a sign error can never ship silently."""

from __future__ import annotations

import math

from rekha.eval.stats import bca_bootstrap_sum_diff, mde_two_proportion, newcombe_diff, wilson


def test_wilson_known_value():
    # 7/10, z=1.96: center 0.6443 +/- 0.2480 -> [0.3963, 0.8924] (hand-computed).
    point, lo, hi = wilson(7, 10)
    assert math.isclose(point, 0.7, abs_tol=1e-9)
    assert math.isclose(lo, 0.3963, abs_tol=5e-4)
    assert math.isclose(hi, 0.8924, abs_tol=5e-4)


def test_wilson_degenerate_cases():
    _point, lo, hi = wilson(0, 10)
    assert lo == 0.0 and math.isclose(hi, 0.2775, abs_tol=5e-4)
    _point, lo, hi = wilson(10, 10)
    assert hi == 1.0 and math.isclose(lo, 0.7225, abs_tol=5e-4)


def test_newcombe_diff_matches_sign_and_scale():
    diff, lo, hi = newcombe_diff(70, 100, 50, 100)
    assert math.isclose(diff, 0.20, abs_tol=1e-9)
    assert lo < diff < hi
    assert hi - lo < 0.35  # a 100/100 sample should not give a silly-wide CI


def test_newcombe_identical_rates_bracket_zero():
    diff, lo, hi = newcombe_diff(50, 100, 50, 100)
    assert abs(diff) < 1e-9
    assert lo <= 0 <= hi


def test_bca_bootstrap_reproducible_and_signed():
    treat = [100, 100, 100, 0, 0, 100, 0, 100, 100, 100]
    ctrl = [0, 0, 0, 0, 0, 100, 0, 0, 0, 0]
    obs1, lo1, hi1 = bca_bootstrap_sum_diff(treat, ctrl)
    obs2, lo2, hi2 = bca_bootstrap_sum_diff(treat, ctrl)
    assert (obs1, lo1, hi1) == (obs2, lo2, hi2)  # seeded: deterministic
    assert obs1 == 600
    assert lo1 <= obs1 <= hi1


def test_mde_shrinks_with_n():
    small = mde_two_proportion(50)
    large = mde_two_proportion(5000)
    assert 0 < large < small < 1


def test_mde_reference_scale():
    # ~1000 per arm at 80% power / alpha=0.05 detects roughly 6-9pp.
    assert 0.05 <= mde_two_proportion(1000) <= 0.09


def test_bca_two_sample_unequal_does_not_pair():
    treat = [100, 100, 0]
    ctrl = [0, 0]
    obs, lo, hi = bca_bootstrap_sum_diff(treat, ctrl)
    assert obs == 200
    assert lo <= obs <= hi
