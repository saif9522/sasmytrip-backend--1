"""
SQLite 3 database connection setup.

Existing SQLite database is preserved on disk at backend/sasmytrip.db.
Do NOT drop tables here — Base.metadata.create_all only creates tables
that don't already exist. Use Alembic (or a manual migration script)
for schema changes once real data exists.
"""
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, declarative_base

SQLALCHEMY_DATABASE_URL = "sqlite:///./sasmytrip.db"

engine = create_engine(
    SQLALCHEMY_DATABASE_URL,
    connect_args={"check_same_thread": False},  # required for SQLite + FastAPI
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    """FastAPI dependency that yields a DB session per request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
