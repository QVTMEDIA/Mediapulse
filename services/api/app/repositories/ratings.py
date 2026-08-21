from __future__ import annotations

import uuid
from collections import Counter
from dataclasses import dataclass
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


class RatingsRepository(Protocol):
    def list_datasets(self, *, search: str = '', market: Optional[str] = None) -> List[RatingsDatasetRecord]: ...

    def get_dataset(self, ratings_dataset_id: str) -> Optional[RatingsDatasetRecord]: ...

    def create_dataset(self, data: RatingsDatasetCreate, extra_invalid_rows: int = 0) -> RatingsDatasetRecord: ...

    def list_rows(self, ratings_dataset_id: str) -> Optional[List[RatingRowRecord]]: ...

    def attach_to_project(self, project_id: str, ratings_dataset_id: str) -> bool: ...

    def detach_from_project(self, project_id: str, ratings_dataset_id: str) -> bool: ...

    def list_project_datasets(self, project_id: str) -> List[RatingsDatasetRecord]: ...

    def list_project_rating_rows(self, project_id: str) -> List[RatingRowRecord]: ...


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
            conn.execute(
                '''
                INSERT INTO project_ratings_datasets (project_id, ratings_dataset_id)
                VALUES (%s, %s)
                ON CONFLICT DO NOTHING
                ''',
                [project_id, ratings_dataset_id],
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
                SELECT rd.* FROM ratings_datasets rd
                JOIN project_ratings_datasets prd ON prd.ratings_dataset_id = rd.id
                WHERE prd.project_id = %s
                ORDER BY prd.attached_at DESC
                ''',
                [project_id],
            ).fetchall()
        return [_dataset_row_to_record(row) for row in rows]

    def list_project_rating_rows(self, project_id):
        with get_connection() as conn:
            rows = conn.execute(
                '''
                SELECT r.* FROM ratings r
                JOIN project_ratings_datasets prd ON prd.ratings_dataset_id = r.ratings_dataset_id
                WHERE prd.project_id = %s
                ''',
                [project_id],
            ).fetchall()
        return [_rating_row_to_record(row) for row in rows]


class InMemoryRatingsRepository:
    """Stand-in for tests and DB-free local runs (API_REPOSITORY=memory)."""

    def __init__(self):
        self._datasets: Dict[str, RatingsDatasetRecord] = {}
        self._rows: Dict[str, List[RatingRowRecord]] = {}
        self._attachments: Dict[str, set] = {}  # project_id -> {ratings_dataset_id, ...}

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
        self._attachments.setdefault(project_id, set()).add(ratings_dataset_id)
        return True

    def detach_from_project(self, project_id, ratings_dataset_id):
        attached = self._attachments.get(project_id, set())
        if ratings_dataset_id not in attached:
            return False
        attached.discard(ratings_dataset_id)
        return True

    def list_project_datasets(self, project_id):
        dataset_ids = self._attachments.get(project_id, set())
        records = [self._datasets[d_id] for d_id in dataset_ids if d_id in self._datasets]
        return sorted(records, key=lambda r: r.uploaded_at, reverse=True)

    def list_project_rating_rows(self, project_id):
        dataset_ids = self._attachments.get(project_id, set())
        rows = []
        for dataset_id in dataset_ids:
            rows.extend(self._rows.get(dataset_id, []))
        return rows


_memory_repository = InMemoryRatingsRepository()
_postgres_repository = PostgresRatingsRepository()


def get_ratings_repository() -> RatingsRepository:
    if get_settings().repository_backend == 'memory':
        return _memory_repository
    return _postgres_repository
