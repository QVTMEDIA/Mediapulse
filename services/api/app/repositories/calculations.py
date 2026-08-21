from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import date as date_type
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Protocol

from ..calculations import RunResult
from ..config import get_settings
from ..db import get_connection


@dataclass
class GrpRunRecord:
    id: str
    project_id: str
    total_brands: int
    total_spots: int
    total_grps: float
    total_spend: float
    matched_rows: int
    unmatched_rows: int
    is_current: bool
    generated_at: datetime


@dataclass
class BrandShareRecord:
    run_id: str
    brand_id: str
    total_grps: float
    tv_grps: float
    cable_tv_grps: float
    radio_grps: float
    sov: float
    spots: int
    avg_rating: Optional[float]
    total_spend: float
    soe: float


@dataclass
class GrpCalculationRecord:
    id: str
    run_id: str
    media_activity_id: str
    brand_id: str
    station: str
    programme: str
    day: str
    medium: str
    time_band: str
    spots: int
    rating: float
    grp: float
    calculated_at: datetime
    activity_date: Optional[date_type]


@dataclass
class StationShareRecord:
    run_id: str
    brand_id: str
    station: str
    total_grps: float
    spots: int


@dataclass
class ProgrammeShareRecord:
    run_id: str
    brand_id: str
    programme: str
    total_grps: float
    spots: int


@dataclass
class DaypartShareRecord:
    # Grouped by the vendor's own daypart/time-band label (media_activity.
    # time_band), not a canonical bucket this app defines — see
    # grp_calculator.py's SYNONYMS['time_band'] comment. Rows with no
    # daypart mapped share the '' bucket, same as station/programme would
    # for an unmapped value.
    run_id: str
    brand_id: str
    time_band: str
    total_grps: float
    spots: int


@dataclass
class TrendPointRecord:
    run_id: str
    brand_id: str
    week_start: date_type
    total_grps: float
    spots: int


class CalculationsRepository(Protocol):
    def create_run(self, project_id: str, result: RunResult) -> GrpRunRecord: ...

    def list_runs(self, project_id: str) -> List[GrpRunRecord]: ...

    def get_latest_run(self, project_id: str) -> Optional[GrpRunRecord]: ...

    def restore_run(self, project_id: str, run_id: str) -> Optional[GrpRunRecord]: ...

    def has_calculations_for_media_activity(self, media_activity_ids: List[str]) -> bool: ...

    def list_brand_shares(self, project_id: str, run_id: str) -> Optional[List[BrandShareRecord]]: ...

    def list_calculations(self, project_id: str, run_id: str) -> Optional[List[GrpCalculationRecord]]: ...

    def list_station_shares(self, project_id: str, run_id: str) -> Optional[List[StationShareRecord]]: ...

    def list_programme_shares(self, project_id: str, run_id: str) -> Optional[List[ProgrammeShareRecord]]: ...

    def list_daypart_shares(self, project_id: str, run_id: str) -> Optional[List[DaypartShareRecord]]: ...

    def list_trend(self, project_id: str, run_id: str) -> Optional[List[TrendPointRecord]]: ...


def _run_row_to_record(row: dict) -> GrpRunRecord:
    return GrpRunRecord(
        id=str(row['id']),
        project_id=str(row['project_id']),
        total_brands=row['total_brands'],
        total_spots=row['total_spots'],
        total_grps=float(row['total_grps']),
        total_spend=float(row['total_spend']),
        matched_rows=row['matched_rows'],
        unmatched_rows=row['unmatched_rows'],
        is_current=row['is_current'],
        generated_at=row['generated_at'],
    )


def _share_row_to_record(row: dict) -> BrandShareRecord:
    return BrandShareRecord(
        run_id=str(row['run_id']),
        brand_id=str(row['brand_id']),
        total_grps=float(row['total_grps']),
        tv_grps=float(row['tv_grps']),
        cable_tv_grps=float(row['cable_tv_grps']),
        radio_grps=float(row['radio_grps']),
        sov=float(row['sov']),
        spots=row['spots'],
        avg_rating=float(row['avg_rating']) if row['avg_rating'] is not None else None,
        total_spend=float(row['total_spend']),
        soe=float(row['soe']),
    )


