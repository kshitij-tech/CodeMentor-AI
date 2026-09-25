from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import desc
from sqlalchemy.orm import Session

from backend.ai import AIProviderError, mentor_response
from backend.database import get_db
from backend.models import MentorMessage, MentorSession, Problem, User
from backend.routers.auth import get_current_user

router = APIRouter(prefix="/mentor", tags=["AI Mentor"])


class DashboardMentorRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    session_id: int | None = Field(default=None, ge=1)


class MentorRequest(BaseModel):
    problem_slug: str = Field(min_length=1, max_length=120)
    language: str = Field(min_length=1, max_length=50)
    code: str = Field(min_length=1, max_length=40000)
    action: Literal["hint", "debug", "complexity", "edge", "question", "modify"] = "question"
    question: str | None = Field(default=None, max_length=2000)
    hint_level: int = Field(default=1, ge=1, le=4)
    execution: dict | None = None
    session_id: int | None = Field(default=None, ge=1)


def _get_or_create_session(
    db: Session,
    user: User,
    *,
    scope: str,
    problem: Problem | None = None,
    session_id: int | None = None,
) -> MentorSession:
    problem_id = problem.id if problem else None

    if session_id is not None:
        session = (
            db.query(MentorSession)
            .filter(
                MentorSession.id == session_id,
                MentorSession.user_id == user.id,
            )
            .first()
        )
        if session is None:
            raise HTTPException(status_code=404, detail="Mentor session not found.")
        if session.scope != scope or session.problem_id != problem_id:
            raise HTTPException(status_code=400, detail="Mentor session context does not match this request.")
        return session

    session = (
        db.query(MentorSession)
        .filter(
            MentorSession.user_id == user.id,
            MentorSession.scope == scope,
            MentorSession.problem_id == problem_id,
        )
        .order_by(desc(MentorSession.updated_at))
        .first()
    )
    if session is not None:
        return session

    title = (
        problem.title if problem is not None
        else "Dashboard AI Mentor"
    )
    session = MentorSession(
        user_id=user.id,
        problem_id=problem_id,
        scope=scope,
        title=title,
    )
    db.add(session)
    db.flush()
    return session


def _history(db: Session, session_id: int, limit: int = 8) -> list[dict[str, str]]:
    messages = (
        db.query(MentorMessage)
        .filter(MentorMessage.session_id == session_id)
        .order_by(MentorMessage.created_at.desc(), MentorMessage.id.desc())
        .limit(limit)
        .all()
    )
    messages.reverse()
    return [{"role": message.role, "content": message.content} for message in messages]


def _serialize_messages(db: Session, session_id: int, limit: int = 40) -> list[dict]:
    messages = (
        db.query(MentorMessage)
        .filter(MentorMessage.session_id == session_id)
        .order_by(MentorMessage.created_at.desc(), MentorMessage.id.desc())
        .limit(limit)
        .all()
    )
    messages.reverse()
    return [
        {
            "id": message.id,
            "role": message.role,
            "content": message.content,
            "action": message.action,
            "hint_level": message.hint_level,
            "created_at": message.created_at.isoformat(),
        }
        for message in messages
    ]


class SessionResponse(BaseModel):
    id: int
    title: str
    scope: str
    problem_slug: str | None
    updated_at: str


