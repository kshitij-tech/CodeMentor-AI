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
from backend.security import (
    APP_ENV,
    get_cors_origins,
    validate_security_configuration,
)


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
    docs_url="/docs" if APP_ENV != "production" else None,
    redoc_url="/redoc" if APP_ENV != "production" else None,
    openapi_url="/openapi.json" if APP_ENV != "production" else None,
)

# Fail closed before serving requests if deployment security configuration is invalid.
validate_security_configuration()

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_cors_origins(),
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Accept", "Authorization", "Content-Type", "Origin"],
)


@app.middleware("http")
async def security_headers(request, call_next):
    response = await call_next(request)

    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = (
        "camera=(), microphone=(), geolocation=(), payment=()"
    )

    if request.url.path.startswith("/auth/"):
        response.headers["Cache-Control"] = "no-store"

    if APP_ENV == "production":
        response.headers["Strict-Transport-Security"] = (
            "max-age=31536000; includeSubDomains"
        )

    return response


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
    payload = {
        "message": "CodeMentor AI API is running.",
        "health": "/health",
    }
    if APP_ENV != "production":
        payload["docs"] = "/docs"
    return payload


@app.get("/health")
def health_check() -> dict[str, str]:
    return {
        "status": "ok",
        "service": "codementor-ai-api",
        "version": "0.2.0",
    }