def _calculation_row_to_record(row: dict) -> GrpCalculationRecord:
    return GrpCalculationRecord(
        id=str(row['id']),
        run_id=str(row['run_id']),
        media_activity_id=str(row['media_activity_id']),
        brand_id=str(row['brand_id']),
        station=row['station'] or '',
        programme=row['programme'] or '',
        day=row['day'] or '',
        medium=row['medium'] or '',
        time_band=row['time_band'] or '',
        spots=row['spots'],
        rating=float(row['rating']),
        grp=float(row['grp']),
        calculated_at=row['calculated_at'],
        activity_date=row.get('activity_date'),
    )


class PostgresCalculationsRepository:
    """Reads/writes `grp_runs`, `grp_calculations`, and `brand_shares` (db/schema.sql)."""

    def create_run(self, project_id, result: RunResult):
        with get_connection() as conn:
            # A fresh calculation is always the new "current" version — undo
            # that on every prior run for this project first, so exactly one
            # stays true (see the is_current comment on grp_runs in
            # db/schema.sql; nothing here enforces it at the DB level).
            conn.execute('UPDATE grp_runs SET is_current = false WHERE project_id = %s', [project_id])
            run_row = conn.execute(
                '''
                INSERT INTO grp_runs (project_id, total_brands, total_spots, total_grps, total_spend, matched_rows, unmatched_rows, is_current)
                VALUES (%s, %s, %s, %s, %s, %s, %s, true)
                RETURNING *
                ''',
                [project_id, result.total_brands, result.total_spots, result.total_grps, result.total_spend,
                 result.matched_rows, result.unmatched_rows],
            ).fetchone()
            run_id = run_row['id']
            if result.calculated_rows:
                with conn.cursor() as cur:
                    cur.executemany(
                        '''
                        INSERT INTO grp_calculations (run_id, media_activity_id, rating_match_id, spots, rating, grp)
                        VALUES (%s, %s, %s, %s, %s, %s)
                        ''',
                        [
                            (run_id, row.media_activity_id, row.rating_match_id, row.spots, row.rating, row.grp)
                            for row in result.calculated_rows
                        ],
                    )
            if result.brand_shares:
                with conn.cursor() as cur:
                    cur.executemany(
                        '''
                        INSERT INTO brand_shares (run_id, brand_id, total_grps, tv_grps, cable_tv_grps, radio_grps, sov, spots, avg_rating, total_spend, soe)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ''',
                        [
                            (run_id, share.brand_id, share.total_grps, share.tv_grps, share.cable_tv_grps,
                             share.radio_grps, share.sov, share.spots, share.avg_rating, share.total_spend, share.soe)
                            for share in result.brand_shares
                        ],
                    )
        return _run_row_to_record(run_row)

    def list_runs(self, project_id):
        with get_connection() as conn:
            rows = conn.execute(
                'SELECT * FROM grp_runs WHERE project_id = %s ORDER BY generated_at DESC', [project_id]
            ).fetchall()
        return [_run_row_to_record(row) for row in rows]

    def get_latest_run(self, project_id):
        with get_connection() as conn:
            # "Latest" means "current version" (is_current), which is the
            # newest run unless a restore pinned it back to an older one —
            # not literally MAX(generated_at). Falls back to the newest run
            # by timestamp if no row is marked current for some reason (e.g.
            # a row inserted before this column existed), so this never
            # regresses to "no latest run" for an otherwise-normal project.
            row = conn.execute(
                'SELECT * FROM grp_runs WHERE project_id = %s AND is_current ORDER BY generated_at DESC LIMIT 1',
                [project_id],
            ).fetchone()
            if row is None:
                row = conn.execute(
                    'SELECT * FROM grp_runs WHERE project_id = %s ORDER BY generated_at DESC LIMIT 1', [project_id]
                ).fetchone()
        return _run_row_to_record(row) if row else None

    def restore_run(self, project_id, run_id):
        with get_connection() as conn:
            target = conn.execute(
                'SELECT id FROM grp_runs WHERE project_id = %s AND id = %s', [project_id, run_id]
            ).fetchone()
            if target is None:
                return None
            conn.execute('UPDATE grp_runs SET is_current = false WHERE project_id = %s', [project_id])
            row = conn.execute(
                'UPDATE grp_runs SET is_current = true WHERE id = %s RETURNING *', [run_id]
            ).fetchone()
        return _run_row_to_record(row)

    def has_calculations_for_media_activity(self, media_activity_ids):
        if not media_activity_ids:
            return False
        with get_connection() as conn:
            row = conn.execute(
                'SELECT EXISTS(SELECT 1 FROM grp_calculations WHERE media_activity_id = ANY(%s)) AS found',
                [media_activity_ids],
            ).fetchone()
        return bool(row['found'])

    def _run_exists(self, conn, project_id, run_id):
        return conn.execute(
            'SELECT id FROM grp_runs WHERE project_id = %s AND id = %s', [project_id, run_id]
        ).fetchone()

    def list_brand_shares(self, project_id, run_id):
        with get_connection() as conn:
            if self._run_exists(conn, project_id, run_id) is None:
                return None
            rows = conn.execute(
                'SELECT * FROM brand_shares WHERE run_id = %s ORDER BY total_grps DESC', [run_id]
            ).fetchall()
        return [_share_row_to_record(row) for row in rows]

    def list_calculations(self, project_id, run_id):
        with get_connection() as conn:
            if self._run_exists(conn, project_id, run_id) is None:
                return None
            rows = conn.execute(
                '''
                SELECT gc.*, ma.brand_id, ma.station, ma.programme, ma.day, ma.medium, ma.time_band, ma.activity_date
                FROM grp_calculations gc
                JOIN media_activity ma ON ma.id = gc.media_activity_id
                WHERE gc.run_id = %s
                ORDER BY gc.grp DESC
                ''',
                [run_id],
            ).fetchall()
        return [_calculation_row_to_record(row) for row in rows]

    def list_station_shares(self, project_id, run_id):
        # Reuses the grp_by_station view (db/schema.sql) rather than
        # re-deriving the same join/group-by here.
        with get_connection() as conn:
            if self._run_exists(conn, project_id, run_id) is None:
                return None
            rows = conn.execute(
                '''
                SELECT run_id, brand_id, station, total_grps, total_spots
                FROM grp_by_station WHERE run_id = %s ORDER BY total_grps DESC
                ''',
                [run_id],
            ).fetchall()
        return [
            StationShareRecord(
                run_id=str(row['run_id']), brand_id=str(row['brand_id']), station=row['station'] or '',
                total_grps=float(row['total_grps']), spots=int(row['total_spots']),
            )
            for row in rows
        ]

    def list_programme_shares(self, project_id, run_id):
        with get_connection() as conn:
            if self._run_exists(conn, project_id, run_id) is None:
                return None
            rows = conn.execute(
                '''
                SELECT run_id, brand_id, programme, total_grps, total_spots
                FROM grp_by_programme WHERE run_id = %s ORDER BY total_grps DESC
                ''',
                [run_id],
            ).fetchall()
        return [
            ProgrammeShareRecord(
                run_id=str(row['run_id']), brand_id=str(row['brand_id']), programme=row['programme'] or '',
                total_grps=float(row['total_grps']), spots=int(row['total_spots']),
            )
            for row in rows
        ]

    def list_daypart_shares(self, project_id, run_id):
        # Reuses the grp_by_daypart view (db/schema.sql), same pattern as
        # list_station_shares/list_programme_shares above.
        with get_connection() as conn:
            if self._run_exists(conn, project_id, run_id) is None:
                return None
            rows = conn.execute(
                '''
                SELECT run_id, brand_id, time_band, total_grps, total_spots
                FROM grp_by_daypart WHERE run_id = %s ORDER BY total_grps DESC
                ''',
                [run_id],
            ).fetchall()
        return [
            DaypartShareRecord(
                run_id=str(row['run_id']), brand_id=str(row['brand_id']), time_band=row['time_band'] or '',
                total_grps=float(row['total_grps']), spots=int(row['total_spots']),
            )
            for row in rows
        ]

    def list_trend(self, project_id, run_id):
        with get_connection() as conn:
            if self._run_exists(conn, project_id, run_id) is None:
                return None
            rows = conn.execute(
                '''
                SELECT gc.run_id, ma.brand_id, date_trunc('week', ma.activity_date)::date AS week_start,
                       sum(gc.grp) AS total_grps, sum(gc.spots) AS total_spots
                FROM grp_calculations gc
                JOIN media_activity ma ON ma.id = gc.media_activity_id
                WHERE gc.run_id = %s AND ma.activity_date IS NOT NULL
                GROUP BY gc.run_id, ma.brand_id, week_start
                ORDER BY week_start, ma.brand_id
                ''',
                [run_id],
            ).fetchall()
        return [
            TrendPointRecord(
                run_id=str(row['run_id']), brand_id=str(row['brand_id']), week_start=row['week_start'],
                total_grps=float(row['total_grps']), spots=int(row['total_spots']),
            )
            for row in rows
        ]


