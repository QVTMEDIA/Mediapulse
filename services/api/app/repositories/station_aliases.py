from __future__ import annotations

import logging
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, List, Protocol

from ..config import get_settings
from ..db import get_connection

logger = logging.getLogger(__name__)


@dataclass
class StationAliasRecord:
    id: str
    alias_name: str
    canonical_name: str
    created_by: str
    created_by_name: str
    created_at: datetime


class StationAliasesRepository(Protocol):
    def list_aliases(self) -> List[StationAliasRecord]: ...

    def create_alias(self, *, alias_name: str, canonical_name: str, created_by: str, created_by_name: str) -> StationAliasRecord: ...

    def delete_alias(self, alias_id: str) -> None: ...

    def get_alias_map(self) -> Dict[str, str]:
        """{normalized_alias_name: canonical_name}, for the Matching Engine
        (see app/matches.py's _apply_station_aliases) -- not keyed by id,
        since matching only ever needs to resolve a raw station string to
        its canonical form, never the alias row itself."""
        ...


def _normalize_alias_key(value: str) -> str:
    # Mirrors db/schema.sql's normalize_match_text() and
    # grp_calculator.normalize_text() -- the same light (case/whitespace
    # only) normalization match_key's own MEDIUM/DAY components use, not
    # the Matching Engine's much more aggressive station normalization.
    # An alias is a specific, deliberate pairing a human confirmed, not
    # another fuzzy rule.
    return re.sub(r'\s+', ' ', str(value or '').strip()).upper()


def _row_to_record(row: dict) -> StationAliasRecord:
    return StationAliasRecord(
        id=str(row['id']),
        alias_name=row['alias_name'],
        canonical_name=row['canonical_name'],
        created_by=str(row['created_by']) if row['created_by'] else '',
        created_by_name=row['created_by_name'],
        created_at=row['created_at'],
    )


class PostgresStationAliasesRepository:
    """Reads/writes `station_aliases` (db/schema.sql)."""

    def list_aliases(self):
        with get_connection() as conn:
            rows = conn.execute('SELECT * FROM station_aliases ORDER BY alias_name').fetchall()
        return [_row_to_record(row) for row in rows]

    def create_alias(self, *, alias_name, canonical_name, created_by, created_by_name):
        with get_connection() as conn:
            row = conn.execute(
                '''
                INSERT INTO station_aliases (alias_name, canonical_name, created_by, created_by_name)
                VALUES (%s, %s, %s, %s)
                ON CONFLICT (normalize_match_text(alias_name)) DO UPDATE
                    SET canonical_name = EXCLUDED.canonical_name,
                        created_by = EXCLUDED.created_by,
                        created_by_name = EXCLUDED.created_by_name
                RETURNING *
                ''',
                [alias_name, canonical_name, created_by, created_by_name],
            ).fetchone()
        return _row_to_record(row)

    def delete_alias(self, alias_id):
        with get_connection() as conn:
            conn.execute('DELETE FROM station_aliases WHERE id = %s', [alias_id])

    def get_alias_map(self):
        # Best-effort on purpose, like PostgresActivityLogRepository.record()
        # -- this table can reach production code before its migration
        # does (see services/api/README.md's avatar_data_url/activity_log
        # incidents), and a missing-table failure here must never break
        # Calculate/matching for every project; it should just mean no
        # aliases apply yet.
        try:
            with get_connection() as conn:
                rows = conn.execute('SELECT alias_name, canonical_name FROM station_aliases').fetchall()
            return {_normalize_alias_key(row['alias_name']): row['canonical_name'] for row in rows}
        except Exception:
            logger.exception('Could not load station aliases -- continuing without them.')
            return {}


class InMemoryStationAliasesRepository:
    """Stand-in for tests and DB-free local runs (API_REPOSITORY=memory)."""

    def __init__(self):
        self._rows: Dict[str, StationAliasRecord] = {}  # keyed by normalized alias_name

    def list_aliases(self):
        return sorted(self._rows.values(), key=lambda r: r.alias_name)

    def create_alias(self, *, alias_name, canonical_name, created_by, created_by_name):
        key = _normalize_alias_key(alias_name)
        existing = self._rows.get(key)
        record = StationAliasRecord(
            id=existing.id if existing else str(uuid.uuid4()),
            alias_name=alias_name,
            canonical_name=canonical_name,
            created_by=created_by,
            created_by_name=created_by_name,
            created_at=existing.created_at if existing else datetime.now(timezone.utc),
        )
        self._rows[key] = record
        return record

    def delete_alias(self, alias_id):
        stale_keys = [key for key, record in self._rows.items() if record.id == alias_id]
        for key in stale_keys:
            del self._rows[key]

    def get_alias_map(self):
        return {key: record.canonical_name for key, record in self._rows.items()}


_memory_repository = InMemoryStationAliasesRepository()
_postgres_repository = PostgresStationAliasesRepository()


def get_station_aliases_repository() -> StationAliasesRepository:
    if get_settings().repository_backend == 'memory':
        return _memory_repository
    return _postgres_repository
