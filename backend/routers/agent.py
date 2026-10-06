from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from backend.agent import AgentRequest, run_agent
from backend.database import get_db
from backend.models import User
from backend.routers.auth import get_current_user


router = APIRouter(prefix="/agent", tags=["Advanced AI"])


class AgentChatRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    code: str = Field(default="", max_length=40000)
    language: str = Field(default="Python", min_length=1, max_length=50)
    execution: dict[str, Any] | None = None
    problem_slug: str | None = Field(default=None, max_length=120)
    current_problem_id: int | None = Field(default=None, ge=1)
    action: str = Field(default="question", max_length=30)


def _serialize_plan(result) -> dict[str, Any]:
    return {
        "goal": result.plan.goal,
        "tools": [
            {"name": call.name, "arguments": call.arguments}
            for call in result.plan.tool_calls
        ],
        "approval_required": result.plan.approval_required,
        "safety_flags": list(result.plan.safety_flags),
    }


@router.post("/chat")
def agent_chat(
    request: AgentChatRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    result = run_agent(
        db,
        current_user,
        AgentRequest(
            question=request.question,
            code=request.code,
            language=request.language,
            execution=request.execution,
            problem_slug=request.problem_slug,
            current_problem_id=request.current_problem_id,
            action=request.action,
        ),
    )
    return {
        "answer": result.answer,
        "approval_required": result.approval_required,
        "patch": result.patch,
        "error_line": result.error_line,
        "learning_state": {
            "total_attempts": result.learning_state.total_attempts,
            "total_submissions": result.learning_state.total_submissions,
            "total_solved": result.learning_state.total_solved,
            "focus_topics": result.learning_state.focus_topics,
            "recurring_mistakes": result.learning_state.recurring_mistakes,
            "conceptual_risks": result.learning_state.conceptual_risks,
            "learning_objectives": result.learning_state.learning_objectives,
        },
    }
