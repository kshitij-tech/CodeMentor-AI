from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy.orm import Session

from backend.models import CodingAttempt, MentorMessage


@dataclass(frozen=True)
class RetentionPolicy:
    """Retention windows for high-volume, non-authoritative activity data."""

    coding_attempt_days: int = 730
    mentor_message_days: int = 365


def purge_expired_activity(
    db: Session,
    *,
    policy: RetentionPolicy = RetentionPolicy(),
    now: datetime | None = None,
) -> dict[str, int]:
    """Delete explicitly expired activity in dependency-safe order.

    Problems and current workspaces are deliberately retained. Problems are
    referenced by historical attempts, and workspace code is user-authored
    state rather than disposable telemetry. Run this function from an
    operator-controlled scheduled job after backup/retention approval.
    """
    now = now or datetime.now(timezone.utc)
    attempt_cutoff = now - timedelta(days=max(policy.coding_attempt_days, 1))
    message_cutoff = now - timedelta(days=max(policy.mentor_message_days, 1))

    deleted_messages = (
        db.query(MentorMessage)
        .filter(MentorMessage.created_at < message_cutoff)
        .delete(synchronize_session=False)
    )
    deleted_attempts = (
        db.query(CodingAttempt)
        .filter(CodingAttempt.created_at < attempt_cutoff)
        .delete(synchronize_session=False)
    )
    return {
        "mentor_messages": int(deleted_messages),
        "coding_attempts": int(deleted_attempts),
    }
