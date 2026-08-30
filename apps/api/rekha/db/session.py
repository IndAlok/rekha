from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from rekha.config import settings
from rekha.db.models import Base

_ENGINE = None
_SESSION = None


def get_engine():
    global _ENGINE
    if _ENGINE is None:
        kwargs: dict = {"future": True}
        if settings.database_url.startswith("sqlite"):
            kwargs["connect_args"] = {"check_same_thread": False, "timeout": 15}
        _ENGINE = create_engine(settings.database_url, **kwargs)
        if settings.database_url.startswith("sqlite"):
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
