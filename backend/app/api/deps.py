"""FastAPI dependencies shared by routers."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Annotated

from fastapi import Depends
from sqlalchemy.orm import Session

from app.persistence.db import get_session_factory


def get_db() -> Iterator[Session]:
    """Request-scoped session: commits on success, rolls back on error."""
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


# Router annotation: `session: DbSession`
DbSession = Annotated[Session, Depends(get_db)]

__all__ = ["DbSession", "get_db"]

