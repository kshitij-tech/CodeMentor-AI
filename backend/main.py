from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import inspect, text

from backend.database import SessionLocal

from backend.database import Base, engine
from backend.routers.auth import router as auth_router
from backend.routers.profile import router as profile_router
from backend.routers.problems import router as problems_router
from backend.routers.execution import router as execution_router
from backend.routers.mentor import router as mentor_router
from backend.problem_seed import seed_problems


def initialize_database() -> None:
    Base.metadata.create_all(bind=engine)

    # Development-only schema upgrade for the existing SQLite database.
    if engine.dialect.name != "sqlite":
        return

    inspector = inspect(engine)
    if inspector.has_table("user_profiles"):
        columns = {column["name"] for column in inspector.get_columns("user_profiles")}
        new_columns = {
            "bio": "VARCHAR(180)",
            "target_companies": "JSON",
            "preparation_timeline": "VARCHAR(100)",
            "onboarding_completed": "BOOLEAN NOT NULL DEFAULT 0",
        }

        with engine.begin() as connection:
            for column_name, column_type in new_columns.items():
                if column_name not in columns:
                    connection.execute(
                        text(
                            f'ALTER TABLE user_profiles ADD COLUMN "{column_name}" {column_type}'
                        )
                    )

            if "onboarding_completed" not in columns:
                connection.execute(
                    text(
                        """
                        UPDATE user_profiles
                        SET onboarding_completed = 1
                        WHERE TRIM(COALESCE(full_name, '')) <> ''
                          AND TRIM(COALESCE(preferred_language, '')) <> ''
                          AND TRIM(COALESCE(experience_level, '')) <> ''
                          AND TRIM(COALESCE(target_role, '')) <> ''
                        """
                    )
                )

    if inspector.has_table("coding_attempts"):
        pass

    if inspector.has_table("problems"):
        problem_columns = {column["name"] for column in inspector.get_columns("problems")}
        if "test_cases" not in problem_columns:
            with engine.begin() as connection:
                connection.execute(
                    text('ALTER TABLE problems ADD COLUMN "test_cases" JSON')
                )

    return

initialize_database()

with SessionLocal() as db:
    seed_problems(db)


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