class InMemoryCalculationsRepository:
    """Stand-in for tests and DB-free local runs (API_REPOSITORY=memory)."""

    def __init__(self):
        self._runs: Dict[str, GrpRunRecord] = {}
        self._shares: Dict[str, List[BrandShareRecord]] = {}
        self._calculations: Dict[str, List[GrpCalculationRecord]] = {}

    def create_run(self, project_id, result: RunResult):
        now = datetime.now(timezone.utc)
        for existing in self._runs.values():
            if existing.project_id == project_id:
                existing.is_current = False
        run = GrpRunRecord(
            id=str(uuid.uuid4()), project_id=project_id, total_brands=result.total_brands,
            total_spots=result.total_spots, total_grps=result.total_grps, total_spend=result.total_spend,
            matched_rows=result.matched_rows, unmatched_rows=result.unmatched_rows, is_current=True, generated_at=now,
        )
        self._runs[run.id] = run
        self._shares[run.id] = [
            BrandShareRecord(
                run_id=run.id, brand_id=share.brand_id, total_grps=share.total_grps, tv_grps=share.tv_grps,
                cable_tv_grps=share.cable_tv_grps, radio_grps=share.radio_grps, sov=share.sov, spots=share.spots,
                avg_rating=share.avg_rating, total_spend=share.total_spend, soe=share.soe,
            )
            for share in result.brand_shares
        ]
        self._calculations[run.id] = [
            GrpCalculationRecord(
                id=str(uuid.uuid4()), run_id=run.id, media_activity_id=row.media_activity_id,
                brand_id=row.brand_id, station=row.station, programme=row.programme, day=row.day,
                medium=row.medium, time_band=row.time_band, spots=row.spots, rating=row.rating, grp=row.grp,
                calculated_at=now, activity_date=row.activity_date,
            )
            for row in result.calculated_rows
        ]
        return run

    def list_runs(self, project_id):
        records = [r for r in self._runs.values() if r.project_id == project_id]
        return sorted(records, key=lambda r: r.generated_at, reverse=True)

    def get_latest_run(self, project_id):
        runs = self.list_runs(project_id)
        current = next((r for r in runs if r.is_current), None)
        return current if current is not None else (runs[0] if runs else None)

    def restore_run(self, project_id, run_id):
        target = self._runs.get(run_id)
        if target is None or target.project_id != project_id:
            return None
        for existing in self._runs.values():
            if existing.project_id == project_id:
                existing.is_current = False
        target.is_current = True
        return target

    def has_calculations_for_media_activity(self, media_activity_ids):
        ids = set(media_activity_ids)
        if not ids:
            return False
        return any(row.media_activity_id in ids for rows in self._calculations.values() for row in rows)

    def _get_run_calculations(self, project_id, run_id):
        run = self._runs.get(run_id)
        if run is None or run.project_id != project_id:
            return None
        return self._calculations.get(run_id, [])

    def list_brand_shares(self, project_id, run_id):
        run = self._runs.get(run_id)
        if run is None or run.project_id != project_id:
            return None
        return sorted(self._shares.get(run_id, []), key=lambda s: s.total_grps, reverse=True)

    def list_calculations(self, project_id, run_id):
        calculations = self._get_run_calculations(project_id, run_id)
        if calculations is None:
            return None
        return sorted(calculations, key=lambda c: c.grp, reverse=True)

    def list_station_shares(self, project_id, run_id):
        calculations = self._get_run_calculations(project_id, run_id)
        if calculations is None:
            return None
        totals: Dict[tuple, List[float]] = defaultdict(lambda: [0.0, 0])
        for row in calculations:
            bucket = totals[(row.brand_id, row.station)]
            bucket[0] += row.grp
            bucket[1] += row.spots
        records = [
            StationShareRecord(run_id=run_id, brand_id=brand_id, station=station, total_grps=grp, spots=spots)
            for (brand_id, station), (grp, spots) in totals.items()
        ]
        return sorted(records, key=lambda r: r.total_grps, reverse=True)

    def list_programme_shares(self, project_id, run_id):
        calculations = self._get_run_calculations(project_id, run_id)
        if calculations is None:
            return None
        totals: Dict[tuple, List[float]] = defaultdict(lambda: [0.0, 0])
        for row in calculations:
            bucket = totals[(row.brand_id, row.programme)]
            bucket[0] += row.grp
            bucket[1] += row.spots
        records = [
            ProgrammeShareRecord(run_id=run_id, brand_id=brand_id, programme=programme, total_grps=grp, spots=spots)
            for (brand_id, programme), (grp, spots) in totals.items()
        ]
        return sorted(records, key=lambda r: r.total_grps, reverse=True)

    def list_daypart_shares(self, project_id, run_id):
        calculations = self._get_run_calculations(project_id, run_id)
        if calculations is None:
            return None
        totals: Dict[tuple, List[float]] = defaultdict(lambda: [0.0, 0])
        for row in calculations:
            bucket = totals[(row.brand_id, row.time_band)]
            bucket[0] += row.grp
            bucket[1] += row.spots
        records = [
            DaypartShareRecord(run_id=run_id, brand_id=brand_id, time_band=time_band, total_grps=grp, spots=spots)
            for (brand_id, time_band), (grp, spots) in totals.items()
        ]
        return sorted(records, key=lambda r: r.total_grps, reverse=True)

    def list_trend(self, project_id, run_id):
        calculations = self._get_run_calculations(project_id, run_id)
        if calculations is None:
            return None
        totals: Dict[tuple, List[float]] = defaultdict(lambda: [0.0, 0])
        for row in calculations:
            if row.activity_date is None:
                continue
            week_start = row.activity_date - timedelta(days=row.activity_date.weekday())
            bucket = totals[(row.brand_id, week_start)]
            bucket[0] += row.grp
            bucket[1] += row.spots
        records = [
            TrendPointRecord(run_id=run_id, brand_id=brand_id, week_start=week_start, total_grps=grp, spots=spots)
            for (brand_id, week_start), (grp, spots) in totals.items()
        ]
        return sorted(records, key=lambda r: (r.week_start, r.brand_id))


_memory_repository = InMemoryCalculationsRepository()
_postgres_repository = PostgresCalculationsRepository()


def get_calculations_repository() -> CalculationsRepository:
    if get_settings().repository_backend == 'memory':
        return _memory_repository
    return _postgres_repository
