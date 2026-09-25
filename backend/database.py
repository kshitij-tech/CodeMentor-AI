from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BACKEND_DIR.parent
load_dotenv(BACKEND_DIR / '.env')
load_dotenv(PROJECT_ROOT / '.env')

import os
import sqlite3

from sqlalchemy import create_engine, event
from sqlalchemy.orm import DeclarativeBase, sessionmaker


configured_database_url = os.getenv(
    "DATABASE_URL",
    "sqlite:///./codementor.db",
)

# Resolve relative SQLite paths from the backend directory. This keeps the
# development database stable whether Uvicorn is started from the repository
# root or from backend/. An explicit DATABASE_URL remains authoritative.
DATABASE_URL = configured_database_url
if configured_database_url.startswith("sqlite:///"):
    sqlite_path = configured_database_url[len("sqlite:///"):]
    is_absolute = (
        sqlite_path.startswith("/")
        or sqlite_path.startswith("\\")
        or (len(sqlite_path) >= 2 and sqlite_path[1] == ":")
    )
    if not is_absolute:
        relative_path = Path(sqlite_path).as_posix().lstrip("./")
        backend_db_path = (BACKEND_DIR / relative_path).resolve()
        cwd_db_path = (Path.cwd() / relative_path).resolve()

        # Prefer the canonical backend location. Only fall back to the current
        # working directory when the backend copy does not exist yet.
        selected_path = backend_db_path if backend_db_path.exists() or not cwd_db_path.exists() else cwd_db_path
        DATABASE_URL = "sqlite:///" + selected_path.as_posix()

connect_args = {}
if DATABASE_URL.startswith("sqlite"):
    connect_args["check_same_thread"] = False
    # Give SQLite concurrent requests time to wait for a short-lived writer
    # instead of immediately raising "database is locked".
    connect_args["timeout"] = 30

engine = create_engine(
    DATABASE_URL,
    connect_args=connect_args,
)

if DATABASE_URL.startswith("sqlite"):
    @event.listens_for(engine, "connect")
    def _configure_sqlite_connection(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA busy_timeout = 30000")
            cursor.execute("PRAGMA journal_mode = WAL")
            cursor.execute("PRAGMA synchronous = NORMAL")
        finally:
            cursor.close()

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
