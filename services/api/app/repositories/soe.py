from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Dict, List, Optional, Protocol, Tuple

from ..config import get_settings
from ..db import get_connection
from ..parsing import ParsedCompositeRow


@dataclass
class SoeUploadRecord:
    id: str
    file_name: str
    mapped_rows: int
    issue_rows: int
    uploaded_at: datetime


@dataclass
class SoeActivityRecord:
    id: str
    upload_id: str
    brand: str
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
class SoeBrandRow:
    """One brand's spend/spots aggregated over whatever filters the caller
    applied -- see routers/soe.py's get_soe for the % SOE computation this
    feeds. `brand` is the vendor's own text, never a foreign key: this data
    has no project, so there is no Brand entity to look up."""

    brand: str
    spend: float
    spots: int


@dataclass
class SoeFilterOptions:
    """Distinct values actually present in soe_activity, for populating the
    SOE Explorer's filter dropdowns -- deliberately not a fixed list, since
    what's filterable is exactly what a given upload happens to contain."""

    mediums: List[str]
    stations: List[str]
    regions: List[str]
    days: List[str]


class SoeRepository(Protocol):
    def list_uploads(self) -> List[SoeUploadRecord]: ...

    def create_upload_with_activity(
        self, file_name: str, rows: List[ParsedCompositeRow], issue_rows: int = 0
    ) -> Tuple[SoeUploadRecord, List[SoeActivityRecord]]: ...

    def delete_upload(self, upload_id: str) -> bool: ...

    def query_soe(
        self,
        *,
        upload_id: Optional[str] = None,
        mediums: Optional[List[str]] = None,
        stations: Optional[List[str]] = None,
        regions: Optional[List[str]] = None,
        days: Optional[List[str]] = None,
        date_from: Optional[date] = None,
        date_to: Optional[date] = None,
    ) -> List[SoeBrandRow]:
        """Per-brand spend/spots summed over soe_activity rows matching
        every given filter (an empty/omitted filter matches everything on
        that dimension). upload_id scopes to a single upload's rows -- the
        SOE Explorer analyzes one uploaded file at a time rather than
        pooling every upload ever made, so an older file doesn't silently
        blend into this week's numbers."""
        ...

    def list_filter_options(self, *, upload_id: Optional[str] = None) -> SoeFilterOptions: ...


def _upload_row_to_record(row: dict) -> SoeUploadRecord:
    return SoeUploadRecord(
        id=str(row['id']),
        file_name=row['file_name'],
        mapped_rows=row['mapped_rows'],
        issue_rows=row['issue_rows'],
        uploaded_at=row['uploaded_at'],
    )


