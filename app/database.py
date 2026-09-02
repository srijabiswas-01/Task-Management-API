from collections.abc import Generator

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import settings

connect_args = (
    {"check_same_thread": False, "timeout": 30}
    if settings.database_url.startswith("sqlite")
    else {}
)

engine_options = {
    "connect_args": connect_args,
    # Validate pooled connections before use and retire them before common
    # hosted-Postgres idle timeouts. Never include bound values in exceptions.
    "pool_pre_ping": True,
    "hide_parameters": True,
}
if not settings.database_url.startswith("sqlite"):
    # Keep hosted-Postgres usage predictable on free tiers. A small LIFO pool
    # reuses warm connections without opening a large burst of database sessions.
    engine_options.update(
        pool_size=3,
        max_overflow=2,
        pool_timeout=15,
        pool_recycle=300,
        pool_use_lifo=True,
    )

engine = create_engine(settings.database_url, **engine_options)
if settings.database_url.startswith("sqlite"):
    @event.listens_for(engine, "connect")
    def enable_sqlite_foreign_keys(dbapi_connection, _):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA busy_timeout=30000")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def get_db() -> Generator[Session, None, None]:
    with SessionLocal() as session:
        try:
            yield session
        except Exception:
            session.rollback()
            raise
