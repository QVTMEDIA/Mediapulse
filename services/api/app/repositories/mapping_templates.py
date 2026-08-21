from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, List, Optional, Protocol

from ..config import get_settings
from ..db import get_connection


@dataclass
class MappingTemplateRecord:
    id: str
    source_label: str
    field_mapping: Dict[str, str]
    created_at: datetime
    last_used_at: Optional[datetime]


class MappingTemplatesRepository(Protocol):
    def list_templates(self) -> List[MappingTemplateRecord]: ...

    def get_by_source_label(self, source_label: str) -> Optional[MappingTemplateRecord]: ...

    def save_template(self, source_label: str, field_mapping: Dict[str, str]) -> MappingTemplateRecord: ...

    def touch_used(self, source_label: str) -> None: ...


def _row_to_record(row: dict) -> MappingTemplateRecord:
    return MappingTemplateRecord(
        id=str(row['id']),
        source_label=row['source_label'],
        field_mapping=dict(row['field_mapping'] or {}),
        created_at=row['created_at'],
        last_used_at=row['last_used_at'],
    )


class PostgresMappingTemplatesRepository:
    """Reads/writes `mapping_templates` (db/schema.sql)."""

    def list_templates(self):
        with get_connection() as conn:
            rows = conn.execute('SELECT * FROM mapping_templates ORDER BY source_label').fetchall()
        return [_row_to_record(row) for row in rows]

    def get_by_source_label(self, source_label):
        with get_connection() as conn:
            row = conn.execute(
                'SELECT * FROM mapping_templates WHERE source_label = %s', [source_label]
            ).fetchone()
        return _row_to_record(row) if row else None

    def save_template(self, source_label, field_mapping):
        from psycopg.types.json import Jsonb

        with get_connection() as conn:
            row = conn.execute(
                '''
                INSERT INTO mapping_templates (source_label, field_mapping)
                VALUES (%s, %s)
                ON CONFLICT (source_label) DO UPDATE SET field_mapping = EXCLUDED.field_mapping
                RETURNING *
                ''',
                [source_label, Jsonb(field_mapping)],
            ).fetchone()
        return _row_to_record(row)

    def touch_used(self, source_label):
        with get_connection() as conn:
            conn.execute(
                'UPDATE mapping_templates SET last_used_at = now() WHERE source_label = %s', [source_label]
            )


class InMemoryMappingTemplatesRepository:
    """Stand-in for tests and DB-free local runs (API_REPOSITORY=memory)."""

    def __init__(self):
        self._rows: Dict[str, MappingTemplateRecord] = {}  # keyed by source_label

    def list_templates(self):
        return sorted(self._rows.values(), key=lambda r: r.source_label)

    def get_by_source_label(self, source_label):
        return self._rows.get(source_label)

    def save_template(self, source_label, field_mapping):
        existing = self._rows.get(source_label)
        record = MappingTemplateRecord(
            id=existing.id if existing else str(uuid.uuid4()),
            source_label=source_label,
            field_mapping=dict(field_mapping),
            created_at=existing.created_at if existing else datetime.now(timezone.utc),
            last_used_at=existing.last_used_at if existing else None,
        )
        self._rows[source_label] = record
        return record

    def touch_used(self, source_label):
        record = self._rows.get(source_label)
        if record:
            record.last_used_at = datetime.now(timezone.utc)


_memory_repository = InMemoryMappingTemplatesRepository()
_postgres_repository = PostgresMappingTemplatesRepository()


def get_mapping_templates_repository() -> MappingTemplatesRepository:
    if get_settings().repository_backend == 'memory':
        return _memory_repository
    return _postgres_repository
