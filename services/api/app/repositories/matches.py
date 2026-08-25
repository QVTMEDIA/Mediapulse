from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, List, Optional, Protocol

from ..config import get_settings
from ..db import get_connection
from ..matches import compute_matches


@dataclass
class RatingMatchRecord:
    id: str
    media_activity_id: str
    matched_rating_id: Optional[str]
    match_status: str
    match_confidence: Optional[float]
    match_key: str
    corrected_at: Optional[datetime]


class MatchesRepository(Protocol):
    def list_matches(self, project_id: str) -> List[RatingMatchRecord]: ...

    def get_match_for_project(self, project_id: str, rating_match_id: str) -> Optional[RatingMatchRecord]: ...

    def ensure_matches_computed(
        self, project_id: str, media_activity_records, rating_records
    ) -> List[RatingMatchRecord]: ...

    def correct_match(self, rating_match_id: str, matched_rating_id: Optional[str]) -> Optional[RatingMatchRecord]: ...

    def update_match(
        self, rating_match_id: str, matched_rating_id: Optional[str], match_status: str, match_confidence: Optional[float]
    ) -> Optional[RatingMatchRecord]: ...

    def update_matches_bulk(
        self, updates: List['tuple[str, Optional[str], str, Optional[float]]']
    ) -> None: ...

    def delete_matches_for_media_activity(self, media_activity_ids: List[str]) -> None: ...


def _row_to_record(row: dict) -> RatingMatchRecord:
    return RatingMatchRecord(
        id=str(row['id']),
        media_activity_id=str(row['media_activity_id']),
        matched_rating_id=str(row['matched_rating_id']) if row['matched_rating_id'] else None,
        match_status=row['match_status'],
        match_confidence=float(row['match_confidence']) if row['match_confidence'] is not None else None,
        match_key=row['match_key'],
        corrected_at=row['corrected_at'],
    )


class PostgresMatchesRepository:
    """Reads/writes `rating_matches` (db/schema.sql)."""

    def list_matches(self, project_id):
        with get_connection() as conn:
            rows = conn.execute(
                '''
                SELECT rm.* FROM rating_matches rm
                JOIN media_activity ma ON ma.id = rm.media_activity_id
                WHERE ma.project_id = %s
                ORDER BY rm.id
                ''',
                [project_id],
            ).fetchall()
        return [_row_to_record(row) for row in rows]

    def get_match_for_project(self, project_id, rating_match_id):
        with get_connection() as conn:
            row = conn.execute(
                '''
                SELECT rm.* FROM rating_matches rm
                JOIN media_activity ma ON ma.id = rm.media_activity_id
                WHERE ma.project_id = %s AND rm.id = %s
                ''',
                [project_id, rating_match_id],
            ).fetchone()
        return _row_to_record(row) if row else None

    def ensure_matches_computed(self, project_id, media_activity_records, rating_records):
        with get_connection() as conn:
            existing_ids = {
                str(row['media_activity_id'])
                for row in conn.execute(
                    '''
                    SELECT rm.media_activity_id FROM rating_matches rm
                    JOIN media_activity ma ON ma.id = rm.media_activity_id
                    WHERE ma.project_id = %s
                    ''',
                    [project_id],
                ).fetchall()
            }
        pending = [activity for activity in media_activity_records if activity.id not in existing_ids]
        if pending:
            computed = compute_matches(pending, rating_records)
            with get_connection() as conn:
                with conn.cursor() as cur:
                    cur.executemany(
                        '''
                        INSERT INTO rating_matches (media_activity_id, matched_rating_id, match_status, match_confidence, match_key)
                        VALUES (%s, %s, %s, %s, %s)
                        ON CONFLICT (media_activity_id) DO NOTHING
                        ''',
                        [
                            (c.media_activity_id, c.matched_rating_id, c.match_status, c.match_confidence, c.match_key)
                            for c in computed
                        ],
                    )
        return self.list_matches(project_id)

    def correct_match(self, rating_match_id, matched_rating_id):
        with get_connection() as conn:
            row = conn.execute(
                '''
                UPDATE rating_matches
                SET matched_rating_id = %s, match_status = 'manual', corrected_at = now()
                WHERE id = %s
                RETURNING *
                ''',
                [matched_rating_id, rating_match_id],
            ).fetchone()
        return _row_to_record(row) if row else None

    def update_match(self, rating_match_id, matched_rating_id, match_status, match_confidence):
        # Used by /recompute — sets an automatically-computed result, unlike
        # correct_match() which always forces 'manual' and stamps corrected_at.
        with get_connection() as conn:
            row = conn.execute(
                '''
                UPDATE rating_matches
                SET matched_rating_id = %s, match_status = %s, match_confidence = %s
                WHERE id = %s
                RETURNING *
                ''',
                [matched_rating_id, match_status, match_confidence, rating_match_id],
            ).fetchone()
        return _row_to_record(row) if row else None

    def update_matches_bulk(self, updates):
        # Same effect as calling update_match() once per row, in one
        # connection instead of one per row -- found live as the real
        # bottleneck behind "Full scan barely ever completes" on a large
        # project: match_jobs.py's _run_recompute used to call update_match()
        # (one fresh Postgres connection each -- see db.py's get_connection())
        # once per row it just resolved, the exact same N-fresh-connections
        # mistake fixed elsewhere in routers/runs.py and routers/exports.py,
        # just on the write side of matching instead of a read. A recompute
        # that resolves thousands of previously-unmatched rows meant
        # thousands of sequential connection round trips before this.
        updates = list(updates)
        if not updates:
            return
        with get_connection() as conn:
            with conn.cursor() as cur:
                cur.executemany(
                    '''
                    UPDATE rating_matches
                    SET matched_rating_id = %s, match_status = %s, match_confidence = %s
                    WHERE id = %s
                    ''',
                    [
                        (matched_rating_id, match_status, match_confidence, rating_match_id)
                        for rating_match_id, matched_rating_id, match_status, match_confidence in updates
                    ],
                )

    def delete_matches_for_media_activity(self, media_activity_ids):
        # Redundant with media_activity's ON DELETE CASCADE onto
        # rating_matches (db/schema.sql) in the normal "delete the upload/
        # brand too" flow, but explicit here so this repository's own
        # contract doesn't depend on a caller also deleting media_activity
        # in the same breath — matches app/routers/uploads.py and brands.py
        # calling this before deleting anything else.
        if not media_activity_ids:
            return
        with get_connection() as conn:
            conn.execute('DELETE FROM rating_matches WHERE media_activity_id = ANY(%s)', [media_activity_ids])