def _activity_row_to_record(row: dict) -> SoeActivityRecord:
    return SoeActivityRecord(
        id=str(row['id']),
        upload_id=str(row['upload_id']),
        brand=row['brand'] or '',
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


class PostgresSoeRepository:
    """Reads/writes `soe_uploads` and `soe_activity` (db/schema.sql)."""

    def list_uploads(self):
        with get_connection() as conn:
            rows = conn.execute('SELECT * FROM soe_uploads ORDER BY uploaded_at DESC').fetchall()
        return [_upload_row_to_record(row) for row in rows]

    def create_upload_with_activity(self, file_name, rows, issue_rows=0):
        with get_connection() as conn:
            upload_row = conn.execute(
                '''
                INSERT INTO soe_uploads (file_name, mapped_rows, issue_rows)
                VALUES (%s, %s, %s)
                RETURNING *
                ''',
                [file_name, len(rows), issue_rows],
            ).fetchone()
            activity_records = []
            if rows:
                with conn.cursor() as cur:
                    cur.executemany(
                        '''
                        INSERT INTO soe_activity (
                            upload_id, brand, medium, station, activity_date, day, programme, spots,
                            cost, time_band, region, source_file
                        ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ''',
                        [
                            (
                                upload_row['id'], row.brand_name, row.medium, row.station, row.activity_date,
                                row.day, row.programme, row.spots, row.cost, row.time_band, row.region,
                                row.source_file,
                            )
                            for row in rows
                        ],
                    )
                activity_rows = conn.execute(
                    'SELECT * FROM soe_activity WHERE upload_id = %s ORDER BY id', [upload_row['id']]
                ).fetchall()
                activity_records = [_activity_row_to_record(row) for row in activity_rows]
        return _upload_row_to_record(upload_row), activity_records

    def delete_upload(self, upload_id):
        # soe_activity.upload_id is ON DELETE CASCADE -- no rating_matches/
        # grp_calculations ever point at this data (it never reaches the
        # Matching Engine), so unlike routers/uploads.py's delete_upload,
        # there's no calculated-run audit trail to protect here.
        with get_connection() as conn:
            row = conn.execute('DELETE FROM soe_uploads WHERE id = %s RETURNING id', [upload_id]).fetchone()
        return row is not None

    def query_soe(self, *, upload_id=None, mediums=None, stations=None, regions=None, days=None, date_from=None, date_to=None):
        clauses = ['true']
        params: list = []
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
                SELECT brand, COALESCE(SUM(cost), 0) AS spend, COALESCE(SUM(spots), 0) AS spots
                FROM soe_activity
                WHERE {where}
                GROUP BY brand
                ''',
                params,
            ).fetchall()
        return [SoeBrandRow(brand=row['brand'], spend=float(row['spend']), spots=int(row['spots'])) for row in rows]

    def list_filter_options(self, *, upload_id=None):
        def _distinct(column: str) -> List[str]:
            clause = f"{column} IS NOT NULL AND {column} <> ''"
            params: list = []
            if upload_id:
                clause += ' AND upload_id = %s'
                params.append(upload_id)
            with get_connection() as conn:
                rows = conn.execute(f'SELECT DISTINCT {column} AS v FROM soe_activity WHERE {clause}', params).fetchall()
            return sorted(row['v'] for row in rows)

        return SoeFilterOptions(
            mediums=_distinct('medium'),
            stations=_distinct('station'),
            regions=_distinct('region'),
            days=_distinct('day'),
        )


class InMemorySoeRepository:
    """Stand-in for tests and DB-free local runs (API_REPOSITORY=memory)."""

    def __init__(self):
        self._uploads: Dict[str, SoeUploadRecord] = {}
        self._activity: Dict[str, SoeActivityRecord] = {}

    def list_uploads(self):
        return sorted(self._uploads.values(), key=lambda u: u.uploaded_at, reverse=True)

    def create_upload_with_activity(self, file_name, rows, issue_rows=0):
        upload = SoeUploadRecord(
            id=str(uuid.uuid4()), file_name=file_name, mapped_rows=len(rows), issue_rows=issue_rows,
            uploaded_at=datetime.now(timezone.utc),
        )
        self._uploads[upload.id] = upload
        activity_records = []
        for row in rows:
            record = SoeActivityRecord(
                id=str(uuid.uuid4()), upload_id=upload.id, brand=row.brand_name, medium=row.medium,
                station=row.station, activity_date=row.activity_date, day=row.day, programme=row.programme,
                spots=row.spots, cost=row.cost, time_band=row.time_band, region=row.region,
                source_file=row.source_file,
            )
            self._activity[record.id] = record
            activity_records.append(record)
        return upload, activity_records

    def delete_upload(self, upload_id):
        if upload_id not in self._uploads:
            return False
        stale_ids = [aid for aid, a in self._activity.items() if a.upload_id == upload_id]
        for aid in stale_ids:
            del self._activity[aid]
        del self._uploads[upload_id]
        return True

    def query_soe(self, *, upload_id=None, mediums=None, stations=None, regions=None, days=None, date_from=None, date_to=None):
        totals: Dict[str, Dict[str, float]] = {}
        for activity in self._activity.values():
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
            bucket = totals.setdefault(activity.brand, {'spend': 0.0, 'spots': 0})
            bucket['spend'] += activity.cost or 0.0
            bucket['spots'] += activity.spots
        return [
            SoeBrandRow(brand=brand, spend=bucket['spend'], spots=int(bucket['spots']))
            for brand, bucket in totals.items()
        ]

    def list_filter_options(self, *, upload_id=None):
        rows = [a for a in self._activity.values() if upload_id is None or a.upload_id == upload_id]
        return SoeFilterOptions(
            mediums=sorted({a.medium for a in rows if a.medium}),
            stations=sorted({a.station for a in rows if a.station}),
            regions=sorted({a.region for a in rows if a.region}),
            days=sorted({a.day for a in rows if a.day}),
        )


_memory_repository = InMemorySoeRepository()
_postgres_repository = PostgresSoeRepository()


def get_soe_repository() -> SoeRepository:
    if get_settings().repository_backend == 'memory':
        return _memory_repository
    return _postgres_repository
