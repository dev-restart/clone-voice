from __future__ import annotations

from contextlib import contextmanager
from functools import lru_cache
from threading import Lock
from typing import Iterator

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import Settings, get_settings
from app.db.models import Base

_schema_init_lock = Lock()


@lru_cache(maxsize=16)
def get_engine_for_url(database_url: str) -> Engine:
    connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
    return create_engine(database_url, connect_args=connect_args, future=True)


def get_engine(settings: Settings | None = None) -> Engine:
    settings = settings or get_settings()
    settings.storage_dir.mkdir(parents=True, exist_ok=True)
    return get_engine_for_url(settings.resolved_database_url)


@lru_cache(maxsize=16)
def get_session_factory(database_url: str):
    return sessionmaker(bind=get_engine_for_url(database_url), expire_on_commit=False, future=True)


def init_db(settings: Settings | None = None) -> None:
    # The first browser load requests voices and content concurrently. Without
    # serialization, both requests can try to create the same fresh SQLite table.
    with _schema_init_lock:
        Base.metadata.create_all(get_engine(settings))


@contextmanager
def session_scope(settings: Settings | None = None) -> Iterator[Session]:
    settings = settings or get_settings()
    init_db(settings)
    factory = get_session_factory(settings.resolved_database_url)
    session = factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
