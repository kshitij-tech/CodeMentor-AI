from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.ai import AIProviderError, mentor_response
from backend.database import get_db
from backend.models import Problem, User
from backend.routers.auth import get_current_user

router = APIRouter(prefix="/mentor", tags=["AI Mentor"])

class MentorRequest(BaseModel):
    problem_slug: str = Field(min_length=1, max_length=120)
    language: str = Field(min_length=1, max_length=50)
    code: str = Field(min_length=1, max_length=40000)
    action: Literal["hint", "debug", "complexity", "edge", "question"] = "question"
    question: str | None = Field(default=None, max_length=2000)
    hint_level: int = Field(default=1, ge=1, le=4)
    execution: dict | None = None

@router.post("/analyze")
def analyze(
    request: MentorRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    problem = db.query(Problem).filter(Problem.slug == request.problem_slug).first()
    if problem is None:
        raise HTTPException(status_code=404, detail="Problem not found.")
    try:
        answer = mentor_response(
            problem={
                "title": problem.title,
                "difficulty": problem.difficulty,
                "topics": problem.topics,
                "description": problem.description,
                "constraints": problem.constraints,
                "examples": problem.examples,
            },
            language=request.language,
            code=request.code,
            execution=request.execution,
            action=request.action,
            question=request.question,
            hint_level=request.hint_level,
        )
    except AIProviderError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {"problem_slug": problem.slug, "action": request.action, "hint_level": request.hint_level, "answer": answer}
