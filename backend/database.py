from pathlib import Path

from dotenv import load_dotenv

BACKEND_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BACKEND_DIR.parent
load_dotenv(BACKEND_DIR / '.env')
load_dotenv(PROJECT_ROOT / '.env')

import os
import sqlite3

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker


configured_database_url = os.getenv(
    "DATABASE_URL",
    "sqlite:///./codementor.db",
)

def _sqlite_database_score(path: Path) -> tuple[int, int, int]:
    """Prefer an existing SQLite file that actually contains app data."""
    if not path.is_file():
        return (-1, -1, -1)
    try:
        with sqlite3.connect(path) as connection:
            table_count = int(
                connection.execute(
                    "SELECT COUNT(*) FROM sqlite_master WHERE type='table'"
                ).fetchone()[0]
            )
            problem_count = 0
            user_count = 0
            if connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='problems'"
            ).fetchone():
                problem_count = int(
                    connection.execute("SELECT COUNT(*) FROM problems").fetchone()[0]
                )
            if connection.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='users'"
            ).fetchone():
                user_count = int(
                    connection.execute("SELECT COUNT(*) FROM users").fetchone()[0]
                )
        return (problem_count, user_count, table_count)
    except sqlite3.Error:
        return (-1, -1, -1)

# Keep relative SQLite paths stable regardless of whether Uvicorn is started
# from the repository root or from the backend directory. For the default
# development database, prefer the existing file with the most CodeMentor data.
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
        candidate_paths = [
            (BACKEND_DIR / relative_path).resolve(),
            (PROJECT_ROOT / relative_path).resolve(),
            (Path.cwd() / relative_path).resolve(),
        ]
        # Preserve order while removing duplicates.
        candidates = list(dict.fromkeys(candidate_paths))
        if relative_path == "codementor.db":
            existing = [(path, _sqlite_database_score(path)) for path in candidates if path.is_file()]
            if existing:
                selected_path, _ = max(existing, key=lambda item: item[1])
                DATABASE_URL = "sqlite:///" + selected_path.as_posix()
            else:
                DATABASE_URL = "sqlite:///" + candidates[0].as_posix()
        else:
            backend_db_path = (BACKEND_DIR / sqlite_path).resolve()
            cwd_db_path = (Path.cwd() / sqlite_path).resolve()
            DATABASE_URL = (
                "sqlite:///" + backend_db_path.as_posix()
                if backend_db_path.exists() or not cwd_db_path.exists()
                else configured_database_url
            )

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
