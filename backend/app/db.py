from collections.abc import Iterator

from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings

engine = create_engine(get_settings().database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


def init_db() -> None:
    """Create the pgvector extension and all tables. Fine for an MVP; switch to Alembic once the schema settles."""
    from app import models  # noqa: F401  (registers the tables on Base.metadata)

    with engine.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    Base.metadata.create_all(engine)
    # create_all doesn't add columns to existing tables; small additive changes until Alembic is set up.
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE case_documents ADD COLUMN IF NOT EXISTS page_info JSONB DEFAULT '[]'::jsonb"))


def get_db() -> Iterator[Session]:
    """FastAPI dependency: one session per request."""
    with SessionLocal() as session:
        yield session
