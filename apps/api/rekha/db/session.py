from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime

from sqlalchemy import DateTime, String, create_engine, event
from sqlalchemy.orm import Session, object_mapper, sessionmaker
from sqlalchemy.orm.exc import UnmappedInstanceError

from rekha.config import settings
from rekha.db.models import Base
from rekha.db.time import as_utc, coerce_utc
from rekha.db.types import TzDateTime

_ENGINE = None
_SESSION = None


def sqlalchemy_url(url: str) -> str:
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://") :]
    scheme, sep, rest = url.partition("://")
    if sep and scheme == "postgresql":
        return f"postgresql+psycopg://{rest}"
    return url


def get_engine():
    global _ENGINE
    if _ENGINE is None:
        url = sqlalchemy_url(settings.database_url)
        kwargs: dict = {"future": True}
        if url.startswith("sqlite"):
            kwargs["connect_args"] = {"check_same_thread": False, "timeout": 15}
        _ENGINE = create_engine(url, **kwargs)
        if url.startswith("sqlite"):
            @event.listens_for(_ENGINE, "connect")
            def _sqlite_pragma(dbapi_connection, _record):
                cursor = dbapi_connection.cursor()
                cursor.execute("PRAGMA journal_mode=WAL")
                cursor.execute("PRAGMA busy_timeout=15000")
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.close()
    return _ENGINE


def get_session() -> Session:
    global _SESSION
    if _SESSION is None:
        _SESSION = sessionmaker(bind=get_engine(), expire_on_commit=False, future=True)
    return _SESSION()


@event.listens_for(Session, "before_flush")
def _coerce_datetimes(session, _flush_context, _instances) -> None:
    for obj in list(session.new) + list(session.dirty):
        try:
            mapper = object_mapper(obj)
        except UnmappedInstanceError:
            continue
        for col in mapper.columns:
            val = getattr(obj, col.key, None)
            if isinstance(col.type, (DateTime, TzDateTime)):
                if val is None:
                    continue
                if isinstance(val, datetime):
                    coerced = as_utc(val)
                else:
                    try:
                        coerced = coerce_utc(val)
                    except (TypeError, ValueError):
                        continue
                if coerced is not None and coerced is not val:
                    setattr(obj, col.key, coerced)
            elif isinstance(val, str) and isinstance(col.type, String) and "\x00" in val:
                setattr(obj, col.key, val.replace("\x00", ""))


def init_db() -> None:
    engine = get_engine()
    Base.metadata.create_all(engine)
    from rekha.db.migrate import apply

    apply(engine)


@contextmanager
def session_scope() -> Iterator[Session]:
    session = get_session()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def reset_engine() -> None:
    """Test helper: drop cached engine/session so a new DATABASE_URL binds."""
    global _ENGINE, _SESSION
    _ENGINE = None
    _SESSION = None
