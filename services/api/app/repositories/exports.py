from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, List, Optional, Protocol

from ..config import get_settings
from ..db import get_connection

VALID_FORMATS = ('xlsx_full',)  # xlsx_summary/pdf/csv are Planned — see PRODUCT_ROADMAP.md


@dataclass
class ExportRecord:
    id: str
    project_id: str
    run_id: Optional[str]
    format: str
    generated_by: Optional[str]
    generated_at: datetime


class ExportsRepository(Protocol):
    def create_export(self, project_id: str, run_id: Optional[str], format_: str, generated_by: Optional[str]) -> ExportRecord: ...

    def list_exports(self, project_id: str) -> List[ExportRecord]: ...

    def get_export(self, project_id: str, export_id: str) -> Optional[ExportRecord]: ...


def _row_to_record(row: dict) -> ExportRecord:
    return ExportRecord(
        id=str(row['id']),
        project_id=str(row['project_id']),
        run_id=str(row['run_id']) if row['run_id'] else None,
        format=row['format'],
        generated_by=str(row['generated_by']) if row['generated_by'] else None,
        generated_at=row['generated_at'],
    )


class PostgresExportsRepository:
    """Reads/writes the `exports` table (db/schema.sql). `storage_path`
    stays null — no object storage is configured in this environment, so
    GET .../exports/{exportId}/download regenerates the workbook on demand
    from the (immutable, run-scoped) calculation data instead of reading a
    stored file. See the comment on that route in app/routers/exports.py."""

    def create_export(self, project_id, run_id, format_, generated_by):
        with get_connection() as conn:
            row = conn.execute(
                '''
                INSERT INTO exports (project_id, run_id, format, generated_by)
                VALUES (%s, %s, %s, %s)
                RETURNING *
                ''',
                [project_id, run_id, format_, generated_by],
            ).fetchone()
        return _row_to_record(row)

    def list_exports(self, project_id):
        with get_connection() as conn:
            rows = conn.execute(
                'SELECT * FROM exports WHERE project_id = %s ORDER BY generated_at DESC', [project_id]
            ).fetchall()
        return [_row_to_record(row) for row in rows]

    def get_export(self, project_id, export_id):
        with get_connection() as conn:
            row = conn.execute(
                'SELECT * FROM exports WHERE project_id = %s AND id = %s', [project_id, export_id]
            ).fetchone()
        return _row_to_record(row) if row else None


class InMemoryExportsRepository:
    """Stand-in for tests and DB-free local runs (API_REPOSITORY=memory)."""

    def __init__(self):
        self._rows: Dict[str, ExportRecord] = {}

    def create_export(self, project_id, run_id, format_, generated_by):
        record = ExportRecord(
            id=str(uuid.uuid4()), project_id=project_id, run_id=run_id, format=format_,
            generated_by=generated_by, generated_at=datetime.now(timezone.utc),
        )
        self._rows[record.id] = record
        return record

    def list_exports(self, project_id):
        records = [r for r in self._rows.values() if r.project_id == project_id]
        return sorted(records, key=lambda r: r.generated_at, reverse=True)

    def get_export(self, project_id, export_id):
        record = self._rows.get(export_id)
        return record if record and record.project_id == project_id else None


_memory_repository = InMemoryExportsRepository()
_postgres_repository = PostgresExportsRepository()


def get_exports_repository() -> ExportsRepository:
    """FastAPI dependency. Defaults to Postgres; set API_REPOSITORY=memory to
    run/explore the API without a database (tests override this directly)."""
    if get_settings().repository_backend == 'memory':
        return _memory_repository
    return _postgres_repository
