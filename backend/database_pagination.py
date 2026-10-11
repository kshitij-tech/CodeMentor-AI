from __future__ import annotations

import base64
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Generic, TypeVar

from sqlalchemy import and_, desc, or_
from sqlalchemy.orm import Query

T = TypeVar("T")


@dataclass(frozen=True)
class Page(Generic[T]):
    items: list[T]
    has_more: bool
    next_cursor: str | None


def encode_cursor(created_at: datetime, item_id: int) -> str:
    value = created_at if created_at.tzinfo else created_at.replace(tzinfo=timezone.utc)
    payload = {"created_at": value.astimezone(timezone.utc).isoformat(), "id": int(item_id)}
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def decode_cursor(cursor: str) -> tuple[datetime, int]:
    if not cursor or len(cursor) > 256:
        raise ValueError("Invalid pagination cursor")
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        payload = json.loads(base64.urlsafe_b64decode(padded.encode("ascii")))
        created_at = datetime.fromisoformat(payload["created_at"])
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=timezone.utc)
        item_id = int(payload["id"])
    except (ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        raise ValueError("Invalid pagination cursor") from exc
    if item_id < 1:
        raise ValueError("Invalid pagination cursor")
    return created_at.astimezone(timezone.utc), item_id


def keyset_paginate(
    query: Query[T],
    *,
    created_at_column,
    id_column,
    limit: int = 50,
    cursor: str | None = None,
    max_limit: int = 200,
) -> Page[T]:
    limit = max(1, min(int(limit), max_limit))
    if cursor:
        cursor_time, cursor_id = decode_cursor(cursor)
        query = query.filter(
            or_(
                created_at_column < cursor_time,
                and_(created_at_column == cursor_time, id_column < cursor_id),
            )
        )

    rows = (
        query.order_by(desc(created_at_column), desc(id_column))
        .limit(limit + 1)
        .all()
    )
    has_more = len(rows) > limit
    rows = rows[:limit]
    next_cursor = None
    if has_more and rows:
        last = rows[-1]
        next_cursor = encode_cursor(
            getattr(last, created_at_column.key),
            getattr(last, id_column.key),
        )
    return Page(items=rows, has_more=has_more, next_cursor=next_cursor)
