from __future__ import annotations

import uuid
from collections import Counter
from dataclasses import dataclass, replace
from datetime import datetime, time, timezone
from typing import Dict, List, Optional, Protocol

from ..config import get_settings
from ..db import get_connection
from ..matching import make_match_key
from ..schemas.ratings import RatingRowIn, RatingsDatasetCreate


def _row_is_invalid(row: RatingRowIn) -> bool:
    return not (row.medium.strip() and row.station.strip() and row.day.strip()) or row.rating is None


def _summarize_rows(rows: List[RatingRowIn]):
    keys = [make_match_key(r.medium, r.station, r.day, r.programme, r.time_band) for r in rows]
    duplicate_keys = sum(1 for _key, count in Counter(keys).items() if count > 1)
    invalid_rows = sum(1 for row in rows if _row_is_invalid(row))
    status = 'Ready' if invalid_rows == 0 else 'Needs Review'
    return invalid_rows, duplicate_keys, status


@dataclass
class RatingRowRecord:
    id: str
    ratings_dataset_id: str
    medium: str
    station: str
    day: str
    programme: str
    time_band: str
    rating: Optional[float]
    start_time: Optional[time]
    end_time: Optional[time]
    week: Optional[int]
    month: Optional[int]
    project_attached_at: Optional[datetime] = None
    priority: Optional[int] = None  # project_ratings_datasets.priority (lower wins); only set on project-scoped listings


@dataclass
class RatingsDatasetRecord:
    id: str
    provider: str
    period: str
    market: str
    audience: str
    media_types: List[str]
    row_count: int
    invalid_rows: int
    duplicate_keys: int
    status: str
    uploaded_at: datetime


@dataclass
class ProjectRatingsDatasetRecord(RatingsDatasetRecord):
    """A dataset as attached to one particular project -- adds `priority`
    (lower wins; see project_ratings_datasets in db/schema.sql), meaningless
    outside a project's attachment. Subclasses RatingsDatasetRecord rather
    than wrapping it so every existing caller of list_project_datasets that
    only reads the base fields (e.g. routers/validation.py) keeps working
    untouched -- only routers/ratings.py's project-scoped listing route and
    the new reorder endpoint need the extra field."""

    priority: int = 0


class RatingsRepository(Protocol):
    def list_datasets(self, *, search: str = '', market: Optional[str] = None) -> List[RatingsDatasetRecord]: ...

    def get_dataset(self, ratings_dataset_id: str) -> Optional[RatingsDatasetRecord]: ...

    def create_dataset(self, data: RatingsDatasetCreate, extra_invalid_rows: int = 0) -> RatingsDatasetRecord: ...

    def list_rows(self, ratings_dataset_id: str) -> Optional[List[RatingRowRecord]]: ...

    def attach_to_project(self, project_id: str, ratings_dataset_id: str) -> bool: ...

    def detach_from_project(self, project_id: str, ratings_dataset_id: str) -> bool: ...

    def list_project_datasets(self, project_id: str) -> List[ProjectRatingsDatasetRecord]: ...

    def list_project_rating_rows(self, project_id: str) -> List[RatingRowRecord]: ...

    def reorder_project_datasets(self, project_id: str, ordered_dataset_ids: List[str]) -> bool:
        """Sets priority = position in `ordered_dataset_ids` (0 = highest)
        for every dataset attached to this project. Returns False (no
        change made) if the given ids don't exactly match the currently-
        attached set -- callers turn that into a 422, since a partial or
        stale list would silently leave some attached dataset's priority
        untouched rather than reflecting the order the caller actually
        asked for."""
        ...


def _dataset_row_to_record(row: dict) -> RatingsDatasetRecord:
    return RatingsDatasetRecord(
        id=str(row['id']),
        provider=row['provider'] or '',
        period=row['period'] or '',
        market=row['market'] or '',
        audience=row['audience'] or '',
        media_types=list(row['media_types'] or []),
        row_count=row['row_count'],
        invalid_rows=row['invalid_rows'],
        duplicate_keys=row['duplicate_keys'],
        status=row['status'],
        uploaded_at=row['uploaded_at'],
    )


