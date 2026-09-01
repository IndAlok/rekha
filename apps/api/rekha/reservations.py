from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Slot:
    customer_id: str
    window_bucket: str
    channel: str


class ContactReservation:
    """One send slot per customer, window, and channel."""

    def __init__(self) -> None:
        self._held: set[Slot] = set()

    def reserve(self, slot: Slot) -> bool:
        if slot in self._held:
            return False
        self._held.add(slot)
        return True

    def confirm(self, slot: Slot) -> None:
        self._held.add(slot)

    def release(self, slot: Slot) -> None:
        self._held.discard(slot)
