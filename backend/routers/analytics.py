from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from typing import Iterable
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from backend.database import get_db
from backend.models import CodingAttempt, MentorMessage, MentorSession, Problem, User
from backend.problem_catalog import CANONICAL_TOPICS, canonicalize_topics, normalize_difficulty
from backend.routers.auth import get_current_user

router = APIRouter(prefix="/analytics", tags=["Analytics"])

TOPICS = CANONICAL_TOPICS
DIFFICULTIES = ("Easy", "Medium", "Hard")
ACTIVITY_DAYS = 365
PROGRESS_DAYS = 180
RUNTIME_TREND_DAYS = 30
WEEK_COUNT = 12
MONTH_COUNT = 12
HISTORY_LIMIT = 100
MISTAKE_LIMIT = 20


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc_aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _local_context(timezone_name: str) -> ZoneInfo:
    try:
        return ZoneInfo(timezone_name or "UTC")
    except (ZoneInfoNotFoundError, ValueError):
        return ZoneInfo("UTC")


def _local_datetime(value: datetime, zone: ZoneInfo) -> datetime:
    return _utc_aware(value).astimezone(zone)


def _rate(numerator: int, denominator: int) -> int:
    return round((numerator / denominator) * 100) if denominator else 0


def _avg(values: Iterable[float | int]) -> float | None:
    values = list(values)
    return round(sum(values) / len(values), 1) if values else None


def _runtime_values(attempt: CodingAttempt) -> list[float]:
    values = []
    for result in (attempt.results or []):
        if isinstance(result, dict):
            value = result.get("runtime_ms")
            if isinstance(value, (int, float)) and value >= 0:
                values.append(float(value))
    return values


def _is_submission(attempt: CodingAttempt) -> bool:
    return str(attempt.mode or "").lower() == "submit"


def _is_accepted(attempt: CodingAttempt) -> bool:
    return _is_submission(attempt) and str(attempt.status or "").strip().lower() == "accepted"


def _difficulty(problem: Problem) -> str:
    return normalize_difficulty(getattr(problem, "difficulty", None)) or "Unknown"


def _topics(problem: Problem) -> list[str]:
    return list(canonicalize_topics(getattr(problem, "topics", None) or []))


def calculate_streaks(solved_days: Iterable[date], today: date) -> tuple[int, int]:
    """Calculate current and longest streaks from unique local solve days."""
    days = set(solved_days)
    if not days:
        return 0, 0

    current = 0
    candidate = today if today in days else today - timedelta(days=1)
    while candidate in days:
        current += 1
        candidate -= timedelta(days=1)

    longest = 0
    running = 0
    previous = None
    for day in sorted(days):
        running = running + 1 if previous and day == previous + timedelta(days=1) else 1
        longest = max(longest, running)
        previous = day

    return current, longest


