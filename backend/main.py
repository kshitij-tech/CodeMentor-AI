from fastapi import FastAPI
from pydantic import BaseModel


app = FastAPI(
    title="CodeMentor AI API",
    version="0.1.0",
    description="Backend API for the CodeMentor AI platform.",
)


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str


@app.get("/health", response_model=HealthResponse)
def health_check() -> HealthResponse:
    return HealthResponse(
        status="ok",
        service="codementor-ai-api",
        version="0.1.0",
    )


@app.get("/")
def root() -> dict[str, str]:
    return {
        "message": "CodeMentor AI API is running.",
        "docs": "/docs",
        "health": "/health",
    }
