from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Dict, List, Optional, Protocol, Tuple

from ..config import get_settings
from ..db import get_connection
from ..parsing import ParsedMediaRow


@dataclass
class MediaActivityInsert:
    """Pairs a parsed row with the brand it belongs to. brand_report uploads
    give every row the same brand_id (the one the caller picked); composite
    uploads resolve a different brand per row from the file's own Brand
    column (see routers/uploads.py), so this can't be a single upload-level
    parameter the way it used to be."""

    brand_id: str
    row: ParsedMediaRow


@dataclass
class UploadRecord:
    id: str
    project_id: str
    # Null for composite_report uploads, which span more than one brand —
    # brand attribution lives on each media_activity row instead. Always set
    # for brand_report uploads.
    brand_id: Optional[str]
    file_name: str
    kind: str
    mapped_rows: int
    issue_rows: int
    uploaded_at: datetime


@dataclass
class MediaActivityRecord:
    id: str
    project_id: str
    brand_id: str
    upload_id: str
    medium: str
    station: str
    activity_date: Optional[date]
    day: str
    programme: str
    spots: int
    cost: Optional[float]
    time_band: str
    region: str
    source_file: str


@dataclass
class SoeRow:
    """One brand's spend/spots aggregated over whatever filters the caller
    applied -- the raw material for Share of Expenditure (a brand's spend
    as a % of the filtered set's total spend), computed by the router since
    that's also where brand names get attached (see routers/runs.py's
    _brand_names for why that join lives at the router layer, not here)."""

    brand_id: str
    spend: float
    spots: int


@dataclass
class SoeFilterOptions:
    """Distinct values actually present in this project's media_activity,
    for populating the SOE Explorer's filter dropdowns -- deliberately not
    a fixed list (e.g. a hardcoded medium enum), since what's filterable
    is exactly what a given project's uploads happen to contain."""

    mediums: List[str]
    stations: List[str]
    regions: List[str]
    days: List[str]


class UploadsRepository(Protocol):
    def list_uploads(self, project_id: str) -> List[UploadRecord]: ...

    def list_media_activity(self, project_id: str) -> List[MediaActivityRecord]: ...

    def query_soe(
        self,
        project_id: str,
        *,
        upload_id: Optional[str] = None,
        mediums: Optional[List[str]] = None,
        stations: Optional[List[str]] = None,
        regions: Optional[List[str]] = None,
        days: Optional[List[str]] = None,
        date_from: Optional[date] = None,
        date_to: Optional[date] = None,
    ) -> List[SoeRow]:
        """Per-brand spend/spots summed over media_activity rows matching
        every given filter (an empty/omitted filter matches everything on
        that dimension). upload_id scopes to a single upload's rows -- the
        SOE Explorer analyzes one uploaded file at a time rather than
        pooling every upload a project has ever had, so a competitor's
        older file doesn't silently blend into this week's numbers. No
        project-level 'has this been calculated yet' gate -- spend is a
        fact about the upload itself (see media_activity.cost's column
        comment), so this works before anyone ever clicks Calculate,
        unlike brand_shares.soe."""
        ...

    def list_soe_filter_options(self, project_id: str, *, upload_id: Optional[str] = None) -> SoeFilterOptions: ...

    def create_upload_with_activity(
        self,
        project_id: str,
        brand_id: Optional[str],
        file_name: str,
        kind: str,
        inserts: List[MediaActivityInsert],
        issue_rows: int = 0,
    ) -> Tuple[UploadRecord, List[MediaActivityRecord]]: ...

    def delete_upload(self, project_id: str, upload_id: str) -> bool: ...

    def delete_media_activity_for_brand(self, project_id: str, brand_id: str) -> None: ...


def _upload_row_to_record(row: dict) -> UploadRecord:
    return UploadRecord(
        id=str(row['id']),
        project_id=str(row['project_id']),
        brand_id=str(row['brand_id']) if row['brand_id'] else None,
        file_name=row['file_name'],
        kind=row['kind'],
        mapped_rows=row['mapped_rows'],
        issue_rows=row['issue_rows'],
        uploaded_at=row['uploaded_at'],
    )


def _activity_row_to_record(row: dict) -> MediaActivityRecord:
    return MediaActivityRecord(
        id=str(row['id']),
        project_id=str(row['project_id']),
        brand_id=str(row['brand_id']),
        upload_id=str(row['upload_id']),
        medium=row['medium'] or '',
        station=row['station'] or '',
        activity_date=row['activity_date'],
        day=row['day'] or '',
        programme=row['programme'] or '',
        spots=row['spots'],
        cost=float(row['cost']) if row['cost'] is not None else None,
        time_band=row['time_band'] or '',
        region=row['region'] or '',
        source_file=row['source_file'] or '',
    )


