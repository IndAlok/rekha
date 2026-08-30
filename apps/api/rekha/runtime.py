from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta


@dataclass
class RuntimeFlags:
    kill_switch: bool = False
    complaints: list[datetime] = field(default_factory=list)
    whatsapp_quality: str = "green"

    def engage_kill(self) -> None:
        self.kill_switch = True

    def release_kill(self) -> None:
        self.kill_switch = False

    def record_complaint(self, when: datetime) -> None:
        self.complaints.append(when)

    def complaint_throttle(self, now: datetime, window_days: int = 10, threshold: int = 2) -> bool:
        cutoff = now - timedelta(days=window_days)
        recent = [c for c in self.complaints if c >= cutoff]
        self.complaints = recent
        return len(recent) >= threshold


FLAGS = RuntimeFlags()
