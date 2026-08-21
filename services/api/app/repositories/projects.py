from __future__ import annotations

import uuid
from dataclasses import dataclass, replace
from datetime import date, datetime, timezone
from typing import Dict, List, Optional, Protocol

from ..config import get_settings
from ..db import get_connection
from ..schemas.projects import ProjectCreate, ProjectUpdate

# Maps camelCase-derived Pydantic field names to `projects` table columns
# (see db/schema.sql). Shared by the Postgres and in-memory repositories so
# create/update stay in lockstep with the schema.
_COLUMN_MAP = {
    'project_name': 'name',
    'project_owner': 'owner_name',
    'client': 'client',
    'category': 'category',
    'market': 'market',
    'start_date': 'start_date',
    'end_date': 'end_date',
    'target_audience': 'target_audience',
    'media_types': 'media_types',
    'ratings_provider': 'ratings_provider',
    'ratings_period': 'ratings_period',
    'status': 'status',
    'archived': 'archived',
    'notes': 'notes',
}


@dataclass
class ProjectRecord:
    id: str
    name: str
    owner_name: str
    client: str
    category: str
    market: str
    start_date: Optional[date]
    end_date: Optional[date]
    target_audience: str
    media_types: List[str]
    ratings_provider: str
    ratings_period: str
    status: str
    archived: bool
    notes: str
    created_at: datetime
    updated_at: datetime


class ProjectsRepository(Protocol):
    def list_projects(
        self, *, search: str = '', status: Optional[str] = None, include_archived: bool = True
    ) -> List[ProjectRecord]: ...

    def get_project(self, project_id: str) -> Optional[ProjectRecord]: ...

    def create_project(self, data: ProjectCreate) -> ProjectRecord: ...

    def update_project(self, project_id: str, data: ProjectUpdate) -> Optional[ProjectRecord]: ...

    def delete_project(self, project_id: str) -> bool: ...

    def duplicate_project(self, project_id: str) -> Optional[ProjectRecord]: ...


def _row_to_record(row: dict) -> ProjectRecord:
    return ProjectRecord(
        id=str(row['id']),
        name=row['name'] or '',
        owner_name=row['owner_name'] or '',
        client=row['client'] or '',
        category=row['category'] or '',
        market=row['market'] or '',
        start_date=row['start_date'],
        end_date=row['end_date'],
        target_audience=row['target_audience'] or '',
        media_types=list(row['media_types'] or []),
        ratings_provider=row['ratings_provider'] or '',
        ratings_period=row['ratings_period'] or '',
        status=row['status'],
        archived=row['archived'],
        notes=row['notes'] or '',
        created_at=row['created_at'],
        updated_at=row['updated_at'],
    )


