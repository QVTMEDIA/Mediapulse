import io

import pytest
from fastapi.testclient import TestClient

from app.auth import get_current_user
from app.main import app
from app.repositories.activity_log import InMemoryActivityLogRepository, get_activity_log_repository
from app.repositories.brands import InMemoryBrandsRepository, get_brands_repository
from app.repositories.calculations import InMemoryCalculationsRepository, get_calculations_repository
from app.repositories.mapping_templates import InMemoryMappingTemplatesRepository, get_mapping_templates_repository
from app.repositories.matches import InMemoryMatchesRepository, get_matches_repository
from app.repositories.projects import InMemoryProjectsRepository, get_projects_repository
from app.repositories.ratings import InMemoryRatingsRepository, get_ratings_repository
from app.repositories.uploads import InMemoryUploadsRepository, get_uploads_repository
from app.repositories.users import InMemoryUsersRepository, get_users_repository

from ._auth_helpers import make_test_user


def _returning(instance):
    def _get():
        return instance

    return _get


@pytest.fixture
def client():
    overrides = {
        get_projects_repository: InMemoryProjectsRepository(),
        get_brands_repository: InMemoryBrandsRepository(),
        get_uploads_repository: InMemoryUploadsRepository(),
        get_ratings_repository: InMemoryRatingsRepository(),
        get_matches_repository: InMemoryMatchesRepository(),
        get_calculations_repository: InMemoryCalculationsRepository(),
        get_mapping_templates_repository: InMemoryMappingTemplatesRepository(),
        get_users_repository: InMemoryUsersRepository(),
        get_activity_log_repository: InMemoryActivityLogRepository(),
    }
    for dependency, instance in overrides.items():
        app.dependency_overrides[dependency] = _returning(instance)
    app.dependency_overrides[get_current_user] = _returning(make_test_user(role='owner'))
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _project(client):
    return client.post('/api/projects', json={'projectName': 'Activity Log Test'}).json()


def test_project_created_is_logged(client):
    project = _project(client)
    entries = client.get('/api/activity-log').json()['entries']
    assert len(entries) == 1
    entry = entries[0]
    assert entry['action'] == 'project.created'
    assert entry['projectId'] == project['projectId']
    assert entry['projectName'] == 'Activity Log Test'
    assert 'Activity Log Test' in entry['summary']
    assert entry['actorName'] == 'Test User'


def test_project_archived_and_deleted_are_logged(client):
    project = _project(client)
    client.patch(f"/api/projects/{project['projectId']}", json={'archived': True})
    client.delete(f"/api/projects/{project['projectId']}")

    entries = client.get('/api/activity-log').json()['entries']
    # Newest first: delete, archive, create.
    actions = [e['action'] for e in entries]
    assert actions == ['project.deleted', 'project.archived', 'project.created']
    # The delete entry has no projectId (the project no longer exists) but
    # still names it in the summary.
    delete_entry = entries[0]
    assert delete_entry['projectId'] is None
    assert 'Activity Log Test' in delete_entry['summary']


def test_brand_created_and_deleted_are_logged(client):
    project = _project(client)
    brand = client.post(f"/api/projects/{project['projectId']}/brands", json={'name': 'PANADOL'}).json()
    client.delete(f"/api/projects/{project['projectId']}/brands/{brand['brandId']}")

    entries = client.get('/api/activity-log').json()['entries']
    actions = [e['action'] for e in entries]
    assert actions[:2] == ['brand.deleted', 'brand.created']
    assert 'PANADOL' in entries[0]['summary']
    assert 'PANADOL' in entries[1]['summary']


def test_upload_is_logged(client):
    project = _project(client)
    brand = client.post(f"/api/projects/{project['projectId']}/brands", json={'name': 'Brand A'}).json()
    csv = b'Channel,Programme,Day,Spots\nAIT,Morning Show,Monday,3\n'
    client.post(
        f"/api/projects/{project['projectId']}/uploads",
        data={'kind': 'brand_report', 'brand_id': brand['brandId'], 'default_medium': 'TV'},
        files={'file': ('report.csv', io.BytesIO(csv), 'text/csv')},
    )

    entries = client.get('/api/activity-log').json()['entries']
    upload_entry = next(e for e in entries if e['action'] == 'upload.media_report')
    assert 'report.csv' in upload_entry['summary']
    assert upload_entry['projectId'] == project['projectId']


def test_calculate_run_is_logged(client):
    project = _project(client)
    client.post(f"/api/projects/{project['projectId']}/calculate")

    entries = client.get('/api/activity-log').json()['entries']
    assert entries[0]['action'] == 'calculate.run'
    assert entries[0]['projectId'] == project['projectId']


