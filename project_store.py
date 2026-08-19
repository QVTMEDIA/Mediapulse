import json
import sqlite3
from contextlib import closing
from pathlib import Path


SCHEMA_VERSION = 1


def json_default(value):
    if hasattr(value, 'isoformat'):
        return value.isoformat()
    raise TypeError(f'Object of type {type(value).__name__} is not JSON serializable')


def connect(db_path):
    path = Path(db_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.row_factory = sqlite3.Row
    return connection


def init_store(db_path):
    with closing(connect(db_path)) as connection:
        with connection:
            connection.execute(
                '''
                CREATE TABLE IF NOT EXISTS project_store_meta (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
                '''
            )
            connection.execute(
                '''
                CREATE TABLE IF NOT EXISTS projects (
                    project_id TEXT PRIMARY KEY,
                    project_json TEXT NOT NULL,
                    archived INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL DEFAULT '',
                    updated_at TEXT NOT NULL DEFAULT ''
                )
                '''
            )
            connection.execute(
                '''
                INSERT INTO project_store_meta (key, value)
                VALUES ('schema_version', ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                ''',
                (str(SCHEMA_VERSION),),
            )


def project_payload(project):
    return json.dumps(project, default=json_default, sort_keys=True)


def load_projects(db_path):
    init_store(db_path)
    projects = {}
    with closing(connect(db_path)) as connection:
        rows = connection.execute(
            '''
            SELECT project_id, project_json
            FROM projects
            ORDER BY updated_at DESC, project_id ASC
            '''
        ).fetchall()

    for row in rows:
        project = json.loads(row['project_json'])
        if not isinstance(project, dict):
            continue
        project['project_id'] = str(project.get('project_id') or row['project_id'])
        projects[project['project_id']] = project
    return projects


def upsert_project(db_path, project):
    if not isinstance(project, dict):
        raise ValueError('Project must be a dictionary.')
    project_id = str(project.get('project_id', '')).strip()
    if not project_id:
        raise ValueError('Project ID is required.')

    init_store(db_path)
    with closing(connect(db_path)) as connection:
        with connection:
            connection.execute(
                '''
                INSERT INTO projects (project_id, project_json, archived, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(project_id) DO UPDATE SET
                    project_json = excluded.project_json,
                    archived = excluded.archived,
                    created_at = excluded.created_at,
                    updated_at = excluded.updated_at
                ''',
                (
                    project_id,
                    project_payload(project),
                    1 if project.get('archived') else 0,
                    str(project.get('created_at', '')),
                    str(project.get('updated_at', '')),
                ),
            )


def delete_project(db_path, project_id):
    init_store(db_path)
    with closing(connect(db_path)) as connection:
        with connection:
            connection.execute('DELETE FROM projects WHERE project_id = ?', (project_id,))


def replace_projects(db_path, projects):
    if isinstance(projects, dict):
        items = list(projects.values())
    elif isinstance(projects, list):
        items = projects
    else:
        items = []

    init_store(db_path)
    with closing(connect(db_path)) as connection:
        with connection:
            connection.execute('DELETE FROM projects')
            for project in items:
                if not isinstance(project, dict) or not project.get('project_id'):
                    continue
                connection.execute(
                    '''
                    INSERT INTO projects (project_id, project_json, archived, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?)
                    ''',
                    (
                        str(project['project_id']),
                        project_payload(project),
                        1 if project.get('archived') else 0,
                        str(project.get('created_at', '')),
                        str(project.get('updated_at', '')),
                    ),
                )