class PostgresProjectsRepository:
    """Reads/writes the `projects` table defined in db/schema.sql."""

    def list_projects(self, *, search='', status=None, include_archived=True):
        clauses = []
        params: list = []
        if search:
            clauses.append('(name ILIKE %s OR client ILIKE %s OR category ILIKE %s)')
            like = f'%{search}%'
            params += [like, like, like]
        if status:
            clauses.append('status = %s')
            params.append(status)
        if not include_archived:
            clauses.append('archived = false')
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ''
        query = f'SELECT * FROM projects {where} ORDER BY updated_at DESC'
        with get_connection() as conn:
            rows = conn.execute(query, params).fetchall()
        return [_row_to_record(row) for row in rows]

    def get_project(self, project_id):
        with get_connection() as conn:
            row = conn.execute('SELECT * FROM projects WHERE id = %s', [project_id]).fetchone()
        return _row_to_record(row) if row else None

    def create_project(self, data: ProjectCreate):
        with get_connection() as conn:
            row = conn.execute(
                '''
                INSERT INTO projects (
                    name, owner_name, client, category, market, start_date, end_date,
                    target_audience, media_types, ratings_provider, ratings_period, status, notes
                ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                RETURNING *
                ''',
                [
                    data.project_name, data.project_owner, data.client, data.category, data.market,
                    data.start_date, data.end_date, data.target_audience, data.media_types,
                    data.ratings_provider, data.ratings_period, data.status, data.notes,
                ],
            ).fetchone()
        return _row_to_record(row)

    def update_project(self, project_id, data: ProjectUpdate):
        updates = data.model_dump(exclude_unset=True)
        set_clauses = []
        params: list = []
        for field_name, value in updates.items():
            column = _COLUMN_MAP.get(field_name)
            if column is None:
                continue
            set_clauses.append(f'{column} = %s')
            params.append(value)
        if not set_clauses:
            return self.get_project(project_id)
        params.append(project_id)
        query = f"UPDATE projects SET {', '.join(set_clauses)} WHERE id = %s RETURNING *"
        with get_connection() as conn:
            row = conn.execute(query, params).fetchone()
        return _row_to_record(row) if row else None

    def delete_project(self, project_id):
        with get_connection() as conn:
            row = conn.execute('DELETE FROM projects WHERE id = %s RETURNING id', [project_id]).fetchone()
        return row is not None

    def duplicate_project(self, project_id):
        # Mirrors app.py's duplicate_project(): new id, name + " Copy",
        # unarchived, fresh timestamps, everything else carried over.
        with get_connection() as conn:
            row = conn.execute(
                '''
                INSERT INTO projects (
                    name, owner_name, client, category, market, start_date, end_date,
                    target_audience, media_types, ratings_provider, ratings_period, status, notes
                )
                SELECT name || ' Copy', owner_name, client, category, market, start_date, end_date,
                       target_audience, media_types, ratings_provider, ratings_period, status, notes
                FROM projects WHERE id = %s
                RETURNING *
                ''',
                [project_id],
            ).fetchone()
        return _row_to_record(row) if row else None


class InMemoryProjectsRepository:
    """Stand-in for tests and for local exploration without Postgres running
    (set API_REPOSITORY=memory). Not persisted across process restarts."""

    def __init__(self):
        self._rows: Dict[str, ProjectRecord] = {}

    def list_projects(self, *, search='', status=None, include_archived=True):
        needle = search.lower()
        results = []
        for record in self._rows.values():
            if not include_archived and record.archived:
                continue
            if status and record.status != status:
                continue
            haystack = f'{record.name} {record.client} {record.category}'.lower()
            if needle and needle not in haystack:
                continue
            results.append(record)
        return sorted(results, key=lambda r: r.updated_at, reverse=True)

    def get_project(self, project_id):
        return self._rows.get(project_id)

    def create_project(self, data: ProjectCreate):
        now = datetime.now(timezone.utc)
        record = ProjectRecord(
            id=str(uuid.uuid4()),
            name=data.project_name,
            owner_name=data.project_owner,
            client=data.client,
            category=data.category,
            market=data.market,
            start_date=data.start_date,
            end_date=data.end_date,
            target_audience=data.target_audience,
            media_types=list(data.media_types),
            ratings_provider=data.ratings_provider,
            ratings_period=data.ratings_period,
            status=data.status,
            archived=False,
            notes=data.notes,
            created_at=now,
            updated_at=now,
        )
        self._rows[record.id] = record
        return record

    def update_project(self, project_id, data: ProjectUpdate):
        record = self._rows.get(project_id)
        if record is None:
            return None
        updates = data.model_dump(exclude_unset=True)
        for field_name, value in updates.items():
            attr = _COLUMN_MAP.get(field_name)
            if attr:
                setattr(record, attr, value)
        record.updated_at = datetime.now(timezone.utc)
        return record

    def delete_project(self, project_id):
        return self._rows.pop(project_id, None) is not None

    def duplicate_project(self, project_id):
        record = self._rows.get(project_id)
        if record is None:
            return None
        now = datetime.now(timezone.utc)
        duplicate = replace(
            record, id=str(uuid.uuid4()), name=f'{record.name} Copy', archived=False,
            created_at=now, updated_at=now,
        )
        self._rows[duplicate.id] = duplicate
        return duplicate


_memory_repository = InMemoryProjectsRepository()
_postgres_repository = PostgresProjectsRepository()


def get_projects_repository() -> ProjectsRepository:
    """FastAPI dependency. Defaults to Postgres; set API_REPOSITORY=memory to
    run/explore the API without a database (tests override this directly)."""
    if get_settings().repository_backend == 'memory':
        return _memory_repository
    return _postgres_repository