class PostgresUploadsRepository:
    """Reads/writes `uploads` and `media_activity` (db/schema.sql)."""

    def list_uploads(self, project_id):
        with get_connection() as conn:
            rows = conn.execute(
                'SELECT * FROM uploads WHERE project_id = %s ORDER BY uploaded_at DESC', [project_id]
            ).fetchall()
        return [_upload_row_to_record(row) for row in rows]

    def list_media_activity(self, project_id):
        with get_connection() as conn:
            rows = conn.execute(
                'SELECT * FROM media_activity WHERE project_id = %s ORDER BY id', [project_id]
            ).fetchall()
        return [_activity_row_to_record(row) for row in rows]

    def create_upload_with_activity(self, project_id, brand_id, file_name, kind, inserts, issue_rows=0):
        with get_connection() as conn:
            upload_row = conn.execute(
                '''
                INSERT INTO uploads (project_id, brand_id, file_name, kind, mapped_rows, issue_rows)
                VALUES (%s, %s, %s, %s, %s, %s)
                RETURNING *
                ''',
                [project_id, brand_id, file_name, kind, len(inserts), issue_rows],
            ).fetchone()
            activity_records = []
            if inserts:
                with conn.cursor() as cur:
                    cur.executemany(
                        '''
                        INSERT INTO media_activity (
                            project_id, brand_id, upload_id, medium, station, activity_date, day,
                            programme, spots, cost, time_band, region, source_file, source_row_number
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ''',
                        [
                            (
                                project_id, insert.brand_id, upload_row['id'], insert.row.medium, insert.row.station,
                                insert.row.activity_date, insert.row.day, insert.row.programme, insert.row.spots,
                                insert.row.cost, insert.row.time_band, insert.row.region, insert.row.source_file,
                                insert.row.source_row_number,
                            )
                            for insert in inserts
                        ],
                    )
                activity_rows = conn.execute(
                    'SELECT * FROM media_activity WHERE upload_id = %s ORDER BY id', [upload_row['id']]
                ).fetchall()
                activity_records = [_activity_row_to_record(row) for row in activity_rows]
        return _upload_row_to_record(upload_row), activity_records

    def delete_upload(self, project_id, upload_id):
        # media_activity.upload_id is ON DELETE CASCADE (db/schema.sql), and
        # rating_matches/grp_calculations cascade transitively from there —
        # the caller (app/routers/uploads.py) is expected to have already
        # confirmed via calculations_repo.has_calculations_for_media_activity
        # that no run depends on this data, so that transitive cascade is a
        # no-op in the normal path, not a silent history-eraser.
        with get_connection() as conn:
            row = conn.execute(
                'DELETE FROM uploads WHERE project_id = %s AND id = %s RETURNING id', [project_id, upload_id]
            ).fetchone()
        return row is not None

    def delete_media_activity_for_brand(self, project_id, brand_id):
        # Only removes the rows, not the upload record itself — a
        # composite_report upload can span several brands, so deleting one
        # brand shouldn't take that upload's other brands' data with it.
        # uploads.mapped_rows for that upload becomes stale after this (it
        # reflects what was originally ingested, not a live count) — a
        # minor, accepted wrinkle, not recomputed anywhere else either.
        with get_connection() as conn:
            conn.execute(
                'DELETE FROM media_activity WHERE project_id = %s AND brand_id = %s', [project_id, brand_id]
            )

    def query_soe(self, project_id, *, upload_id=None, mediums=None, stations=None, regions=None, days=None, date_from=None, date_to=None):
        clauses = ['project_id = %s']
        params: list = [project_id]
        if upload_id:
            clauses.append('upload_id = %s')
            params.append(upload_id)
        if mediums:
            clauses.append('medium = ANY(%s)')
            params.append(list(mediums))
        if stations:
            clauses.append('station = ANY(%s)')
            params.append(list(stations))
        if regions:
            clauses.append('region = ANY(%s)')
            params.append(list(regions))
        if days:
            clauses.append('day = ANY(%s)')
            params.append(list(days))
        if date_from:
            clauses.append('activity_date >= %s')
            params.append(date_from)
        if date_to:
            clauses.append('activity_date <= %s')
            params.append(date_to)
        where = ' AND '.join(clauses)
        with get_connection() as conn:
            rows = conn.execute(
                f'''
                SELECT brand_id, COALESCE(SUM(cost), 0) AS spend, COALESCE(SUM(spots), 0) AS spots
                FROM media_activity
                WHERE {where}
                GROUP BY brand_id
                ''',
                params,
            ).fetchall()
        return [SoeRow(brand_id=str(row['brand_id']), spend=float(row['spend']), spots=int(row['spots'])) for row in rows]

    def list_soe_filter_options(self, project_id, *, upload_id=None):
        def _distinct(column: str) -> List[str]:
            clause = f"project_id = %s AND {column} IS NOT NULL AND {column} <> ''"
            params: list = [project_id]
            if upload_id:
                clause += ' AND upload_id = %s'
                params.append(upload_id)
            with get_connection() as conn:
                rows = conn.execute(
                    f'SELECT DISTINCT {column} AS v FROM media_activity WHERE {clause}',
                    params,
                ).fetchall()
            return sorted(row['v'] for row in rows)

        return SoeFilterOptions(
            mediums=_distinct('medium'),
            stations=_distinct('station'),
            regions=_distinct('region'),
            days=_distinct('day'),
        )


