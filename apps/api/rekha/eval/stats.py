from __future__ import annotations

import math
import random


def wilson(successes: int, n: int, z: float = 1.96) -> tuple[float, float, float]:
    if n <= 0:
        return 0.0, 0.0, 0.0
    p = successes / n
    z2 = z * z
    denom = 1 + z2 / n
    centre = (p + z2 / (2 * n)) / denom
    spread = z * math.sqrt((p * (1 - p) + z2 / (4 * n)) / n) / denom
    return p, max(0.0, centre - spread), min(1.0, centre + spread)


def newcombe_diff(x1: int, n1: int, x2: int, n2: int, z: float = 1.96) -> tuple[float, float, float]:
    """Newcombe interval on the difference of two rates."""
    p1, l1, u1 = wilson(x1, n1, z)
    p2, l2, u2 = wilson(x2, n2, z)
    diff = p1 - p2
    lower = diff - math.sqrt((p1 - l1) ** 2 + (u2 - p2) ** 2)
    upper = diff + math.sqrt((u1 - p1) ** 2 + (p2 - l2) ** 2)
    return diff, lower, upper


def bca_bootstrap_sum_diff(
    treatment: list[int],
    holdout: list[int],
    *,
    n_boot: int = 2000,
    alpha: float = 0.05,
    seed: int = 42,
) -> tuple[int, float, float]:
    """BCa interval on two-sample rupee lift. Arms are resampled independently."""
    rng = random.Random(seed)
    n_t, n_h = len(treatment), len(holdout)
    obs = sum(treatment) - sum(holdout)
    if n_t == 0 and n_h == 0:
        return 0, 0.0, 0.0
    if n_t == 0 or n_h == 0:
        return obs, float(obs), float(obs)
    boots: list[int] = []
    for _ in range(n_boot):
        t_idx = [rng.randrange(n_t) for _ in range(n_t)]
        h_idx = [rng.randrange(n_h) for _ in range(n_h)]
        boots.append(sum(treatment[i] for i in t_idx) - sum(holdout[i] for i in h_idx))
    boots.sort()
    total_t, total_h = sum(treatment), sum(holdout)
    jack = []
    for i in range(n_t):
        jack.append((total_t - treatment[i]) - total_h)
    for j in range(n_h):
        jack.append(total_t - (total_h - holdout[j]))
    n = len(jack)
    jack_mean = sum(jack) / n
    num = sum((jack_mean - j) ** 3 for j in jack)
    den = sum((jack_mean - j) ** 2 for j in jack)
    acc = num / (6.0 * (den ** 1.5)) if den > 0 else 0.0
    prop_less = sum(1 for b in boots if b < obs) / n_boot
    prop_less = min(1 - 1e-6, max(1e-6, prop_less))
    z0 = _inv_norm(prop_less)
    z_lo = _inv_norm(alpha / 2)
    z_hi = _inv_norm(1 - alpha / 2)
    a1 = _norm_cdf(z0 + (z0 + z_lo) / (1 - acc * (z0 + z_lo)))
    a2 = _norm_cdf(z0 + (z0 + z_hi) / (1 - acc * (z0 + z_hi)))
    lo = boots[min(n_boot - 1, max(0, int(a1 * n_boot)))]
    hi = boots[min(n_boot - 1, max(0, int(a2 * n_boot)))]
    return obs, float(lo), float(hi)


def mde_two_proportion(n_per_arm: int, p: float = 0.4, alpha: float = 0.05, power: float = 0.8) -> float:
    """Smallest rate gap this n can detect at the given power."""
    z_a = 1.95996398454
    z_b = 0.841621233572
    if n_per_arm <= 0:
        return 1.0
    return (z_a + z_b) * math.sqrt(2 * p * (1 - p) / n_per_arm)


def _inv_norm(p: float) -> float:
    """Acklam normal quantile."""
    if p <= 0 or p >= 1:
        raise ValueError("p in (0,1)")
    a = [-3.969683028665376e01, 2.209460984245205e02, -2.759285104469687e02, 1.383577518672690e02, -3.066479806614716e01, 2.506628277459239e00]
    b = [-5.447609879822406e01, 1.615858368580409e02, -1.556989798598866e02, 6.680131188771972e01, -1.328068155288572e01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e00, -2.549732386385654e00, 4.374664141464968e00, 2.938163982698783e00]
    d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e00, 3.754408661907416e00]
    plow = 0.02425
    phigh = 1 - plow
    if p < plow:
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / (
            (((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1
        )
    if p <= phigh:
        q = p - 0.5
        r = q * q
        return (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q / (
            ((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r + 1
        )
    q = math.sqrt(-2 * math.log(1 - p))
    return -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / (
        (((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1
    )


def _norm_cdf(x: float) -> float:
    return 0.5 * (1 + math.erf(x / math.sqrt(2)))
