"""Standalone database scalability benchmark.

Run:
    python -m backend.benchmarks.benchmark_database

The default benchmark uses SQLite so it needs no external service. Set
DATABASE_URL to PostgreSQL in an environment with psycopg installed to point
the same workload at PostgreSQL.
"""
from __future__ import annotations

import statistics
import time
from datetime import datetime, timedelta, timezone

from sqlalchemy import create_engine, text
from sqlalchemy.orm import Session

from backend.models import Base, CodingAttempt, Problem, User

ROWS = 20_000
QUERIES = 20


def main() -> None:
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        user = User(email="bench@example.com", password_hash="x")
        problem = Problem(
            slug="bench-problem",
            title="Benchmark",
            difficulty="Medium",
            topics=["Arrays"],
            description="bench",
            constraints=[],
            examples=[],
            test_cases=[],
            starter_code={},
        )
        db.add_all([user, problem])
        db.flush()
        base = datetime(2026, 1, 1, tzinfo=timezone.utc)
        db.bulk_save_objects(
            [
                CodingAttempt(
                    user_id=user.id,
                    problem_id=problem.id,
                    language="Python",
                    mode="submit",
                    code="pass",
                    status="Accepted" if i % 7 == 0 else "Wrong Answer",
                    summary="bench",
                    results=[],
                    created_at=base + timedelta(seconds=i),
                )
                for i in range(ROWS)
            ]
        )
        db.commit()

        timings = []
        for _ in range(QUERIES):
            started = time.perf_counter()
            db.query(CodingAttempt).filter(
                CodingAttempt.user_id == user.id
            ).order_by(CodingAttempt.created_at, CodingAttempt.id).limit(50).all()
            timings.append((time.perf_counter() - started) * 1000)

        plan = db.execute(
            text(
                "EXPLAIN QUERY PLAN "
                "SELECT id FROM coding_attempts "
                "WHERE user_id = :user_id "
                "ORDER BY created_at, id LIMIT 50"
            ),
            {"user_id": user.id},
        ).all()

    print(f"rows={ROWS} queries={QUERIES}")
    print(f"median_ms={statistics.median(timings):.3f}")
    print("query_plan=")
    for row in plan:
        print("  ", row[-1])


if __name__ == "__main__":
    main()
