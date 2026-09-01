"""Downtime API first, then slice statistics.

A slice is degraded only when its success rate is significantly below the
slice's own baseline (Wilson lower bound), confirmed in >= 3 of the last 5
windows (hysteresis. no flapping), and ranked by rupees lost, not z-score.
First attempts only: retries never feed the monitor, or the monitor would
feed the retries.
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class SliceStats:
    attempts: int = 0
    successes: int = 0
    baseline_fail: float = 0.15  # trailing baseline; learned, not configured truth
    rupees_at_risk: int = 0
    window_history: list[bool] = field(default_factory=list)  # degraded per window

    @property
    def fail_rate(self) -> float:
        if self.attempts == 0:
            return 0.0
        return 1.0 - (self.successes / self.attempts)


@dataclass
class DegradationMonitor:
    """First-attempt slices by issuer, method, amount band, UPI PSP, and hour."""

    slices: dict[str, SliceStats] = field(default_factory=dict)
    downtime_keys: set[str] = field(default_factory=set)
    min_attempts: int = 30
    confirm_windows: int = 3
    lookback_windows: int = 5

    def ingest_downtime_api(self, payload: dict) -> None:
        for item in payload.get("items") or payload.get("downtimes") or []:
            key = _slice_key(
                issuer=item.get("issuer") or item.get("bank"),
                method=item.get("method"),
                psp=item.get("psp"),
                status=item.get("status") or item.get("begin"),
            )
            if item.get("status") in {"started", "active", None} and not item.get("end"):
                self.downtime_keys.add(key)
            if item.get("end") or item.get("status") == "resolved":
                self.downtime_keys.discard(key)

    def record(
        self,
        *,
        issuer: str | None,
        method: str | None,
        psp: str | None,
        success: bool,
        amount_paise: int = 0,
        attempt_no: int = 1,
    ) -> None:
        if attempt_no != 1:
            return  # retries never feed the monitor
        key = _slice_key(issuer=issuer, method=method, psp=psp)
        stats = self.slices.setdefault(key, SliceStats())
        stats.attempts += 1
        stats.successes += int(success)
        stats.rupees_at_risk += 0 if success else int(amount_paise)

    def close_window(self, *, issuer: str | None = None, method: str | None = None, psp: str | None = None) -> None:
        """End a monitoring window: roll the degraded bit into history."""
        key = _slice_key(issuer=issuer, method=method, psp=psp)
        stats = self.slices.get(key)
        if stats is None:
            return
        stats.window_history.append(self._window_degraded(stats))
        stats.window_history = stats.window_history[-self.lookback_windows :]
        # Re-learn the baseline from healthy windows only.
        if not stats.window_history[-1]:
            stats.baseline_fail = 0.9 * stats.baseline_fail + 0.1 * stats.fail_rate

    def _window_degraded(self, stats: SliceStats) -> bool:
        if stats.attempts < self.min_attempts:
            return False
        from rekha.eval.stats import wilson

        _point, lo, _hi = wilson(int(stats.successes), int(stats.attempts))
        # Significantly below the slice's own success baseline.
        return lo < 1.0 - stats.baseline_fail

    def incident(self, *, issuer: str | None = None, method: str | None = None, psp: str | None = None) -> bool:
        key = _slice_key(issuer=issuer, method=method, psp=psp)
        if key in self.downtime_keys or "global" in self.downtime_keys:
            return True
        stats = self.slices.get(key)
        if not stats or len(stats.window_history) < self.confirm_windows:
            return False
        return sum(stats.window_history[-self.confirm_windows :]) >= self.confirm_windows

    def ranked_by_rupees(self) -> list[dict]:
        """Severity is money, not statistics: rank by rupees at risk."""
        rows = [
            {
                "slice": key,
                "rupees_at_risk_paise": stats.rupees_at_risk,
                "fail_rate": round(stats.fail_rate, 3),
                "baseline_fail": round(stats.baseline_fail, 3),
                "attempts": stats.attempts,
                "incident": self.incident(),
            }
            for key, stats in self.slices.items()
        ]
        return sorted(rows, key=lambda r: r["rupees_at_risk_paise"], reverse=True)


def _slice_key(*, issuer: str | None = None, method: str | None = None, psp: str | None = None, status: str | None = None) -> str:
    if status == "global":
        return "global"
    return "|".join([issuer or "*", method or "*", psp or "*"])


MONITOR = DegradationMonitor()