def _project_dataset_row_to_record(row: dict) -> ProjectRatingsDatasetRecord:
    base = _dataset_row_to_record(row)
    return ProjectRatingsDatasetRecord(priority=row['priority'], **vars(base))


def _rating_row_to_record(row: dict) -> RatingRowRecord:
    return RatingRowRecord(
        id=str(row['id']),
        ratings_dataset_id=str(row['ratings_dataset_id']),
        medium=row['medium'] or '',
        station=row['station'] or '',
        day=row['day'] or '',
        programme=row['programme'] or '',
        time_band=row['time_band'] or '',
        rating=row['rating'],
        start_time=row['start_time'],
        end_time=row['end_time'],
        week=row['week'],
        month=row['month'],
        project_attached_at=row.get('project_attached_at'),
        priority=row.get('priority'),
    )


class PostgresRatingsRepository:
    """Reads/writes `ratings_datasets`, `ratings`, and `project_ratings_datasets`."""

    def list_datasets(self, *, search='', market=None):
        clauses = []
        params: list = []
        if search:
            clauses.append('(provider ILIKE %s OR period ILIKE %s OR market ILIKE %s)')
            like = f'%{search}%'
            params += [like, like, like]
        if market:
            clauses.append('market = %s')
            params.append(market)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ''
        query = f'SELECT * FROM ratings_datasets {where} ORDER BY uploaded_at DESC'
        with get_connection() as conn:
            rows = conn.execute(query, params).fetchall()
        return [_dataset_row_to_record(row) for row in rows]

    def get_dataset(self, ratings_dataset_id):
        with get_connection() as conn:
            row = conn.execute(
                'SELECT * FROM ratings_datasets WHERE id = %s', [ratings_dataset_id]
            ).fetchone()
        return _dataset_row_to_record(row) if row else None

    def create_dataset(self, data: RatingsDatasetCreate, extra_invalid_rows: int = 0):
        invalid_rows, duplicate_keys, _ = _summarize_rows(data.rows)
        invalid_rows += extra_invalid_rows
        row_count = len(data.rows) + extra_invalid_rows
        status = 'Ready' if invalid_rows == 0 else 'Needs Review'
        with get_connection() as conn:
            dataset_row = conn.execute(
                '''
                INSERT INTO ratings_datasets (
                    provider, period, market, audience, media_types, row_count,
                    invalid_rows, duplicate_keys, status
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING *
                ''',
                [
                    data.provider, data.period, data.market, data.audience, data.media_types,
                    row_count, invalid_rows, duplicate_keys, status,
                ],
            ).fetchone()
            if data.rows:
                with conn.cursor() as cur:
                    cur.executemany(
                        '''
                        INSERT INTO ratings (
                            ratings_dataset_id, medium, station, day, programme, time_band,
                            rating, start_time, end_time, week, month
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ''',
                        [
                            (
                                dataset_row['id'], row.medium, row.station, row.day, row.programme,
                                row.time_band, row.rating, row.start_time, row.end_time, row.week, row.month,
                            )
                            for row in data.rows
                        ],
                    )
        return _dataset_row_to_record(dataset_row)

    def list_rows(self, ratings_dataset_id):
        if self.get_dataset(ratings_dataset_id) is None:
            return None
        with get_connection() as conn:
            rows = conn.execute(
                'SELECT * FROM ratings WHERE ratings_dataset_id = %s ORDER BY id', [ratings_dataset_id]
            ).fetchall()
        return [_rating_row_to_record(row) for row in rows]

    def attach_to_project(self, project_id, ratings_dataset_id):
        if self.get_dataset(ratings_dataset_id) is None:
            return False
        with get_connection() as conn:
            # New attachment goes to the bottom of this project's current
            # priority order (lowest precedence) -- see the column comment
            # in db/schema.sql for why that's the safe default.
            conn.execute(
                '''
                INSERT INTO project_ratings_datasets (project_id, ratings_dataset_id, priority)
                VALUES (
                    %s, %s,
                    COALESCE((SELECT MAX(priority) + 1 FROM project_ratings_datasets WHERE project_id = %s), 0)
                )
                ON CONFLICT DO NOTHING
                ''',
                [project_id, ratings_dataset_id, project_id],
            )
        return True

    def detach_from_project(self, project_id, ratings_dataset_id):
        # Only removes the project_ratings_datasets join row — the shared
        # ratings_datasets/ratings rows themselves are untouched (other
        # projects may still use them), and so is anything already
        # calculated: rating_matches.matched_rating_id still points at a
        # real ratings row, and grp_calculations still snapshot what was
        # used at the time. Detaching only affects future matching, not
        # anything already on the books.
        with get_connection() as conn:
            row = conn.execute(
                'DELETE FROM project_ratings_datasets WHERE project_id = %s AND ratings_dataset_id = %s RETURNING ratings_dataset_id',
                [project_id, ratings_dataset_id],
            ).fetchone()
        return row is not None

    def list_project_datasets(self, project_id):
        with get_connection() as conn:
            rows = conn.execute(
                '''
                SELECT rd.*, prd.priority FROM ratings_datasets rd
                JOIN project_ratings_datasets prd ON prd.ratings_dataset_id = rd.id
                WHERE prd.project_id = %s
                ORDER BY prd.priority ASC, prd.attached_at DESC
                ''',
                [project_id],
            ).fetchall()
        return [_project_dataset_row_to_record(row) for row in rows]

    def list_project_rating_rows(self, project_id):
        # Ordered by dataset priority first (lowest = highest precedence,
        # user-controlled via reorder_project_datasets), then by the
        # pre-existing attached_at/dataset_id/id tie-break for determinism
        # between datasets that are still tied on priority (e.g. two
        # datasets attached in the same request, before anyone has
        # reordered them). compute_matches's "first occurrence wins on a
        # duplicate key" pooling logic (`_rating_order_key`) mirrors this
        # exact ordering in Python, since rating_records can also come from
        # InMemoryRatingsRepository, which has no ORDER BY to rely on.
        with get_connection() as conn:
            rows = conn.execute(
                '''
                SELECT r.*, prd.attached_at AS project_attached_at, prd.priority FROM ratings r
                JOIN project_ratings_datasets prd ON prd.ratings_dataset_id = r.ratings_dataset_id
                WHERE prd.project_id = %s
                ORDER BY prd.priority ASC, prd.attached_at DESC, r.ratings_dataset_id, r.id
                ''',
                [project_id],
            ).fetchall()
        return [_rating_row_to_record(row) for row in rows]

    def reorder_project_datasets(self, project_id, ordered_dataset_ids):
        with get_connection() as conn:
            attached = {
                str(row['ratings_dataset_id'])
                for row in conn.execute(
                    'SELECT ratings_dataset_id FROM project_ratings_datasets WHERE project_id = %s', [project_id]
                ).fetchall()
            }
            if attached != set(ordered_dataset_ids):
                return False
            with conn.cursor() as cur:
                cur.executemany(
                    '''
                    UPDATE project_ratings_datasets SET priority = %s
                    WHERE project_id = %s AND ratings_dataset_id = %s
                    ''',
                    [
                        (priority, project_id, dataset_id)
                        for priority, dataset_id in enumerate(ordered_dataset_ids)
                    ],
                )
        return True


