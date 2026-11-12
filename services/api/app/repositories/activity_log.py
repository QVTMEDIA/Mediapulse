from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import List, Optional, Protocol

from ..config import get_settings
from ..db import get_connection

logger = logging.getLogger(__name__)


@dataclass
class ActivityLogEntryRecord:
    id: str
    actor_id: Optional[str]
    actor_name: str
    action: str
    summary: str
    project_id: Optional[str]
    project_name: Optional[str]
    created_at: datetime


@dataclass
class ActivityLogPage:
    entries: List[ActivityLogEntryRecord]
    # Total entries across the whole account, not just len(entries) -- for
    # pagination UI, same shape as RatingsRowsPage's own `total`.
    total: int


class ActivityLogRepository(Protocol):
    def record(
        self,
        *,
        actor_id: Optional[str],
        actor_name: str,
        action: str,
        summary: str,
        project_id: Optional[str] = None,
        project_name: Optional[str] = None,
    ) -> Optional[ActivityLogEntryRecord]: ...

    def list_entries(self, *, limit: int, offset: int) -> ActivityLogPage: ...


def _row_to_record(row: dict) -> ActivityLogEntryRecord:
    return ActivityLogEntryRecord(
        id=str(row['id']),
        actor_id=str(row['actor_id']) if row['actor_id'] else None,
        actor_name=row['actor_name'],
        action=row['action'],
        summary=row['summary'],
        project_id=str(row['project_id']) if row['project_id'] else None,
        project_name=row['project_name'],
        created_at=row['created_at'],
    )


class PostgresActivityLogRepository:
    """Reads/writes the `activity_log` table (db/schema.sql)."""

    def record(self, *, actor_id, actor_name, action, summary, project_id=None, project_name=None):
        # Best-effort on purpose: every caller (login, uploads, Calculate,
        # ...) fires this as a side effect of an action that has already
        # succeeded and discards the return value, so a logging failure must
        # never surface as that action's own failure. Deliberately a broad
        # except, not a narrow one scoped to "table doesn't exist yet" --
        # this project has already shipped exactly that incident once
        # (see services/api/README.md's avatar_data_url writeup: a schema
        # change landing in code before its migration reached the live
        # database broke login entirely, with no error visible to the user
        # beyond a browser-reported "blocked by CORS" red herring). Logged
        # here instead of raised so it's still visible in the server's own
        # logs for diagnosis.
        try:
            with get_connection() as conn:
                row = conn.execute(
                    '''
                    INSERT INTO activity_log (actor_id, actor_name, action, summary, project_id, project_name)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    RETURNING *
                    ''',
                    [actor_id, actor_name, action, summary, project_id, project_name],
                ).fetchone()
            return _row_to_record(row)
        except Exception:
            logger.exception('Could not record activity log entry (action=%s) -- continuing without it.', action)
            return None

    def list_entries(self, *, limit, offset):
        with get_connection() as conn:
            total = conn.execute('SELECT count(*) AS count FROM activity_log').fetchone()['count']
            rows = conn.execute(
                'SELECT * FROM activity_log ORDER BY created_at DESC LIMIT %s OFFSET %s', [limit, offset]
            ).fetchall()
        return ActivityLogPage(entries=[_row_to_record(row) for row in rows], total=total)


class InMemoryActivityLogRepository:
    """Stand-in for tests and DB-free local runs (API_REPOSITORY=memory)."""

    def __init__(self):
        self._entries: List[ActivityLogEntryRecord] = []

    def record(self, *, actor_id, actor_name, action, summary, project_id=None, project_name=None):
        entry = ActivityLogEntryRecord(
            id=str(uuid.uuid4()), actor_id=actor_id, actor_name=actor_name, action=action, summary=summary,
            project_id=project_id, project_name=project_name, created_at=datetime.now(timezone.utc),
        )
        self._entries.append(entry)
        return entry

    def list_entries(self, *, limit, offset):
        ordered = sorted(self._entries, key=lambda e: e.created_at, reverse=True)
        return ActivityLogPage(entries=ordered[offset:offset + limit], total=len(ordered))


_memory_repository = InMemoryActivityLogRepository()
_postgres_repository = PostgresActivityLogRepository()


def get_activity_log_repository() -> ActivityLogRepository:
    """FastAPI dependency. Defaults to Postgres; set API_REPOSITORY=memory to
    run/explore the API without a database (tests override this directly)."""
    if get_settings().repository_backend == 'memory':
        return _memory_repository
    return _postgres_repository
