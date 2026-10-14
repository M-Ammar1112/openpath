"""Database engine/session management.

Sync SQLAlchemy sessions (SQLite by default, PostgreSQL via DATABASE_URL).
SQLite gets WAL mode + foreign keys on for sane concurrent local reads.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.config import settings

_engine: Engine | None = None
_SessionFactory: sessionmaker[Session] | None = None


def _ensure_sqlite_dir(url: str) -> None:
    if url.startswith("sqlite:///"):
        raw = url.removeprefix("sqlite:///")
        if raw and raw != ":memory:":
            Path(raw).expanduser().resolve().parent.mkdir(parents=True, exist_ok=True)


def get_engine() -> Engine:
    """Create (once) and return the global engine."""
    global _engine, _SessionFactory
    if _engine is None:
        url = settings.database_url
        _ensure_sqlite_dir(url)
        kwargs: dict[str, object] = {"future": True, "pool_pre_ping": True}
        if url.startswith("sqlite"):
            kwargs["connect_args"] = {"check_same_thread": False}
        _engine = create_engine(url, **kwargs)  # type: ignore[arg-type]
        if url.startswith("sqlite"):
            _register_sqlite_pragmas(_engine)
        _SessionFactory = sessionmaker(bind=_engine, expire_on_commit=False, future=True)
    return _engine


def _register_sqlite_pragmas(engine: Engine) -> None:
    @event.listens_for(engine, "connect")
    def _set_pragmas(dbapi_connection: object, _record: object) -> None:  # pragma: no cover
        cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.close()


def get_session_factory() -> sessionmaker[Session]:
    get_engine()
    assert _SessionFactory is not None
    return _SessionFactory


def session_scope() -> Iterator[Session]:
    """Context manager: commit on success, rollback on error."""
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def reset_engine() -> None:
    """Dispose the engine (used by tests when swapping DATABASE_URL)."""
    global _engine, _SessionFactory
    if _engine is not None:
        _engine.dispose()
    _engine = None
    _SessionFactory = None


@contextmanager
def session() -> Iterator[Session]:
    yield from session_scope()