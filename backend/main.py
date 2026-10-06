from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import inspect, text

from backend.database import SessionLocal

from backend.database import Base, engine
from backend.routers.auth import router as auth_router
from backend.routers.profile import router as profile_router
from backend.routers.problems import router as problems_router, prime_problem_catalog
from backend.routers.execution import router as execution_router
from backend.routers.mentor import router as mentor_router
from backend.routers.analytics import router as analytics_router
from backend.routers.recommendations import router as recommendations_router
from backend.routers.workspace import router as workspace_router
from backend.problem_seed import seed_problems


def initialize_database() -> None:
    Base.metadata.create_all(bind=engine)

    # Development-only schema upgrade for the existing SQLite database.
    if engine.dialect.name != "sqlite":
        return

    inspector = inspect(engine)
    if inspector.has_table("user_profiles"):
        columns = {column["name"] for column in inspector.get_columns("user_profiles")}
        new_profile_columns = {
            "bio": "VARCHAR(180)",
            "target_companies": "JSON",
            "preparation_timeline": "VARCHAR(100)",
            "dsa_familiarity": "JSON",
            "preferred_languages": "JSON",
            "target_categories": "JSON",
            "daily_practice_target": "INTEGER NOT NULL DEFAULT 3",
            "learning_preferences": "JSON",
            "onboarding_completed": "BOOLEAN NOT NULL DEFAULT 0",
        }
        added_profile_preference_columns = False

        with engine.begin() as connection:
            for column_name, column_type in new_profile_columns.items():
                if column_name not in columns:
                    connection.execute(
                        text(
                            f'ALTER TABLE user_profiles ADD COLUMN "{column_name}" {column_type}'
                        )
                    )
                    if column_name not in {"bio", "target_companies", "preparation_timeline", "onboarding_completed"}:
                        added_profile_preference_columns = True

            # Existing users were onboarded against the older, smaller profile
            # contract. Force one fresh onboarding pass after the expanded
            # preference fields are introduced instead of silently pretending
            # those fields were collected.
            if added_profile_preference_columns:
                connection.execute(
                    text(
                        "UPDATE user_profiles SET onboarding_completed = 0"
                    )
                )

    if inspector.has_table("coding_attempts"):
        pass

    if inspector.has_table("problems"):
        problem_columns = {column["name"] for column in inspector.get_columns("problems")}
        problem_migrations = {
            "test_cases": "JSON",
            "source": "VARCHAR(40) NOT NULL DEFAULT 'local'",
            "external_id": "VARCHAR(120)",
            "external_url": "VARCHAR(500)",
            "execution_mode": "VARCHAR(20) NOT NULL DEFAULT 'function'",
            "time_limit_ms": "INTEGER NOT NULL DEFAULT 2000",
            "memory_limit_mb": "INTEGER",
            "validation": "VARCHAR(30) NOT NULL DEFAULT 'default'",
            "package_metadata": "JSON",
        }
        with engine.begin() as connection:
            for column_name, column_type in problem_migrations.items():
                if column_name not in problem_columns:
                    connection.execute(
                        text(
                            f'ALTER TABLE problems ADD COLUMN "{column_name}" {column_type}'
                        )
                    )

    return

initialize_database()

with SessionLocal() as db:
    seed_problems(db)
    # Warm the problem catalogue once at startup so the first Practice request
    # does not have to scan and normalize the full problem dataset.
    prime_problem_catalog(db)


app = FastAPI(
    title="CodeMentor AI API",
    version="0.2.0",
    description="Backend API for the CodeMentor AI platform.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:5173", "http://localhost:5500", "http://127.0.0.1:5500", "null"],
    allow_origin_regex=r"^https?://(localhost|127\.0\.0\.1)(:\d+)?$",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(profile_router)
app.include_router(problems_router)
app.include_router(execution_router)
app.include_router(mentor_router)
app.include_router(analytics_router)
app.include_router(recommendations_router)
app.include_router(workspace_router)


@app.get("/")
def root() -> dict[str, str]:
    return {
        "message": "CodeMentor AI API is running.",
        "docs": "/docs",
        "health": "/health",
    }


@app.get("/health")
def health_check() -> dict[str, str]:
    return {
        "status": "ok",
        "service": "codementor-ai-api",
        "version": "0.2.0",
    }
