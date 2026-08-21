from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Dict, List, Optional, Protocol

from ..config import get_settings
from ..db import get_connection

VALID_ROLES = ('owner', 'admin', 'member')


@dataclass
class UserRecord:
    id: str
    email: str
    display_name: str
    password_hash: Optional[str]
    role: str
    created_at: datetime


class UsersRepository(Protocol):
    def get_by_id(self, user_id: str) -> Optional[UserRecord]: ...

    def get_by_email(self, email: str) -> Optional[UserRecord]: ...

    def list_users(self) -> List[UserRecord]: ...

    def count_users(self) -> int: ...

    def create_user(self, email: str, display_name: str, password_hash: str, role: str) -> UserRecord: ...

    def update_role(self, user_id: str, role: str) -> Optional[UserRecord]: ...


def _row_to_record(row: dict) -> UserRecord:
    return UserRecord(
        id=str(row['id']),
        email=row['email'],
        display_name=row['display_name'] or '',
        password_hash=row['password_hash'],
        role=row['role'],
        created_at=row['created_at'],
    )


class PostgresUsersRepository:
    """Reads/writes the `users` table defined in db/schema.sql."""

    def get_by_id(self, user_id: str):
        with get_connection() as conn:
            row = conn.execute('SELECT * FROM users WHERE id = %s', [user_id]).fetchone()
        return _row_to_record(row) if row else None

    def get_by_email(self, email: str):
        with get_connection() as conn:
            row = conn.execute('SELECT * FROM users WHERE lower(email) = lower(%s)', [email]).fetchone()
        return _row_to_record(row) if row else None

    def list_users(self):
        with get_connection() as conn:
            rows = conn.execute('SELECT * FROM users ORDER BY created_at ASC').fetchall()
        return [_row_to_record(row) for row in rows]

    def count_users(self) -> int:
        with get_connection() as conn:
            row = conn.execute('SELECT count(*) AS n FROM users').fetchone()
        return int(row['n'])

    def create_user(self, email: str, display_name: str, password_hash: str, role: str):
        with get_connection() as conn:
            row = conn.execute(
                '''
                INSERT INTO users (email, display_name, password_hash, role)
                VALUES (%s, %s, %s, %s)
                RETURNING *
                ''',
                [email, display_name, password_hash, role],
            ).fetchone()
        return _row_to_record(row)

    def update_role(self, user_id: str, role: str):
        with get_connection() as conn:
            row = conn.execute(
                'UPDATE users SET role = %s WHERE id = %s RETURNING *', [role, user_id]
            ).fetchone()
        return _row_to_record(row) if row else None


class InMemoryUsersRepository:
    """Stand-in for tests and for local exploration without Postgres running
    (set API_REPOSITORY=memory). Not persisted across process restarts."""

    def __init__(self):
        self._rows: Dict[str, UserRecord] = {}

    def get_by_id(self, user_id: str):
        return self._rows.get(user_id)

    def get_by_email(self, email: str):
        needle = email.lower()
        for record in self._rows.values():
            if record.email.lower() == needle:
                return record
        return None

    def list_users(self):
        return sorted(self._rows.values(), key=lambda r: r.created_at)

    def count_users(self) -> int:
        return len(self._rows)

    def create_user(self, email: str, display_name: str, password_hash: str, role: str):
        record = UserRecord(
            id=str(uuid.uuid4()),
            email=email,
            display_name=display_name,
            password_hash=password_hash,
            role=role,
            created_at=datetime.now(timezone.utc),
        )
        self._rows[record.id] = record
        return record

    def update_role(self, user_id: str, role: str):
        record = self._rows.get(user_id)
        if record is None:
            return None
        record.role = role
        return record


_memory_repository = InMemoryUsersRepository()
_postgres_repository = PostgresUsersRepository()


def get_users_repository() -> UsersRepository:
    """FastAPI dependency. Defaults to Postgres; set API_REPOSITORY=memory to
    run/explore the API without a database (tests override this directly)."""
    if get_settings().repository_backend == 'memory':
        return _memory_repository
    return _postgres_repository
