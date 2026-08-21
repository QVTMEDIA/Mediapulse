from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, List, Optional, Protocol

import psycopg

from ..config import get_settings
from ..db import get_connection
from ..schemas.brands import BrandCreate


@dataclass
class BrandRecord:
    id: str
    project_id: str
    name: str
    created_at: datetime


class BrandAlreadyExists(Exception):
    """Raised when a brand name already exists for the project (unique per db/schema.sql)."""


class BrandsRepository(Protocol):
    def list_brands(self, project_id: str) -> List[BrandRecord]: ...

    def create_brand(self, project_id: str, data: BrandCreate) -> BrandRecord: ...

    def get_brand(self, project_id: str, brand_id: str) -> Optional[BrandRecord]: ...

    def get_or_create_brand(self, project_id: str, name: str) -> BrandRecord: ...

    def delete_brand(self, project_id: str, brand_id: str) -> bool: ...


def _row_to_record(row: dict) -> BrandRecord:
    return BrandRecord(
        id=str(row['id']),
        project_id=str(row['project_id']),
        name=row['name'],
        created_at=row['created_at'],
    )


class PostgresBrandsRepository:
    """Reads/writes the `brands` table defined in db/schema.sql."""

    def list_brands(self, project_id):
        with get_connection() as conn:
            rows = conn.execute(
                'SELECT * FROM brands WHERE project_id = %s ORDER BY name', [project_id]
            ).fetchall()
        return [_row_to_record(row) for row in rows]

    def get_brand(self, project_id, brand_id):
        with get_connection() as conn:
            row = conn.execute(
                'SELECT * FROM brands WHERE project_id = %s AND id = %s', [project_id, brand_id]
            ).fetchone()
        return _row_to_record(row) if row else None

    def create_brand(self, project_id, data: BrandCreate):
        try:
            with get_connection() as conn:
                row = conn.execute(
                    'INSERT INTO brands (project_id, name) VALUES (%s, %s) RETURNING *',
                    [project_id, data.name],
                ).fetchone()
        except psycopg.errors.UniqueViolation as exc:
            raise BrandAlreadyExists(data.name) from exc
        return _row_to_record(row)

    def get_or_create_brand(self, project_id, name):
        # Atomic upsert on the (project_id, name) unique constraint — used by
        # composite-report ingestion, which discovers brand names from file
        # content rather than the caller picking one up front, so a
        # check-then-insert race is a real possibility across concurrent rows.
        with get_connection() as conn:
            row = conn.execute(
                '''
                INSERT INTO brands (project_id, name) VALUES (%s, %s)
                ON CONFLICT (project_id, name) DO UPDATE SET name = EXCLUDED.name
                RETURNING *
                ''',
                [project_id, name],
            ).fetchone()
        return _row_to_record(row)

    def delete_brand(self, project_id, brand_id):
        # media_activity.brand_id is ON DELETE CASCADE (db/schema.sql), so
        # this alone would take that brand's activity/matches/calculations
        # with it — the caller (app/routers/brands.py) is expected to have
        # already confirmed via calculations_repo.has_calculations_for_
        # media_activity that no run depends on it, same guard as deleting
        # an upload.
        with get_connection() as conn:
            row = conn.execute(
                'DELETE FROM brands WHERE project_id = %s AND id = %s RETURNING id', [project_id, brand_id]
            ).fetchone()
        return row is not None


class InMemoryBrandsRepository:
    """Stand-in for tests and DB-free local runs (API_REPOSITORY=memory)."""

    def __init__(self):
        self._rows: Dict[str, BrandRecord] = {}

    def list_brands(self, project_id):
        records = [record for record in self._rows.values() if record.project_id == project_id]
        return sorted(records, key=lambda r: r.name)

    def get_brand(self, project_id, brand_id):
        record = self._rows.get(brand_id)
        return record if record and record.project_id == project_id else None

    def create_brand(self, project_id, data: BrandCreate):
        if any(r.project_id == project_id and r.name == data.name for r in self._rows.values()):
            raise BrandAlreadyExists(data.name)
        record = BrandRecord(
            id=str(uuid.uuid4()), project_id=project_id, name=data.name, created_at=datetime.now(timezone.utc)
        )
        self._rows[record.id] = record
        return record

    def get_or_create_brand(self, project_id, name):
        for record in self._rows.values():
            if record.project_id == project_id and record.name == name:
                return record
        record = BrandRecord(
            id=str(uuid.uuid4()), project_id=project_id, name=name, created_at=datetime.now(timezone.utc)
        )
        self._rows[record.id] = record
        return record

    def delete_brand(self, project_id, brand_id):
        record = self._rows.get(brand_id)
        if record is None or record.project_id != project_id:
            return False
        del self._rows[brand_id]
        return True


_memory_repository = InMemoryBrandsRepository()
_postgres_repository = PostgresBrandsRepository()


def get_brands_repository() -> BrandsRepository:
    if get_settings().repository_backend == 'memory':
        return _memory_repository
    return _postgres_repository