class InMemoryRatingsRepository:
    """Stand-in for tests and DB-free local runs (API_REPOSITORY=memory)."""

    def __init__(self):
        self._datasets: Dict[str, RatingsDatasetRecord] = {}
        self._rows: Dict[str, List[RatingRowRecord]] = {}
        self._attachments: Dict[str, Dict[str, datetime]] = {}  # project_id -> {ratings_dataset_id: attached_at}
        # project_id -> {ratings_dataset_id: priority} -- lower wins, same
        # meaning as project_ratings_datasets.priority in db/schema.sql.
        self._priorities: Dict[str, Dict[str, int]] = {}

    def list_datasets(self, *, search='', market=None):
        needle = search.lower()
        results = []
        for record in self._datasets.values():
            if market and record.market != market:
                continue
            haystack = f'{record.provider} {record.period} {record.market}'.lower()
            if needle and needle not in haystack:
                continue
            results.append(record)
        return sorted(results, key=lambda r: r.uploaded_at, reverse=True)

    def get_dataset(self, ratings_dataset_id):
        return self._datasets.get(ratings_dataset_id)

    def create_dataset(self, data: RatingsDatasetCreate, extra_invalid_rows: int = 0):
        invalid_rows, duplicate_keys, _ = _summarize_rows(data.rows)
        invalid_rows += extra_invalid_rows
        status = 'Ready' if invalid_rows == 0 else 'Needs Review'
        dataset_id = str(uuid.uuid4())
        record = RatingsDatasetRecord(
            id=dataset_id,
            provider=data.provider,
            period=data.period,
            market=data.market,
            audience=data.audience,
            media_types=list(data.media_types),
            row_count=len(data.rows) + extra_invalid_rows,
            invalid_rows=invalid_rows,
            duplicate_keys=duplicate_keys,
            status=status,
            uploaded_at=datetime.now(timezone.utc),
        )
        self._datasets[dataset_id] = record
        self._rows[dataset_id] = [
            RatingRowRecord(
                id=str(uuid.uuid4()), ratings_dataset_id=dataset_id, medium=row.medium, station=row.station,
                day=row.day, programme=row.programme, time_band=row.time_band, rating=row.rating,
                start_time=row.start_time, end_time=row.end_time, week=row.week, month=row.month,
            )
            for row in data.rows
        ]
        return record

    def list_rows(self, ratings_dataset_id):
        if ratings_dataset_id not in self._datasets:
            return None
        return self._rows.get(ratings_dataset_id, [])

    def attach_to_project(self, project_id, ratings_dataset_id):
        if ratings_dataset_id not in self._datasets:
            return False
        self._attachments.setdefault(project_id, {})[ratings_dataset_id] = datetime.now(timezone.utc)
        priorities = self._priorities.setdefault(project_id, {})
        if ratings_dataset_id not in priorities:
            # New attachment goes to the bottom (lowest precedence) of this
            # project's current priority order -- see attach_to_project's
            # comment on the Postgres side for why.
            priorities[ratings_dataset_id] = (max(priorities.values()) + 1) if priorities else 0
        return True

    def detach_from_project(self, project_id, ratings_dataset_id):
        attached = self._attachments.get(project_id, {})
        if ratings_dataset_id not in attached:
            return False
        del attached[ratings_dataset_id]
        self._priorities.get(project_id, {}).pop(ratings_dataset_id, None)
        return True

    def _ordered_dataset_ids(self, project_id):
        # Priority first (lowest = highest precedence), then most-recently
        # attached as the tie-break for datasets still at the same
        # priority -- mirrors PostgresRatingsRepository's ORDER BY and
        # app/matches.py's _rating_order_key.
        attached = self._attachments.get(project_id, {})
        priorities = self._priorities.get(project_id, {})
        return sorted(attached, key=lambda d_id: (priorities.get(d_id, 0), -attached[d_id].timestamp()))

    def list_project_datasets(self, project_id):
        priorities = self._priorities.get(project_id, {})
        dataset_ids = self._ordered_dataset_ids(project_id)
        records = [
            ProjectRatingsDatasetRecord(priority=priorities.get(d_id, 0), **vars(self._datasets[d_id]))
            for d_id in dataset_ids
            if d_id in self._datasets
        ]
        return records

    def list_project_rating_rows(self, project_id):
        attached = self._attachments.get(project_id, {})
        priorities = self._priorities.get(project_id, {})
        dataset_ids = self._ordered_dataset_ids(project_id)
        rows = []
        for dataset_id in dataset_ids:
            attached_at = attached[dataset_id]
            priority = priorities.get(dataset_id, 0)
            rows.extend(
                replace(row, project_attached_at=attached_at, priority=priority)
                for row in sorted(self._rows.get(dataset_id, []), key=lambda r: r.id)
            )
        return rows

    def reorder_project_datasets(self, project_id, ordered_dataset_ids):
        attached = set(self._attachments.get(project_id, {}))
        if attached != set(ordered_dataset_ids):
            return False
        self._priorities[project_id] = {
            dataset_id: priority for priority, dataset_id in enumerate(ordered_dataset_ids)
        }
        return True


_memory_repository = InMemoryRatingsRepository()
_postgres_repository = PostgresRatingsRepository()


def get_ratings_repository() -> RatingsRepository:
    if get_settings().repository_backend == 'memory':
        return _memory_repository
    return _postgres_repository