@router.get("/sessions", response_model=list[SessionResponse])
def list_sessions(
    scope: Literal["dashboard", "practice"] = "practice",
    problem_slug: str | None = None,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    problem_id = None
    if problem_slug:
        problem = db.query(Problem).filter(Problem.slug == problem_slug).first()
        if problem is None:
            raise HTTPException(status_code=404, detail="Problem not found.")
        problem_id = problem.id
    sessions = (
        db.query(MentorSession)
        .filter(
            MentorSession.user_id == current_user.id,
            MentorSession.scope == scope,
            MentorSession.problem_id == problem_id,
        )
        .order_by(desc(MentorSession.updated_at))
        .limit(20)
        .all()
    )
    problem = None
    if problem_id is not None:
        problem = db.query(Problem).filter(Problem.id == problem_id).first()

    return [
        SessionResponse(
            id=session.id,
            title=session.title,
            scope=session.scope,
            problem_slug=problem.slug if problem is not None else None,
            updated_at=session.updated_at.isoformat(),
        )
        for session in sessions
    ]


@router.get("/sessions/{session_id}")
def get_session(
    session_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    session = (
        db.query(MentorSession)
        .filter(MentorSession.id == session_id, MentorSession.user_id == current_user.id)
        .first()
    )
    if session is None:
        raise HTTPException(status_code=404, detail="Mentor session not found.")
    problem = db.query(Problem).filter(Problem.id == session.problem_id).first() if session.problem_id else None
    return {
        "id": session.id,
        "title": session.title,
        "scope": session.scope,
        "problem_slug": problem.slug if problem else None,
        "messages": _serialize_messages(db, session.id),
    }


@router.delete("/sessions/{session_id}")
def delete_session(
    session_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    session = (
        db.query(MentorSession)
        .filter(MentorSession.id == session_id, MentorSession.user_id == current_user.id)
        .first()
    )
    if session is None:
        raise HTTPException(status_code=404, detail="Mentor session not found.")
    db.query(MentorMessage).filter(MentorMessage.session_id == session.id).delete(synchronize_session=False)
    db.delete(session)
    db.commit()
    return {"deleted": True}


@router.post("/chat")
def dashboard_chat(
    request: DashboardMentorRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    session = _get_or_create_session(
        db,
        current_user,
        scope="dashboard",
        session_id=request.session_id,
    )

    prior_history = _history(db, session.id)
    user_message = MentorMessage(
        session_id=session.id,
        role="user",
        content=request.question,
        action="question",
        hint_level=1,
    )
    db.add(user_message)
    # Do not keep a SQLite write transaction open while waiting for the
    # local/cloud LLM. Persist the user message first so other requests can
    # write to the database while the mentor is thinking.
    db.commit()

    try:
        result = mentor_response(
            problem={
                "title": "Dashboard mentoring session",
                "difficulty": "Personalized",
                "topics": ["DSA", "Interview Preparation"],
                "description": "The user is asking for general coding and interview coaching from the CodeMentor dashboard.",
                "constraints": [],
                "examples": [],
            },
            language="Not specified",
            code="(No code is currently open in the Dashboard mentor.)",
            execution=None,
            action="question",
            question=request.question,
            hint_level=1,
            history=prior_history,
        )
    except AIProviderError as exc:
        db.rollback()
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    assistant_message = MentorMessage(
        session_id=session.id,
        role="assistant",
        content=result.get("answer", ""),
        action="question",
        hint_level=1,
    )
    db.add(assistant_message)
    session.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(assistant_message)

    return {
        "session_id": session.id,
        "answer": result.get("answer", ""),
        "error_line": None,
        "patch": None,
        "message_id": assistant_message.id,
    }


@router.post("/analyze")
def analyze(
    request: MentorRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    problem = db.query(Problem).filter(Problem.slug == request.problem_slug).first()
    if problem is None:
        raise HTTPException(status_code=404, detail="Problem not found.")

    session = _get_or_create_session(
        db,
        current_user,
        scope="practice",
        problem=problem,
        session_id=request.session_id,
    )
    prior_history = _history(db, session.id)
    user_message = MentorMessage(
        session_id=session.id,
        role="user",
        content=request.question or request.action,
        action=request.action,
        hint_level=request.hint_level,
    )
    db.add(user_message)
    # Keep the LLM call outside the SQLite write transaction.
    db.commit()

    try:
        result = mentor_response(
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
            history=prior_history,
        )
    except AIProviderError as exc:
        db.rollback()
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    if not isinstance(result, dict):
        raise HTTPException(status_code=503, detail="The mentor returned an invalid response.")

    assistant_message = MentorMessage(
        session_id=session.id,
        role="assistant",
        content=result.get("answer", ""),
        action=request.action,
        hint_level=request.hint_level,
    )
    db.add(assistant_message)
    session.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(assistant_message)

    return {
        "session_id": session.id,
        "problem_slug": problem.slug,
        "action": request.action,
        "hint_level": request.hint_level,
        "answer": result.get("answer", ""),
        "error_line": result.get("error_line"),
        "patch": result.get("patch"),
        "message_id": assistant_message.id,
    }
