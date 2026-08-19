import uuid
import unittest
from contextlib import contextmanager
from pathlib import Path

import pandas as pd

import project_store


ROOT = Path(__file__).resolve().parents[1]
TEST_OUTPUT = ROOT / '.test-output'


@contextmanager
def temporary_db_path():
    TEST_OUTPUT.mkdir(exist_ok=True)
    db_path = TEST_OUTPUT / f'projects_{uuid.uuid4().hex}.db'
    try:
        yield db_path
    finally:
        for path in [db_path, db_path.with_suffix('.db-shm'), db_path.with_suffix('.db-wal')]:
            path.unlink(missing_ok=True)


class ProjectStoreTests(unittest.TestCase):
    def test_sqlite_project_store_round_trips_projects(self):
        with temporary_db_path() as db_path:
            project = {
                'project_id': 'MP-1234',
                'project_name': 'Seasoning Category Q1',
                'media_types': ['TV', 'Radio'],
                'archived': False,
                'created_at': '2026-08-19 10:00:00',
                'updated_at': '2026-08-19 10:30:00',
                'start_date': pd.Timestamp('2026-01-01'),
            }

            project_store.upsert_project(db_path, project)
            projects = project_store.load_projects(db_path)

            self.assertEqual(list(projects), ['MP-1234'])
            self.assertEqual(projects['MP-1234']['project_name'], 'Seasoning Category Q1')
            self.assertEqual(projects['MP-1234']['media_types'], ['TV', 'Radio'])
            self.assertEqual(projects['MP-1234']['start_date'], '2026-01-01T00:00:00')

    def test_sqlite_project_store_updates_and_deletes_project(self):
        with temporary_db_path() as db_path:
            project = {
                'project_id': 'MP-1234',
                'project_name': 'Original',
                'archived': False,
                'created_at': '2026-08-19 10:00:00',
                'updated_at': '2026-08-19 10:30:00',
            }

            project_store.upsert_project(db_path, project)
            project['project_name'] = 'Updated'
            project['archived'] = True
            project_store.upsert_project(db_path, project)

            projects = project_store.load_projects(db_path)
            self.assertEqual(projects['MP-1234']['project_name'], 'Updated')
            self.assertTrue(projects['MP-1234']['archived'])

            project_store.delete_project(db_path, 'MP-1234')
            self.assertEqual(project_store.load_projects(db_path), {})

    def test_sqlite_project_store_replaces_project_collection(self):
        with temporary_db_path() as db_path:
            project_store.upsert_project(db_path, {'project_id': 'MP-OLD', 'project_name': 'Old'})
            project_store.replace_projects(db_path, [
                {'project_id': 'MP-NEW', 'project_name': 'New'},
            ])

            projects = project_store.load_projects(db_path)
            self.assertEqual(list(projects), ['MP-NEW'])
            self.assertEqual(projects['MP-NEW']['project_name'], 'New')

    def test_sqlite_project_store_rejects_missing_project_id(self):
        with temporary_db_path() as db_path:
            with self.assertRaisesRegex(ValueError, 'Project ID'):
                project_store.upsert_project(db_path, {'project_name': 'Missing ID'})


if __name__ == '__main__':
    unittest.main()