def _shift_month(first_day: date, months: int) -> date:
    index = first_day.year * 12 + (first_day.month - 1) + months
    return date(index // 12, index % 12 + 1, 1)


def _period_stats(
    normalized_rows: list[tuple[CodingAttempt, Problem, datetime]],
    start: date,
    end: date,
    first_solve_day_by_problem: dict[int, date],
) -> dict:
    rows = [row for row in normalized_rows if start <= row[2].date() <= end]
    submissions = [attempt for attempt, _, _ in rows if _is_submission(attempt)]
    accepted = [attempt for attempt in submissions if _is_accepted(attempt)]
    solved = {
        problem_id
        for problem_id, solve_day in first_solve_day_by_problem.items()
        if start <= solve_day <= end
    }
    active_days = {local_dt.date() for _, _, local_dt in rows}
    runtimes = [
        runtime
        for attempt, _, _ in rows
        for runtime in _runtime_values(attempt)
    ]
    return {
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "attempts": len(rows),
        "submissions": len(submissions),
        "accepted_submissions": len(accepted),
        "solved": len(solved),
        "acceptance_rate": _rate(len(accepted), len(submissions)),
        "active_days": len(active_days),
        "average_runtime_ms": _avg(runtimes),
    }


def build_analytics(
    rows: Iterable[tuple[CodingAttempt, Problem]],
    mentor_hint_count: int = 0,
    timezone_name: str = "UTC",
    now: datetime | None = None,
) -> dict:
    """Build one consistent analytics payload for the dashboard and analytics page."""
    zone = _local_context(timezone_name)
    utc_now = _utc_now() if now is None else _utc_aware(now)
    local_now = utc_now.astimezone(zone)
    today = local_now.date()

    normalized_rows = sorted(
        [
            (attempt, problem, _local_datetime(attempt.created_at, zone))
            for attempt, problem in rows
        ],
        key=lambda item: (item[2], item[0].id),
    )
    submissions = [row for row in normalized_rows if _is_submission(row[0])]
    accepted_submissions = [row for row in submissions if _is_accepted(row[0])]

    attempted_problem_ids = {attempt.problem_id for attempt, _, _ in submissions}
    solved_problem_ids = {attempt.problem_id for attempt, _, _ in accepted_submissions}

    # Keep solve-duration arithmetic in UTC so DST transitions cannot change
    # elapsed time. Calendar/streak grouping still uses the user's local zone.
    first_submission_by_problem: dict[int, datetime] = {}
    first_accept_by_problem: dict[int, datetime] = {}
    for attempt, problem, local_dt in submissions:
        first_submission_by_problem.setdefault(problem.id, _utc_aware(attempt.created_at))
        if _is_accepted(attempt):
            first_accept_by_problem.setdefault(problem.id, _utc_aware(attempt.created_at))

    first_solve_day_by_problem = {
        problem_id: accepted_at.astimezone(zone).date()
        for problem_id, accepted_at in first_accept_by_problem.items()
    }
    solved_days = set(first_solve_day_by_problem.values())
    current_streak, longest_streak = calculate_streaks(solved_days, today)

    solve_durations = {
        problem_id: max(
            0.0,
            (accepted_at - first_submission_by_problem[problem_id]).total_seconds(),
        )
        for problem_id, accepted_at in first_accept_by_problem.items()
        if problem_id in first_submission_by_problem
    }

    runtimes = [
        runtime
        for attempt, _, _ in normalized_rows
        for runtime in _runtime_values(attempt)
    ]

    difficulty_stats = []
    for level in DIFFICULTIES:
        level_rows = [row for row in submissions if _difficulty(row[1]) == level]
        level_problem_ids = {attempt.problem_id for attempt, _, _ in level_rows}
        level_solved_ids = {
            problem_id
            for problem_id in level_problem_ids
            if problem_id in solved_problem_ids
        }
        durations = [
            solve_durations[problem_id]
            for problem_id in level_solved_ids
            if problem_id in solve_durations
        ]
        difficulty_stats.append(
            {
                "difficulty": level,
                "attempted_problems": len(level_problem_ids),
                "solved_problems": len(level_solved_ids),
                "submissions": len(level_rows),
                "accepted_submissions": sum(_is_accepted(row[0]) for row in level_rows),
                "acceptance_rate": _rate(
                    sum(_is_accepted(row[0]) for row in level_rows),
                    len(level_rows),
                ),
                "mastery": _rate(len(level_solved_ids), len(level_problem_ids)),
                "average_attempts_per_problem": (
                    round(len(level_rows) / len(level_problem_ids), 2)
                    if level_problem_ids
                    else None
                ),
                "average_time_to_solve_seconds": _avg(durations),
            }
        )

    topic_stats = []
    for topic in TOPICS:
        topic_rows = [row for row in submissions if topic in _topics(row[1])]
        topic_problem_ids = {attempt.problem_id for attempt, _, _ in topic_rows}
        topic_solved_ids = {
            problem_id
            for problem_id in topic_problem_ids
            if problem_id in solved_problem_ids
        }
        topic_accepted = sum(_is_accepted(row[0]) for row in topic_rows)
        durations = [
            solve_durations[problem_id]
            for problem_id in topic_solved_ids
            if problem_id in solve_durations
        ]
        topic_stats.append(
            {
                "topic": topic,
                "attempted_problems": len(topic_problem_ids),
                "solved_problems": len(topic_solved_ids),
                "submissions": len(topic_rows),
                "accepted_submissions": topic_accepted,
                "acceptance_rate": _rate(topic_accepted, len(topic_rows)),
                "mastery": _rate(len(topic_solved_ids), len(topic_problem_ids)),
                "mastery_confidence": min(100, len(topic_problem_ids) * 10),
                "average_attempts_per_problem": (
                    round(len(topic_rows) / len(topic_problem_ids), 2)
                    if topic_problem_ids
                    else None
                ),
                "average_time_to_solve_seconds": _avg(durations),
            }
        )

    practiced_topics = [item for item in topic_stats if item["attempted_problems"] > 0]
    weakest_topics = sorted(
        practiced_topics,
        key=lambda item: (
            item["mastery"],
            item["acceptance_rate"],
            item["solved_problems"],
            item["topic"],
        ),
    )[:5]
    strongest_topics = sorted(
        practiced_topics,
        key=lambda item: (
            -item["mastery"],
            -item["acceptance_rate"],
            -item["solved_problems"],
            item["topic"],
        ),
    )[:5]

    activity_start = today - timedelta(days=ACTIVITY_DAYS - 1)
    activity_counts: dict[date, dict[str, object]] = defaultdict(
        lambda: {
            "attempts": 0,
            "submissions": 0,
            "accepted_submissions": 0,
            "solved_ids": set(),
        }
    )
    for attempt, problem, local_dt in normalized_rows:
        day = local_dt.date()
        if not activity_start <= day <= today:
            continue
        bucket = activity_counts[day]
        bucket["attempts"] = int(bucket["attempts"]) + 1
        if _is_submission(attempt):
            bucket["submissions"] = int(bucket["submissions"]) + 1
        if _is_accepted(attempt):
            bucket["accepted_submissions"] = int(bucket["accepted_submissions"]) + 1
        if _is_accepted(attempt) and first_solve_day_by_problem.get(problem.id) == day:
            solved_ids = bucket["solved_ids"]
            if isinstance(solved_ids, set):
                solved_ids.add(problem.id)

    activity = []
    for offset in range(ACTIVITY_DAYS):
        day = activity_start + timedelta(days=offset)
        bucket = activity_counts.get(day)
        solved_ids = bucket["solved_ids"] if bucket else set()
        activity.append(
            {
                "date": day.isoformat(),
                "attempts": int(bucket["attempts"]) if bucket else 0,
                "submissions": int(bucket["submissions"]) if bucket else 0,
                "accepted_submissions": int(bucket["accepted_submissions"]) if bucket else 0,
                "solved": len(solved_ids) if isinstance(solved_ids, set) else 0,
            }
        )

    progress_start = today - timedelta(days=PROGRESS_DAYS - 1)
    cumulative_ids = {
        problem_id
        for problem_id, solve_day in first_solve_day_by_problem.items()
        if solve_day < progress_start
    }
    progress = []
    for offset in range(PROGRESS_DAYS):
        day = progress_start + timedelta(days=offset)
        cumulative_ids.update(
            problem_id
            for problem_id, solve_day in first_solve_day_by_problem.items()
            if solve_day == day
        )
        progress.append(
            {
                "date": day.isoformat(),
                "cumulative_solved": len(cumulative_ids),
                "solved": sum(solve_day == day for solve_day in first_solve_day_by_problem.values()),
            }
        )

    runtime_start = today - timedelta(days=RUNTIME_TREND_DAYS - 1)
    daily_runtime_values: dict[date, list[float]] = defaultdict(list)
    for attempt, _, local_dt in normalized_rows:
        day = local_dt.date()
        if runtime_start <= day <= today:
            daily_runtime_values[day].extend(_runtime_values(attempt))
    runtime_trend = [
        {
            "date": (runtime_start + timedelta(days=offset)).isoformat(),
            "average_runtime_ms": _avg(
                daily_runtime_values.get(runtime_start + timedelta(days=offset), [])
            ),
        }
        for offset in range(RUNTIME_TREND_DAYS)
    ]

    current_week_start = today - timedelta(days=today.weekday())
    weekly = [
        _period_stats(
            normalized_rows,
            current_week_start - timedelta(days=offset * 7),
            current_week_start - timedelta(days=offset * 7) + timedelta(days=6),
            first_solve_day_by_problem,
        )
        for offset in range(WEEK_COUNT - 1, -1, -1)
    ]

    current_month_start = date(today.year, today.month, 1)
    monthly = []
    for offset in range(MONTH_COUNT - 1, -1, -1):
        month_start = _shift_month(current_month_start, -offset)
        month_end = _shift_month(month_start, 1) - timedelta(days=1)
        monthly.append(
            _period_stats(
                normalized_rows,
                month_start,
                month_end,
                first_solve_day_by_problem,
            )
        )

    problem_stats_map: dict[int, dict] = {}
    for attempt, problem, local_dt in submissions:
        stat = problem_stats_map.setdefault(
            problem.id,
            {
                "problem_id": problem.id,
                "slug": problem.slug,
                "title": problem.title,
                "difficulty": _difficulty(problem),
                "topics": _topics(problem),
                "attempts": 0,
                "accepted_submissions": 0,
                "first_submission_at": None,
                "solved_at": None,
                "time_to_solve_seconds": None,
                "runtime_values": [],
                "latest_status": None,
            },
        )
        stat["attempts"] += 1
        stat["accepted_submissions"] += int(_is_accepted(attempt))
        stat["latest_status"] = attempt.status
        if stat["first_submission_at"] is None:
            stat["first_submission_at"] = local_dt.isoformat()
        if _is_accepted(attempt) and stat["solved_at"] is None:
            stat["solved_at"] = local_dt.isoformat()
        stat["runtime_values"].extend(_runtime_values(attempt))

    for stat in problem_stats_map.values():
        stat["solved"] = stat["accepted_submissions"] > 0
        stat["acceptance_rate"] = _rate(
            stat["accepted_submissions"],
            stat["attempts"],
        )
        stat["time_to_solve_seconds"] = solve_durations.get(stat["problem_id"])
        stat["average_runtime_ms"] = _avg(stat.pop("runtime_values"))

    recent_submissions = [
        {
            "attempt_id": attempt.id,
            "problem_id": problem.id,
            "problem_slug": problem.slug,
            "problem_title": problem.title,
            "difficulty": _difficulty(problem),
            "topics": _topics(problem),
            "language": attempt.language,
            "status": attempt.status,
            "summary": attempt.summary,
            "runtime_ms": _avg(_runtime_values(attempt)),
            "created_at": _utc_aware(attempt.created_at).isoformat(),
            "created_at_local": local_dt.isoformat(),
        }
        for attempt, problem, local_dt in reversed(submissions[-HISTORY_LIMIT:])
    ]

    recent_mistakes = [
        {
            "attempt_id": attempt.id,
            "problem_slug": problem.slug,
            "problem_title": problem.title,
            "difficulty": _difficulty(problem),
            "status": attempt.status,
            "summary": attempt.summary,
            "language": attempt.language,
            "created_at": _utc_aware(attempt.created_at).isoformat(),
            "created_at_local": local_dt.isoformat(),
        }
        for attempt, problem, local_dt in reversed(submissions)
        if not _is_accepted(attempt)
    ][:MISTAKE_LIMIT]

    total_submissions = len(submissions)
    accepted_count = len(accepted_submissions)

    return {
        "timezone": getattr(zone, "key", timezone_name or "UTC"),
        "generated_at": utc_now.isoformat(),
        "total_attempts": len(normalized_rows),
        "total_submissions": total_submissions,
        "accepted_submissions": accepted_count,
        "total_solved": len(solved_problem_ids),
        "acceptance_rate": _rate(accepted_count, total_submissions),
        "current_streak": current_streak,
        "longest_streak": longest_streak,
        "active_days": len({local_dt.date() for _, _, local_dt in normalized_rows}),
        "average_attempts_per_problem": (
            round(total_submissions / len(attempted_problem_ids), 2)
            if attempted_problem_ids
            else None
        ),
        "average_time_to_solve_seconds": _avg(solve_durations.values()),
        "average_runtime_ms": _avg(runtimes),
        "ai_hints": int(mentor_hint_count or 0),
        "difficulty": difficulty_stats,
        "topics": topic_stats,
        "weakest_topics": weakest_topics,
        "strongest_topics": strongest_topics,
        "activity": activity,
        "progress_over_time": progress,
        "runtime_trend": runtime_trend,
        "weekly": weekly,
        "monthly": monthly,
        "problems": sorted(problem_stats_map.values(), key=lambda item: item["title"].lower()),
        "recent_submissions": recent_submissions,
        "recent_mistakes": recent_mistakes,
    }


def _fetch_rows(current_user: User, db: Session) -> list[tuple[CodingAttempt, Problem]]:
    return (
        db.query(CodingAttempt, Problem)
        .join(Problem, CodingAttempt.problem_id == Problem.id)
        .filter(CodingAttempt.user_id == current_user.id)
        .order_by(CodingAttempt.created_at.asc(), CodingAttempt.id.asc())
        .all()
    )


def _mentor_hint_count(current_user: User, db: Session) -> int:
    from sqlalchemy import func

    return int(
        db.query(func.count(MentorMessage.id))
        .join(MentorSession, MentorMessage.session_id == MentorSession.id)
        .filter(
            MentorSession.user_id == current_user.id,
            MentorMessage.role == "assistant",
            MentorMessage.action == "hint",
        )
        .scalar()
        or 0
    )


def _analytics(current_user: User, db: Session, timezone_name: str) -> dict:
    rows = _fetch_rows(current_user, db)
    return build_analytics(
        rows,
        mentor_hint_count=_mentor_hint_count(current_user, db),
        timezone_name=timezone_name,
    )


@router.get("/summary")
def analytics_summary(
    timezone_name: str = "UTC",
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return _analytics(current_user, db, timezone_name)


@router.get("/detail")
def analytics_detail(
    timezone_name: str = "UTC",
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    return _analytics(current_user, db, timezone_name)
