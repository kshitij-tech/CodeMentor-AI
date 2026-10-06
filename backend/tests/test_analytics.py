from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace
import unittest

from backend.routers.analytics import build_analytics, calculate_streaks


def problem(problem_id, difficulty="Easy", topics=None):
    return SimpleNamespace(
        id=problem_id,
        slug=f"problem-{problem_id}",
        title=f"Problem {problem_id}",
        difficulty=difficulty,
        topics=topics or [],
    )


def attempt(
    attempt_id,
    problem_id,
    created_at,
    *,
    mode="submit",
    status="Wrong Answer",
    runtime_ms=100,
    language="Python",
):
    results = [] if runtime_ms is None else [{"runtime_ms": runtime_ms}]
    return SimpleNamespace(
        id=attempt_id,
        user_id=1,
        problem_id=problem_id,
        language=language,
        mode=mode,
        code="print(1)",
        status=status,
        summary=f"{status} summary",
        results=results,
        created_at=created_at,
    )


class AnalyticsCalculationTests(unittest.TestCase):
    def test_streak_calculation_counts_unique_days(self):
        days = {
            date(2026, 10, 2),
            date(2026, 10, 3),
            date(2026, 10, 5),
            date(2026, 10, 6),
        }
        self.assertEqual(calculate_streaks(days, date(2026, 10, 6)), (2, 2))

    def test_repeated_acceptance_does_not_extend_streak(self):
        now = datetime(2026, 10, 6, 12, tzinfo=timezone.utc)
        rows = [
            (attempt(1, 1, now - timedelta(days=2), status="Accepted"), problem(1)),
            # Same problem accepted again the next day: it is not a new solve.
            (attempt(2, 1, now - timedelta(days=1), status="Accepted"), problem(1)),
            (attempt(3, 2, now, status="Accepted"), problem(2)),
        ]
        payload = build_analytics(rows, now=now)
        self.assertEqual(payload["total_solved"], 2)
        self.assertEqual(payload["current_streak"], 1)
        self.assertEqual(payload["longest_streak"], 1)

    def test_failed_and_run_attempts_never_count_as_solved(self):
        now = datetime(2026, 10, 6, 12, tzinfo=timezone.utc)
        rows = [
            (attempt(1, 1, now - timedelta(minutes=30), status="Wrong Answer"), problem(1)),
            (attempt(2, 1, now - timedelta(minutes=20), mode="run", status="Accepted"), problem(1)),
            (attempt(3, 2, now - timedelta(minutes=10), status="Accepted"), problem(2, "Hard")),
        ]
        payload = build_analytics(rows, now=now)
        self.assertEqual(payload["total_submissions"], 2)
        self.assertEqual(payload["accepted_submissions"], 1)
        self.assertEqual(payload["total_solved"], 1)
        self.assertEqual(payload["difficulty"][2]["solved_problems"], 1)

    def test_acceptance_average_attempts_and_solve_time(self):
        now = datetime(2026, 10, 6, 12, tzinfo=timezone.utc)
        rows = [
            (attempt(1, 1, now - timedelta(minutes=30), status="Wrong Answer"), problem(1)),
            (attempt(2, 1, now - timedelta(minutes=10), status="Accepted", runtime_ms=80), problem(1)),
            (attempt(3, 2, now - timedelta(minutes=5), status="Accepted", runtime_ms=120), problem(2, "Medium")),
        ]
        payload = build_analytics(rows, now=now)
        self.assertEqual(payload["acceptance_rate"], 67)
        self.assertEqual(payload["average_attempts_per_problem"], 1.5)
        self.assertEqual(payload["average_time_to_solve_seconds"], 600)
        self.assertEqual(payload["average_runtime_ms"], 100)

    def test_timezone_changes_streak_calendar_day(self):
        now = datetime(2026, 10, 6, 1, 0, tzinfo=timezone.utc)
        rows = [
            (
                attempt(1, 1, datetime(2026, 10, 5, 23, 30, tzinfo=timezone.utc), status="Accepted"),
                problem(1),
            )
        ]
        payload = build_analytics(rows, timezone_name="Asia/Kolkata", now=now)
        self.assertEqual(payload["current_streak"], 1)
        self.assertEqual(payload["timezone"], "Asia/Kolkata")
        local_day = next(item for item in payload["activity"] if item["date"] == "2026-10-06")
        self.assertEqual(local_day["solved"], 1)

    def test_topic_weakest_and_strongest_use_practiced_topics_only(self):
        now = datetime(2026, 10, 6, 12, tzinfo=timezone.utc)
        rows = [
            (attempt(1, 1, now - timedelta(days=2), status="Wrong Answer"), problem(1, topics=["Arrays & Strings"])),
            (attempt(2, 2, now - timedelta(days=1), status="Accepted"), problem(2, topics=["Binary Search"])),
            (attempt(3, 3, now, status="Accepted"), problem(3, topics=["Binary Search"])),
        ]
        payload = build_analytics(rows, now=now)
        self.assertEqual(payload["weakest_topics"][0]["topic"], "Arrays & Strings")
        self.assertEqual(payload["strongest_topics"][0]["topic"], "Binary Search")
        self.assertTrue(all(item["attempted_problems"] > 0 for item in payload["weakest_topics"]))

    def test_activity_progress_weekly_monthly_and_runtime_trend_are_present(self):
        now = datetime(2026, 10, 6, 12, tzinfo=timezone.utc)
        rows = [
            (attempt(1, 1, now - timedelta(days=2), status="Accepted", runtime_ms=100), problem(1)),
            (attempt(2, 2, now - timedelta(days=1), status="Wrong Answer", runtime_ms=200), problem(2, "Hard")),
        ]
        payload = build_analytics(rows, now=now)
        self.assertEqual(len(payload["activity"]), 365)
        self.assertEqual(len(payload["progress_over_time"]), 180)
        self.assertEqual(len(payload["runtime_trend"]), 30)
        self.assertEqual(len(payload["weekly"]), 12)
        self.assertEqual(len(payload["monthly"]), 12)
        self.assertEqual(payload["progress_over_time"][-1]["cumulative_solved"], 1)

    def test_new_user_returns_zero_metrics_and_empty_rankings(self):
        now = datetime(2026, 10, 6, 12, tzinfo=timezone.utc)
        payload = build_analytics([], now=now)
        self.assertEqual(payload["total_solved"], 0)
        self.assertEqual(payload["total_submissions"], 0)
        self.assertEqual(payload["current_streak"], 0)
        self.assertEqual(payload["longest_streak"], 0)
        self.assertIsNone(payload["average_attempts_per_problem"])
        self.assertIsNone(payload["average_time_to_solve_seconds"])
        self.assertEqual(payload["weakest_topics"], [])
        self.assertEqual(payload["strongest_topics"], [])


if __name__ == "__main__":
    unittest.main()