class InMemoryUploadsRepository:
    """Stand-in for tests and DB-free local runs (API_REPOSITORY=memory)."""

    def __init__(self):
        self._uploads: Dict[str, UploadRecord] = {}
        self._activity: Dict[str, MediaActivityRecord] = {}

    def list_uploads(self, project_id):
        records = [u for u in self._uploads.values() if u.project_id == project_id]
        return sorted(records, key=lambda u: u.uploaded_at, reverse=True)

    def list_media_activity(self, project_id):
        return [a for a in self._activity.values() if a.project_id == project_id]

    def create_upload_with_activity(self, project_id, brand_id, file_name, kind, inserts, issue_rows=0):
        upload = UploadRecord(
            id=str(uuid.uuid4()), project_id=project_id, brand_id=brand_id, file_name=file_name, kind=kind,
            mapped_rows=len(inserts), issue_rows=issue_rows, uploaded_at=datetime.now(timezone.utc),
        )
        self._uploads[upload.id] = upload
        activity_records = []
        for insert in inserts:
            record = MediaActivityRecord(
                id=str(uuid.uuid4()), project_id=project_id, brand_id=insert.brand_id, upload_id=upload.id,
                medium=insert.row.medium, station=insert.row.station, activity_date=insert.row.activity_date,
                day=insert.row.day, programme=insert.row.programme, spots=insert.row.spots,
                cost=insert.row.cost, time_band=insert.row.time_band, region=insert.row.region,
                source_file=insert.row.source_file,
            )
            self._activity[record.id] = record
            activity_records.append(record)
        return upload, activity_records

    def delete_upload(self, project_id, upload_id):
        upload = self._uploads.get(upload_id)
        if upload is None or upload.project_id != project_id:
            return False
        stale_ids = [aid for aid, a in self._activity.items() if a.upload_id == upload_id]
        for aid in stale_ids:
            del self._activity[aid]
        del self._uploads[upload_id]
        return True

    def delete_media_activity_for_brand(self, project_id, brand_id):
        stale_ids = [
            aid for aid, a in self._activity.items() if a.project_id == project_id and a.brand_id == brand_id
        ]
        for aid in stale_ids:
            del self._activity[aid]

    def query_soe(self, project_id, *, upload_id=None, mediums=None, stations=None, regions=None, days=None, date_from=None, date_to=None):
        totals: Dict[str, Dict[str, float]] = {}
        for activity in self._activity.values():
            if activity.project_id != project_id:
                continue
            if upload_id and activity.upload_id != upload_id:
                continue
            if mediums and activity.medium not in mediums:
                continue
            if stations and activity.station not in stations:
                continue
            if regions and activity.region not in regions:
                continue
            if days and activity.day not in days:
                continue
            if date_from and (activity.activity_date is None or activity.activity_date < date_from):
                continue
            if date_to and (activity.activity_date is None or activity.activity_date > date_to):
                continue
            bucket = totals.setdefault(activity.brand_id, {'spend': 0.0, 'spots': 0})
            bucket['spend'] += activity.cost or 0.0
            bucket['spots'] += activity.spots
        return [
            SoeRow(brand_id=brand_id, spend=bucket['spend'], spots=int(bucket['spots']))
            for brand_id, bucket in totals.items()
        ]

    def list_soe_filter_options(self, project_id, *, upload_id=None):
        rows = [
            a for a in self._activity.values()
            if a.project_id == project_id and (upload_id is None or a.upload_id == upload_id)
        ]
        return SoeFilterOptions(
            mediums=sorted({a.medium for a in rows if a.medium}),
            stations=sorted({a.station for a in rows if a.station}),
            regions=sorted({a.region for a in rows if a.region}),
            days=sorted({a.day for a in rows if a.day}),
        )


_memory_repository = InMemoryUploadsRepository()
_postgres_repository = PostgresUploadsRepository()


def get_uploads_repository() -> UploadsRepository:
    if get_settings().repository_backend == 'memory':
        return _memory_repository
    return _postgres_repository
