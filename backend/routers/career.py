from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.career import (
    COMPANY_CATEGORIES,
    CS_FUNDAMENTALS,
    INTERVIEW_QUESTIONS,
    QUESTION_MAP,
    ROLE_PROFILES,
    get_role,
    normalized_role_key,
    percent,
    readiness_band,
    role_to_dict,
    topic_match,
)
from backend.career_ai import generate_interview_feedback, heuristic_interview_feedback
from backend.database import get_db
from backend.models import (
    CareerResumeAnalysis,
    CareerSkillProgress,
    CodingAttempt,
    MockInterview,
    MockInterviewResponse,
    Problem,
    User,
    UserProfile,
)
from backend.routers.auth import get_current_user
from backend.schemas import (
    CareerSkillProgressUpsert,
    CareerTargetRoleRequest,
    MockInterviewCreate,
    MockInterviewResponseCreate,
    ResumeSkillAnalysisRequest,
)

router = APIRouter(prefix="/career", tags=["Career Preparation"])

_VALID_PROGRESS_TYPES = {"cs_fundamentals", "role_skill", "behavioral"}
_VALID_INTERVIEW_MODES = {"mixed", "technical", "behavioral"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _profile(db: Session, user: User) -> UserProfile | None:
    return db.scalar(select(UserProfile).where(UserProfile.user_id == user.id))


def _role_for_user(db: Session, user: User) -> tuple[UserProfile | None, Any]:
    profile = _profile(db, user)
    return profile, get_role(normalized_role_key(profile.target_role if profile else None))


def _manual_progress(db: Session, user_id: int) -> dict[tuple[str, str], CareerSkillProgress]:
    rows = db.scalars(
        select(CareerSkillProgress).where(CareerSkillProgress.user_id == user_id)
    ).all()
    return {(row.skill_type, row.skill_key): row for row in rows}


def _dsa_progress(db: Session, user_id: int, required_topics: tuple[str, ...]) -> dict[str, dict[str, int]]:
    rows = db.execute(
        select(CodingAttempt, Problem)
        .join(Problem, CodingAttempt.problem_id == Problem.id)
        .where(CodingAttempt.user_id == user_id)
    ).all()
    result: dict[str, dict[str, int]] = {}
    for topic in required_topics:
        attempted_problem_ids: set[int] = set()
        solved_problem_ids: set[int] = set()
        submissions = 0
        accepted = 0
        for attempt, problem in rows:
            if not any(topic_match(actual, topic) for actual in (problem.topics or [])):
                continue
            attempted_problem_ids.add(problem.id)
            if attempt.mode == "submit":
                submissions += 1
                if attempt.status == "Accepted":
                    accepted += 1
                    solved_problem_ids.add(problem.id)
        attempted = len(attempted_problem_ids)
        solved = len(solved_problem_ids)
        solve_rate = solved / attempted if attempted else 0.0
        submission_success = accepted / submissions if submissions else 0.0
        evidence = min(1.0, attempted / 8.0)
        mastery = round((0.7 * solve_rate + 0.3 * submission_success) * evidence * 100) if attempted else 0
        result[topic] = {
            "attempted": attempted,
            "solved": solved,
            "submissions": submissions,
            "accepted": accepted,
            "mastery": mastery,
            "evidence": round(evidence * 100),
        }
    return result


def _skill_entry(skill_type: str, key: str, label: str, progress: CareerSkillProgress | None) -> dict[str, Any]:
    return {
        "type": skill_type,
        "key": key,
        "label": label,
        "status": progress.status if progress else "not_started",
        "score": int(progress.score if progress else 0),
        "evidence_count": int(progress.evidence_count if progress else 0),
        "notes": progress.notes if progress else None,
    }


def _required_skill_entries(role: Any, manual: dict[tuple[str, str], CareerSkillProgress]) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    for skill in role.cs_fundamentals:
        entries.append(_skill_entry("cs_fundamentals", skill, skill, manual.get(("cs_fundamentals", skill))))
    for skill in role.role_skills:
        entries.append(_skill_entry("role_skill", skill, skill, manual.get(("role_skill", skill))))
    return entries


def _mock_stats(db: Session, user_id: int) -> dict[str, Any]:
    sessions = db.scalars(
        select(MockInterview)
        .where(MockInterview.user_id == user_id)
        .order_by(MockInterview.created_at.desc())
    ).all()
    completed = [item for item in sessions if item.status == "completed" and item.score is not None]
    avg = round(sum(int(item.score or 0) for item in completed) / len(completed)) if completed else 0
    return {
        "total": len(sessions),
        "completed": len(completed),
        "average_score": avg,
        "latest_score": int(completed[0].score) if completed else None,
        "recent": [
            {
                "id": item.id,
                "role_key": item.role_key,
                "mode": item.mode,
                "status": item.status,
                "score": item.score,
                "created_at": item.created_at.isoformat(),
            }
            for item in sessions[:5]
        ],
    }


def _resume_stats(db: Session, user_id: int) -> dict[str, Any]:
    latest = db.scalar(
        select(CareerResumeAnalysis)
        .where(CareerResumeAnalysis.user_id == user_id)
        .order_by(CareerResumeAnalysis.created_at.desc())
    )
    if not latest:
        return {"alignment_score": 0, "matched_skills": [], "missing_skills": [], "last_analyzed_at": None}
    return {
        "alignment_score": latest.alignment_score,
        "matched_skills": latest.matched_skills or [],
        "missing_skills": latest.missing_skills or [],
        "last_analyzed_at": latest.created_at.isoformat(),
    }


def _compute_readiness(dsa: int, fundamentals: int, role_skills: int, interviews: int, resume: int) -> int:
    return round(
        max(0, min(100,
            dsa * 0.30
            + fundamentals * 0.25
            + role_skills * 0.20
            + interviews * 0.15
            + resume * 0.10
        ))
    )


def _weak_areas(role: Any, dsa: dict[str, dict[str, int]], skills: list[dict[str, Any]]) -> list[dict[str, Any]]:
    weaknesses = [
        {"type": "dsa", "key": topic, "label": topic, "score": stats["mastery"], "reason": "Low demonstrated DSA mastery."}
        for topic, stats in dsa.items()
        if stats["mastery"] < 50
    ]
    weaknesses += [
        {"type": item["type"], "key": item["key"], "label": item["label"], "score": item["score"], "reason": "Needs tracked coverage before interviews."}
        for item in skills
        if item["score"] < 50
    ]
    weaknesses.sort(key=lambda item: (item["score"], item["label"]))
    return weaknesses[:8]


def _personalized_plan(role: Any, weaknesses: list[dict[str, Any]]) -> list[dict[str, Any]]:
    plan: list[dict[str, Any]] = []
    for weakness in weaknesses[:5]:
        label = weakness["label"]
        if weakness["type"] == "dsa":
            action = f"Solve 3 {label} problems, review one failed attempt, then repeat one timed problem."
        elif weakness["type"] == "cs_fundamentals":
            action = f"Study {label}, write a one-page interview summary, and answer 5 oral questions."
        elif weakness["type"] == "role_skill":
            action = f"Build or review a small {label} example and explain the design trade-offs aloud."
        else:
            action = f"Practice a STAR story covering {label} and record a 90-second answer."
        plan.append({"priority": len(plan) + 1, "focus": label, "action": action, "score": weakness["score"]})
    if not plan:
        plan.append({
            "priority": 1,
            "focus": "Mock interview",
            "action": "Take a mixed mock interview and use the feedback to choose your next weak area.",
            "score": 100,
        })
    return plan


def _questions_for(role_key: str, mode: str, limit: int) -> list[dict[str, Any]]:
    typed: list[dict[str, Any]] = []
    role_candidates = []
    for question in INTERVIEW_QUESTIONS:
        if role_key not in question["roles"]:
            continue
        if mode != "mixed" and question["type"] != mode:
            continue
        role_candidates.append(question)
    if mode == "mixed":
        technical = [q for q in role_candidates if q["type"] == "technical"]
        behavioral = [q for q in role_candidates if q["type"] == "behavioral"]
        while len(typed) < limit and (technical or behavioral):
            source = technical if len(typed) % 2 == 0 and technical else behavioral if behavioral else technical
            typed.append(source.pop(0))
    else:
        typed = role_candidates[:limit]
    return typed[:limit]


def _question_payload(question: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": question["id"],
        "prompt": question["prompt"],
        "type": question["type"],
        "difficulty": question["difficulty"],
        "topics": list(question["topics"]),
        "companies": list(question["companies"]),
    }


def _session_payload(db: Session, session: MockInterview) -> dict[str, Any]:
    responses = db.scalars(
        select(MockInterviewResponse)
        .where(MockInterviewResponse.interview_id == session.id)
        .order_by(MockInterviewResponse.created_at.asc())
    ).all()
    question_ids = session.question_ids or []
    current_question = QUESTION_MAP.get(question_ids[session.current_index]) if session.current_index < len(question_ids) else None
    return {
        "id": session.id,
        "role_key": session.role_key,
        "mode": session.mode,
        "status": session.status,
        "current_index": session.current_index,
        "total_questions": session.total_questions,
        "score": session.score,
        "current_question": _question_payload(current_question) if current_question else None,
        "responses": [
            {
                "id": item.id,
                "question_id": item.question_id,
                "score": item.score,
                "feedback": item.feedback,
                "created_at": item.created_at.isoformat(),
            }
            for item in responses
        ],
        "feedback": session.feedback,
        "created_at": session.created_at.isoformat(),
        "completed_at": session.completed_at.isoformat() if session.completed_at else None,
    }


@router.get("/roles")
def career_roles(current_user: User = Depends(get_current_user)) -> list[dict[str, Any]]:
    return [role_to_dict(role) for role in ROLE_PROFILES.values()]


@router.get("/company-categories")
def company_categories(current_user: User = Depends(get_current_user)) -> dict[str, Any]:
    return COMPANY_CATEGORIES


@router.put("/target-role")
def set_target_role(
    request: CareerTargetRoleRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    role_key = normalized_role_key(request.role_key)
    if role_key not in ROLE_PROFILES:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Unsupported target role.")
    profile = _profile(db, current_user)
    if profile is None:
        profile = UserProfile(user_id=current_user.id, target_role=role_key)
        db.add(profile)
    else:
        profile.target_role = role_key
    db.commit()
    return {"role": role_to_dict(ROLE_PROFILES[role_key])}


@router.get("/questions")
def interview_questions(
    role_key: str | None = None,
    question_type: str | None = Query(default=None, alias="type"),
    topic: str | None = None,
    difficulty: str | None = None,
    company: str | None = None,
    limit: int = Query(default=50, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    key = normalized_role_key(role_key) if role_key else None
    filtered = []
    for question in INTERVIEW_QUESTIONS:
        if key and key not in question["roles"]:
            continue
        if question_type and question["type"] != question_type:
            continue
        if topic and topic.casefold() not in {item.casefold() for item in question["topics"]}:
            continue
        if difficulty and question["difficulty"] != difficulty:
            continue
        if company and company not in question["companies"]:
            continue
        filtered.append(_question_payload(question) | {"rubric": list(question["rubric"]), "roles": list(question["roles"])})
    return {"total": len(filtered), "questions": filtered[offset:offset + limit]}


@router.get("/progress")
def career_progress(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    profile, role = _role_for_user(db, current_user)
    manual = _manual_progress(db, current_user.id)
    skills = _required_skill_entries(role, manual)
    dsa = _dsa_progress(db, current_user.id, role.dsa_topics)

    dsa_score = round(sum(item["mastery"] for item in dsa.values()) / max(len(dsa), 1))
    fundamentals = [item for item in skills if item["type"] == "cs_fundamentals"]
    role_skills = [item for item in skills if item["type"] == "role_skill"]
    fundamentals_score = round(sum(item["score"] for item in fundamentals) / max(len(fundamentals), 1))
    role_score = round(sum(item["score"] for item in role_skills) / max(len(role_skills), 1))
    mock = _mock_stats(db, current_user.id)
    resume = _resume_stats(db, current_user.id)
    readiness = _compute_readiness(dsa_score, fundamentals_score, role_score, mock["average_score"], resume["alignment_score"])

    weaknesses = _weak_areas(role, dsa, skills)
    return {
        "role": role_to_dict(role),
        "readiness_score": readiness,
        "readiness_band": readiness_band(readiness),
        "dsa": {
            "score": dsa_score,
            "topics_completed": sum(1 for item in dsa.values() if item["mastery"] >= 75),
            "total_topics": len(dsa),
            "topics": dsa,
        },
        "cs_fundamentals": {
            "score": fundamentals_score,
            "completed": sum(1 for item in fundamentals if item["score"] >= 75),
            "total": len(fundamentals),
            "skills": fundamentals,
        },
        "role_skills": {
            "score": role_score,
            "completed": sum(1 for item in role_skills if item["score"] >= 75),
            "total": len(role_skills),
            "skills": role_skills,
        },
        "mock_interviews": mock,
        "resume": resume,
        "weak_areas": weaknesses,
    }


@router.put("/progress")
def upsert_career_progress(
    request: CareerSkillProgressUpsert,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    if request.skill_type not in _VALID_PROGRESS_TYPES:
        raise HTTPException(status_code=400, detail="skill_type must be cs_fundamentals, role_skill, or behavioral.")
    profile = _profile(db, current_user)
    role_key = normalized_role_key(profile.target_role if profile else None)
    role = ROLE_PROFILES.get(role_key) or ROLE_PROFILES["software_engineer"]
    valid_keys = set(CS_FUNDAMENTALS) | set(role.cs_fundamentals) | set(role.role_skills) | {"Behavioral"}
    if request.skill_type == "behavioral":
        valid_keys |= {question["id"] for question in INTERVIEW_QUESTIONS if question["type"] == "behavioral"}
    if request.skill_key not in valid_keys:
        raise HTTPException(status_code=400, detail="The requested skill is not part of the selected career path.")
    progress = db.scalar(
        select(CareerSkillProgress).where(
            CareerSkillProgress.user_id == current_user.id,
            CareerSkillProgress.skill_type == request.skill_type,
            CareerSkillProgress.skill_key == request.skill_key,
        )
    )
    if progress is None:
        progress = CareerSkillProgress(
            user_id=current_user.id,
            skill_type=request.skill_type,
            skill_key=request.skill_key,
        )
        db.add(progress)
    progress.status = request.status
    progress.score = request.score
    progress.evidence_count = request.evidence_count
    progress.notes = request.notes
    db.commit()
    db.refresh(progress)
    return {
        "id": progress.id,
        "skill_type": progress.skill_type,
        "skill_key": progress.skill_key,
        "status": progress.status,
        "score": progress.score,
        "evidence_count": progress.evidence_count,
        "notes": progress.notes,
    }


@router.get("/roadmap")
def interview_roadmap(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    progress = career_progress(current_user=current_user, db=db)
    role = progress["role"]
    score_by_skill = {
        topic: stats["mastery"]
        for topic, stats in progress["dsa"]["topics"].items()
    }
    score_by_skill.update({item["label"]: item["score"] for item in progress["cs_fundamentals"]["skills"]})
    score_by_skill.update({item["label"]: item["score"] for item in progress["role_skills"]["skills"]})
    phases = []
    for index, phase in enumerate(role["roadmap"], start=1):
        phase_items = list(phase["items"])
        completed = sum(1 for item in phase_items if score_by_skill.get(item, 0) >= 75)
        active = sum(1 for item in phase_items if 0 < score_by_skill.get(item, 0) < 75)
        phase_percent = percent(completed, len(phase_items))
        phases.append({
            **phase,
            "phase": index,
            "completion": phase_percent,
            "status": "complete" if completed == len(phase_items) else "active" if active or completed else "upcoming",
        })
    return {
        "role": role,
        "overall_completion": round(sum(item["completion"] for item in phases) / max(len(phases), 1)),
        "phases": phases,
        "personalized_plan": _personalized_plan(get_role(role["key"]), progress["weak_areas"]),
    }


@router.get("/dashboard")
def career_dashboard(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    profile, role = _role_for_user(db, current_user)
    progress = career_progress(current_user=current_user, db=db)
    roadmap = interview_roadmap(current_user=current_user, db=db)
    target_companies = list(profile.target_companies or []) if profile else []
    role_categories = role.company_categories
    company_rows = []
    for category in role_categories:
        details = COMPANY_CATEGORIES.get(category)
        if details:
            company_rows.append({"category": category, **details, "selected": any(name in target_companies for name in details["companies"])})
    return {
        "profile": {
            "full_name": profile.full_name if profile else None,
            "experience_level": profile.experience_level if profile else None,
            "preferred_language": profile.preferred_language if profile else None,
            "target_role": role.key,
            "target_role_selected": bool(profile and profile.target_role),
            "target_companies": target_companies,
            "preparation_timeline": profile.preparation_timeline if profile else None,
        },
        "role": role_to_dict(role),
        "readiness_score": progress["readiness_score"],
        "readiness_band": progress["readiness_band"],
        "metrics": {
            "dsa": progress["dsa"],
            "cs_fundamentals": progress["cs_fundamentals"],
            "role_skills": progress["role_skills"],
            "mock_interviews": progress["mock_interviews"],
            "resume": progress["resume"],
        },
        "weak_areas": progress["weak_areas"],
        "roadmap": roadmap,
        "company_preparation": company_rows,
        "interview_question_count": len(INTERVIEW_QUESTIONS),
        "personalized_plan": roadmap["personalized_plan"],
    }


@router.post("/mock-interviews")
def create_mock_interview(
    request: MockInterviewCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    if request.mode not in _VALID_INTERVIEW_MODES:
        raise HTTPException(status_code=400, detail="mode must be mixed, technical, or behavioral.")
    profile = _profile(db, current_user)
    role_key = normalized_role_key(request.role_key or (profile.target_role if profile else None))
    if role_key not in ROLE_PROFILES:
        role_key = "software_engineer"
    questions = _questions_for(role_key, request.mode, request.question_count)
    if len(questions) < 3:
        raise HTTPException(status_code=400, detail="Not enough questions are available for this interview mode.")
    session = MockInterview(
        user_id=current_user.id,
        role_key=role_key,
        mode=request.mode,
        status="in_progress",
        current_index=0,
        total_questions=len(questions),
        question_ids=[item["id"] for item in questions],
    )
    db.add(session)
    db.commit()
    db.refresh(session)
    return _session_payload(db, session)


@router.get("/mock-interviews/{interview_id}")
def get_mock_interview(
    interview_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    session = db.scalar(select(MockInterview).where(MockInterview.id == interview_id, MockInterview.user_id == current_user.id))
    if session is None:
        raise HTTPException(status_code=404, detail="Mock interview not found.")
    return _session_payload(db, session)


@router.post("/mock-interviews/{interview_id}/responses")
def answer_mock_question(
    interview_id: int,
    request: MockInterviewResponseCreate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    session = db.scalar(select(MockInterview).where(MockInterview.id == interview_id, MockInterview.user_id == current_user.id))
    if session is None:
        raise HTTPException(status_code=404, detail="Mock interview not found.")
    if session.status != "in_progress":
        raise HTTPException(status_code=400, detail="This mock interview is already complete.")
    if session.current_index >= len(session.question_ids or []):
        raise HTTPException(status_code=400, detail="There are no unanswered questions.")

    expected_id = session.question_ids[session.current_index]
    if request.question_id != expected_id:
        raise HTTPException(status_code=409, detail="Answer the current interview question before moving on.")
    question = QUESTION_MAP[expected_id]
    try:
        feedback = generate_interview_feedback(
            question=question["prompt"],
            answer=request.answer,
            rubric=list(question["rubric"]),
            question_type=question["type"],
        )
        feedback_source = "ai"
    except Exception:
        feedback = heuristic_interview_feedback(
            question=question["prompt"],
            answer=request.answer,
            rubric=list(question["rubric"]),
            question_type=question["type"],
        )
        feedback_source = "heuristic"
    feedback["source"] = feedback_source

    response = MockInterviewResponse(
        interview_id=session.id,
        question_id=request.question_id,
        answer=request.answer,
        score=feedback["score"],
        feedback=feedback,
    )
    db.add(response)
    session.current_index += 1
    if session.current_index >= session.total_questions:
        session.status = "ready_to_complete"
    db.commit()
    db.refresh(response)
    db.refresh(session)
    return {
        "response": {
            "id": response.id,
            "question_id": response.question_id,
            "score": response.score,
            "feedback": response.feedback,
        },
        "next_question": (
            _question_payload(QUESTION_MAP[session.question_ids[session.current_index]])
            if session.current_index < len(session.question_ids)
            else None
        ),
        "status": session.status,
    }


@router.post("/mock-interviews/{interview_id}/complete")
def complete_mock_interview(
    interview_id: int,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    session = db.scalar(select(MockInterview).where(MockInterview.id == interview_id, MockInterview.user_id == current_user.id))
    if session is None:
        raise HTTPException(status_code=404, detail="Mock interview not found.")
    responses = db.scalars(select(MockInterviewResponse).where(MockInterviewResponse.interview_id == session.id)).all()
    if len(responses) < session.total_questions:
        raise HTTPException(status_code=400, detail="Answer all interview questions before completing the session.")
    scores = [int(item.score or 0) for item in responses]
    score = round(sum(scores) / max(len(scores), 1))
    strengths = []
    improvements = []
    for item in sorted(responses, key=lambda row: int(row.score or 0), reverse=True)[:3]:
        strengths.extend((item.feedback or {}).get("strengths") or [])
    for item in sorted(responses, key=lambda row: int(row.score or 0))[:3]:
        improvements.extend((item.feedback or {}).get("improvements") or [])

    session.status = "completed"
    session.score = score
    session.completed_at = _now()
    session.feedback = {
        "score": score,
        "strengths": list(dict.fromkeys(strengths))[:5],
        "improvements": list(dict.fromkeys(improvements))[:5],
        "summary": f"You scored {score}/100 across {len(responses)} interview questions. Focus next on the lowest-scoring answers.",
    }
    db.commit()
    db.refresh(session)
    return _session_payload(db, session)


@router.post("/resume-analysis")
def analyze_resume(
    request: ResumeSkillAnalysisRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    profile = _profile(db, current_user)
    role_key = normalized_role_key(request.role_key or (profile.target_role if profile else None))
    if role_key not in ROLE_PROFILES:
        raise HTTPException(status_code=400, detail="Unsupported target role.")
    role = ROLE_PROFILES[role_key]
    haystack = request.resume_text.casefold()
    skills = list(dict.fromkeys([*role.dsa_topics, *role.cs_fundamentals, *role.role_skills]))

    matched: list[str] = []
    missing: list[str] = []
    for skill in skills:
        variants = [
            skill.casefold(),
            *[part.strip().casefold() for part in skill.replace("/", ",").split(",") if part.strip()],
        ]
        if any(len(variant) >= 3 and variant in haystack for variant in variants):
            matched.append(skill)
        else:
            missing.append(skill)
    alignment = percent(len(matched), len(skills))
    recommendations = [f"Add evidence for {skill}: project, metric, coursework, or interview-ready explanation." for skill in missing[:8]]

    analysis = CareerResumeAnalysis(
        user_id=current_user.id,
        role_key=role_key,
        matched_skills=matched,
        missing_skills=missing,
        recommendations=recommendations,
        alignment_score=alignment,
    )
    db.add(analysis)
    db.commit()
    db.refresh(analysis)
    return {
        "id": analysis.id,
        "role": role_to_dict(role),
        "alignment_score": alignment,
        "matched_skills": matched,
        "missing_skills": missing,
        "recommendations": recommendations,
        "privacy": "Resume text is analyzed in memory and is not persisted; only the skill-gap result is stored.",
    }