class InMemoryMatchesRepository:
    """Stand-in for tests and DB-free local runs (API_REPOSITORY=memory)."""

    def __init__(self):
        self._rows: Dict[str, RatingMatchRecord] = {}
        self._project_by_activity: Dict[str, str] = {}

    def list_matches(self, project_id):
        return [
            record for record in self._rows.values()
            if self._project_by_activity.get(record.media_activity_id) == project_id
        ]

    def get_match_for_project(self, project_id, rating_match_id):
        record = self._rows.get(rating_match_id)
        if record and self._project_by_activity.get(record.media_activity_id) == project_id:
            return record
        return None

    def ensure_matches_computed(self, project_id, media_activity_records, rating_records):
        existing_ids = {record.media_activity_id for record in self._rows.values()}
        pending = [activity for activity in media_activity_records if activity.id not in existing_ids]
        for activity in pending:
            self._project_by_activity[activity.id] = project_id
        for computed in compute_matches(pending, rating_records):
            record = RatingMatchRecord(
                id=str(uuid.uuid4()),
                media_activity_id=computed.media_activity_id,
                matched_rating_id=computed.matched_rating_id,
                match_status=computed.match_status,
                match_confidence=computed.match_confidence,
                match_key=computed.match_key,
                corrected_at=None,
            )
            self._rows[record.id] = record
        return self.list_matches(project_id)

    def correct_match(self, rating_match_id, matched_rating_id):
        record = self._rows.get(rating_match_id)
        if record is None:
            return None
        record.matched_rating_id = matched_rating_id
        record.match_status = 'manual'
        record.corrected_at = datetime.now(timezone.utc)
        return record

    def update_match(self, rating_match_id, matched_rating_id, match_status, match_confidence):
        record = self._rows.get(rating_match_id)
        if record is None:
            return None
        record.matched_rating_id = matched_rating_id
        record.match_status = match_status
        record.match_confidence = match_confidence
        return record

    def update_matches_bulk(self, updates):
        for rating_match_id, matched_rating_id, match_status, match_confidence in updates:
            self.update_match(rating_match_id, matched_rating_id, match_status, match_confidence)

    def delete_matches_for_media_activity(self, media_activity_ids):
        ids = set(media_activity_ids)
        if not ids:
            return
        stale_match_ids = [rid for rid, record in self._rows.items() if record.media_activity_id in ids]
        for match_id in stale_match_ids:
            del self._rows[match_id]
        for activity_id in ids:
            self._project_by_activity.pop(activity_id, None)


_memory_repository = InMemoryMatchesRepository()
_postgres_repository = PostgresMatchesRepository()


def get_matches_repository() -> MatchesRepository:
    if get_settings().repository_backend == 'memory':
        return _memory_repository
    return _postgres_repository
