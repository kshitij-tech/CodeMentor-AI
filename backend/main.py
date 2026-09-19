from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from backend.database import Base, engine
from backend.routers.auth import router as auth_router


Base.metadata.create_all(bind=engine)


app = FastAPI(
    title="CodeMentor AI API",
    version="0.2.0",
    description="Backend API for the CodeMentor AI platform.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)


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
