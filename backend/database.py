from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BACKEND_DIR.parent
load_dotenv(BACKEND_DIR / '.env')
load_dotenv(PROJECT_ROOT / '.env')

import os

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker


configured_database_url = os.getenv(
    "DATABASE_URL",
    "sqlite:///./codementor.db",
)

# Keep relative SQLite paths stable regardless of whether Uvicorn is started
# from the repository root or from the backend directory. Prefer the existing
# backend database when both locations exist so development data is not lost.
DATABASE_URL = configured_database_url
if configured_database_url.startswith("sqlite:///"):
    sqlite_path = configured_database_url[len("sqlite:///"):]
    is_absolute = (
        sqlite_path.startswith("/")
        or sqlite_path.startswith("\\")
        or (len(sqlite_path) >= 2 and sqlite_path[1] == ":")
    )
    if not is_absolute:
        backend_db_path = (BACKEND_DIR / sqlite_path).resolve()
        cwd_db_path = (Path.cwd() / sqlite_path).resolve()
        if backend_db_path.exists() or not cwd_db_path.exists():
            DATABASE_URL = "sqlite:///" + backend_db_path.as_posix()

connect_args = {}
if DATABASE_URL.startswith("sqlite"):
    connect_args["check_same_thread"] = False

engine = create_engine(
    DATABASE_URL,
    connect_args=connect_args,
)

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
