from __future__ import annotations

from sqlalchemy import DateTime
from sqlalchemy.types import TypeDecorator

from rekha.db.time import coerce_utc, maybe_utc


class TzDateTime(TypeDecorator):
    """Every bind is UTC-aware. SQLite may still return naive values."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, _dialect):
        return coerce_utc(value)

    def process_result_value(self, value, _dialect):
        return maybe_utc(value)
