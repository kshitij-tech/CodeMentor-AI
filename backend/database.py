from contextlib import contextmanager
from pathlib import Path
import os
import time
from collections.abc import Callable, Generator
from typing import TypeVar

from dotenv import load_dotenv
from sqlalchemy import create_engine, event
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

BACKEND_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = BACKEND_DIR.parent
load_dotenv(BACKEND_DIR / ".env")
load_dotenv(PROJECT_ROOT / ".env")


T = TypeVar("T")


def _env_int(name: str, default: int, *, minimum: int = 1) -> int:
    value = os.getenv(name)
    if value is None:
        return default
    try:
        parsed = int(value)
    except ValueError:
        return default
    return max(parsed, minimum)


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def normalize_database_url(url: str) -> str:
    """Normalize supported PostgreSQL URLs to the psycopg 3 sync driver."""
    normalized = (url or "").strip()
    if normalized.startswith("postgres://"):
        return "postgresql+psycopg://" + normalized[len("postgres://") :]
    if normalized.startswith("postgresql://"):
        return "postgresql+psycopg://" + normalized[len("postgresql://") :]
    return normalized


configured_database_url = os.getenv("DATABASE_URL", "sqlite:///./codementor.db")
DATABASE_URL = normalize_database_url(configured_database_url)
IS_SQLITE = DATABASE_URL.startswith("sqlite")
IS_POSTGRESQL = DATABASE_URL.startswith("postgresql")
# PostgreSQL deployments are migration-managed by default. SQLite remains
# auto-created for local development unless explicitly disabled.
AUTO_CREATE_SCHEMA = _env_bool("AUTO_CREATE_SCHEMA", IS_SQLITE)

# SQLite remains the zero-configuration development database. PostgreSQL is
# the production path and gets a real QueuePool tuned through environment vars.
connect_args: dict[str, object] = {}
engine_options: dict[str, object] = {
    "pool_pre_ping": True,
}

if IS_SQLITE:
    # Resolve relative SQLite paths from the backend directory. This keeps the
    # development database stable whether Uvicorn starts from repo root or
    # backend/. An explicit DATABASE_URL remains authoritative.
    if DATABASE_URL.startswith("sqlite:///"):
        sqlite_path = DATABASE_URL[len("sqlite:///") :]
        is_absolute = (
            sqlite_path.startswith("/")
            or sqlite_path.startswith("\")
            or (len(sqlite_path) >= 2 and sqlite_path[1] == ":")
        )
        if sqlite_path not in {":memory:", ""} and not is_absolute:
            relative_path = Path(sqlite_path).as_posix().lstrip("./")
            backend_db_path = (BACKEND_DIR / relative_path).resolve()
            cwd_db_path = (Path.cwd() / relative_path).resolve()
            selected_path = (
                backend_db_path
                if backend_db_path.exists() or not cwd_db_path.exists()
                else cwd_db_path
            )
            DATABASE_URL = "sqlite:///" + selected_path.as_posix()

    connect_args.update(
        {
            "check_same_thread": False,
            # Wait briefly for another SQLite writer instead of failing fast.
            "timeout": _env_int("DB_SQLITE_TIMEOUT", 30),
        }
    )
else:
    engine_options.update(
        {
            "pool_size": _env_int("DB_POOL_SIZE", 10),
            "max_overflow": _env_int("DB_MAX_OVERFLOW", 20, minimum=0),
            "pool_timeout": _env_int("DB_POOL_TIMEOUT", 30),
            "pool_recycle": _env_int("DB_POOL_RECYCLE", 1800),
            "pool_use_lifo": True,
        }
    )

engine_options["connect_args"] = connect_args
engine = create_engine(DATABASE_URL, **engine_options)


if IS_SQLITE:

    @event.listens_for(engine, "connect")
    def _configure_sqlite_connection(dbapi_connection, _connection_record):
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute("PRAGMA foreign_keys = ON")
            cursor.execute(f"PRAGMA busy_timeout = {_env_int('DB_SQLITE_TIMEOUT', 30) * 1000}")
            if not str(DATABASE_URL).endswith(":memory:"):
                cursor.execute("PRAGMA journal_mode = WAL")
                cursor.execute("PRAGMA synchronous = NORMAL")
        finally:
            cursor.close()


if IS_POSTGRESQL:

    @event.listens_for(engine, "connect")
    def _configure_postgresql_connection(dbapi_connection, _connection_record):
        statement_timeout_ms = _env_int("DB_STATEMENT_TIMEOUT_MS", 30000)
        cursor = dbapi_connection.cursor()
        try:
            cursor.execute(f"SET statement_timeout = {statement_timeout_ms}")
        finally:
            cursor.close()


SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    expire_on_commit=False,
)


class Base(DeclarativeBase):
    pass


def get_db() -> Generator[Session, None, None]:
    """Yield a request-scoped Session and always rollback failed requests."""
    db = SessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


@contextmanager
def session_scope() -> Generator[Session, None, None]:
    """Run a complete standalone unit of work in one transaction."""
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def is_retryable_concurrency_error(exc: BaseException) -> bool:
    """Return True for transient PostgreSQL/SQLite write-contention errors."""
    original = getattr(exc, "orig", None)
    sqlstate = getattr(original, "sqlstate", None) or getattr(original, "pgcode", None)
    if sqlstate in {"40001", "40P01"}:
        return True
    message = str(original or exc).lower()
    return IS_SQLITE and ("database is locked" in message or "database is busy" in message)


def run_in_transaction(
    operation: Callable[[Session], T],
    *,
    retries: int = 3,
    backoff_seconds: float = 0.05,
) -> T:
    """Execute an operation with bounded retry for transient write conflicts."""
    attempts = max(retries, 1)
    for attempt in range(attempts):
        try:
            with session_scope() as db:
                return operation(db)
        except OperationalError as exc:
            if attempt == attempts - 1 or not is_retryable_concurrency_error(exc):
                raise
            time.sleep(backoff_seconds * (2**attempt))
    raise RuntimeError("Transaction retry loop exited unexpectedly")