def test_match_correction_is_logged(client):
    project = _project(client)
    project_id = project['projectId']
    brand = client.post(f"/api/projects/{project_id}/brands", json={'name': 'Brand A'}).json()
    csv = b'Channel,Programme,Day,Spots\nAIT,Morning Show,Monday,3\n'
    client.post(
        f'/api/projects/{project_id}/uploads',
        data={'kind': 'brand_report', 'brand_id': brand['brandId'], 'default_medium': 'TV'},
        files={'file': ('report.csv', io.BytesIO(csv), 'text/csv')},
    )
    matches = client.get(f'/api/projects/{project_id}/matches').json()
    match_id = matches[0]['ratingMatchId']
    client.post(f'/api/projects/{project_id}/matches/{match_id}/correct', json={'matchedRatingId': None})

    entries = client.get('/api/activity-log').json()['entries']
    assert entries[0]['action'] == 'match.corrected'
    assert entries[0]['projectId'] == project_id


def test_match_recompute_is_logged_but_ensure_is_not(client):
    project = _project(client)
    project_id = project['projectId']
    # 'ensure' is the automatic job the Matches screen fires on every visit
    # -- not a human action, so it must not show up in the feed.
    client.post(f'/api/projects/{project_id}/matches/jobs', params={'mode': 'ensure'})
    entries = client.get('/api/activity-log').json()['entries']
    assert [e for e in entries if e['action'] == 'match.recompute'] == []

    client.post(f'/api/projects/{project_id}/matches/jobs', params={'mode': 'recompute'})
    entries = client.get('/api/activity-log').json()['entries']
    assert entries[0]['action'] == 'match.recompute'
    assert 'Fast recompute' in entries[0]['summary']


def test_ratings_dataset_upload_attach_and_detach_are_logged(client):
    project = _project(client)
    project_id = project['projectId']
    dataset = client.post(
        '/api/ratings-datasets',
        json={'provider': 'Nielsen', 'period': 'Q1', 'rows': [
            {'medium': 'TV', 'station': 'AIT', 'day': 'MON', 'programme': 'Morning Show', 'rating': 5.0},
        ]},
    ).json()
    dataset_id = dataset['ratingsDatasetId']
    client.post(f'/api/projects/{project_id}/ratings-datasets/{dataset_id}/attach')
    client.delete(f'/api/projects/{project_id}/ratings-datasets/{dataset_id}/attach')

    entries = client.get('/api/activity-log').json()['entries']
    actions = [e['action'] for e in entries]
    assert actions[:2] == ['ratings.detached', 'ratings.attached']


def test_role_change_is_logged(client):
    member = client.post(
        '/api/auth/register', json={'email': 'member@example.com', 'password': 'password123'}
    )
    # The register call above is itself logged ('user.registered') via its
    # own un-authenticated flow; find the newly created member's id via the
    # team list rather than assuming entry order.
    users = client.get('/api/users').json()
    target = next(u for u in users if u['email'] == 'member@example.com')
    client.patch(f"/api/users/{target['userId']}/role", json={'role': 'admin'})

    entries = client.get('/api/activity-log').json()['entries']
    assert entries[0]['action'] == 'user.role_changed'
    assert 'admin' in entries[0]['summary']
    assert member.status_code == 201


def test_register_and_login_are_logged():
    # Separate client (no auth override) -- these two routes are the only
    # ones reachable without a bearer token.
    app.dependency_overrides[get_projects_repository] = _returning(InMemoryProjectsRepository())
    app.dependency_overrides[get_users_repository] = _returning(InMemoryUsersRepository())
    activity_repo = InMemoryActivityLogRepository()
    app.dependency_overrides[get_activity_log_repository] = _returning(activity_repo)
    try:
        with TestClient(app) as test_client:
            test_client.post('/api/auth/register', json={'email': 'new@example.com', 'password': 'password123'})
            test_client.post('/api/auth/login', json={'email': 'new@example.com', 'password': 'password123'})
    finally:
        app.dependency_overrides.clear()

    actions = [e.action for e in activity_repo.list_entries(limit=10, offset=0).entries]
    assert actions == ['user.signed_in', 'user.registered']


def test_pagination(client):
    for i in range(5):
        client.post('/api/projects', json={'projectName': f'Project {i}'})

    page_one = client.get('/api/activity-log', params={'limit': 2, 'offset': 0}).json()
    assert len(page_one['entries']) == 2
    assert page_one['total'] == 5
    assert page_one['entries'][0]['summary'].endswith('"Project 4".')

    page_two = client.get('/api/activity-log', params={'limit': 2, 'offset': 2}).json()
    assert len(page_two['entries']) == 2
    assert page_two['entries'][0]['summary'].endswith('"Project 2".')


def test_any_signed_in_role_can_read_the_log(client):
    app.dependency_overrides[get_current_user] = _returning(make_test_user(role='member'))
    _project(client)
    response = client.get('/api/activity-log')
    assert response.status_code == 200
    assert len(response.json()['entries']) == 1
