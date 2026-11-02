from collections.abc import Iterator

from sqlalchemy import create_engine, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings

engine = create_engine(get_settings().database_url, pool_pre_ping=True)
SessionLocal = sessionmaker(engine, expire_on_commit=False)


class Base(DeclarativeBase):
    pass


# Columns added to `judgments` for ingestion provenance (ingest/); additive, so existing data is kept.
JUDGMENT_COLUMNS = [
    ("source", "VARCHAR"), ("court_code", "VARCHAR"), ("bench", "VARCHAR"), ("cnr", "VARCHAR"),
    ("case_type", "VARCHAR"), ("headnote", "TEXT"), ("acts", "JSONB DEFAULT '[]'::jsonb"),
    ("topic_tags", "JSONB DEFAULT '[]'::jsonb"), ("property_score", "DOUBLE PRECISION"),
    ("filter_evidence", "JSONB DEFAULT '{}'::jsonb"), ("language", "VARCHAR"), ("pdf_key", "TEXT"),
    ("summary_status", "VARCHAR DEFAULT 'none'"), ("embedding_model", "VARCHAR"), ("pipeline_version", "VARCHAR"),
    ("ingested_at", "TIMESTAMPTZ"),
]


def init_db() -> None:
    """Create the pgvector extension and all tables. Fine for an MVP; switch to Alembic once the schema settles."""
    from app import models  # noqa: F401  (registers the tables on Base.metadata)

    with engine.begin() as conn:
        conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
    Base.metadata.create_all(engine)
    # create_all doesn't add columns to existing tables; small additive changes until Alembic is set up.
    with engine.begin() as conn:
        conn.execute(text("ALTER TABLE case_documents ADD COLUMN IF NOT EXISTS page_info JSONB DEFAULT '[]'::jsonb"))
        conn.execute(text("ALTER TABLE case_documents ADD COLUMN IF NOT EXISTS understanding JSONB DEFAULT '{}'::jsonb"))
        conn.execute(text("ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS sources JSONB DEFAULT '[]'::jsonb"))
        conn.execute(text("ALTER TABLE chat_messages ADD COLUMN IF NOT EXISTS mentions JSONB DEFAULT '[]'::jsonb"))
        for column, kind in JUDGMENT_COLUMNS:
            conn.execute(text(f"ALTER TABLE judgments ADD COLUMN IF NOT EXISTS {column} {kind}"))


def get_db() -> Iterator[Session]:
    """FastAPI dependency: one session per request."""
    with SessionLocal() as session:
        yield session
