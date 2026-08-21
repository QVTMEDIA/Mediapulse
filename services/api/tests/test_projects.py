import pytest
from fastapi.testclient import TestClient

from app.auth import get_current_user
from app.main import app
from app.repositories.projects import InMemoryProjectsRepository, get_projects_repository

from ._auth_helpers import make_test_user


@pytest.fixture
def client():
    repo = InMemoryProjectsRepository()
    app.dependency_overrides[get_projects_repository] = lambda: repo
    # 'owner' by default so the existing archive/delete tests below don't
    # need to know about role gating — test_update_project_requires_owner_
    # or_admin_to_archive and test_delete_project_requires_owner_or_admin
    # override this per-test to exercise the 403 path specifically.
    app.dependency_overrides[get_current_user] = lambda: make_test_user(role='owner')
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_health(client):
    response = client.get('/api/health')
    assert response.status_code == 200
    assert response.json() == {'status': 'ok'}


def test_create_project_applies_defaults(client):
    response = client.post('/api/projects', json={'projectName': 'Seasoning Q1'})
    assert response.status_code == 201
    body = response.json()
    assert body['projectName'] == 'Seasoning Q1'
    assert body['status'] == 'Setup'
    assert body['archived'] is False
    assert body['mediaTypes'] == []
    assert 'projectId' in body


def test_create_project_requires_name(client):
    response = client.post('/api/projects', json={'projectName': ''})
    assert response.status_code == 422


def test_create_project_rejects_unknown_status(client):
    response = client.post('/api/projects', json={'projectName': 'X', 'status': 'Bogus'})
    assert response.status_code == 422


def test_create_project_rejects_unknown_media_type(client):
    response = client.post('/api/projects', json={'projectName': 'X', 'mediaTypes': ['Digital']})
    assert response.status_code == 422


def test_get_project_round_trips(client):
    created = client.post('/api/projects', json={'projectName': 'Malaria Category', 'client': 'Client A'}).json()
    fetched = client.get(f"/api/projects/{created['projectId']}")
    assert fetched.status_code == 200
    assert fetched.json() == created


def test_get_missing_project_returns_404(client):
    response = client.get('/api/projects/does-not-exist')
    assert response.status_code == 404


def test_list_projects_filters_by_search(client):
    client.post('/api/projects', json={'projectName': 'Seasoning Cubes', 'category': 'Seasoning'})
    client.post('/api/projects', json={'projectName': 'Beverage Launch', 'category': 'Beverage'})

    response = client.get('/api/projects', params={'search': 'seasoning'})
    names = [p['projectName'] for p in response.json()]
    assert names == ['Seasoning Cubes']


def test_list_projects_filters_by_status(client):
    client.post('/api/projects', json={'projectName': 'A', 'status': 'Setup'})
    client.post('/api/projects', json={'projectName': 'B', 'status': 'Complete'})

    response = client.get('/api/projects', params={'status': 'Complete'})
    names = [p['projectName'] for p in response.json()]
    assert names == ['B']


def test_list_projects_can_exclude_archived(client):
    created = client.post('/api/projects', json={'projectName': 'Archive Me'}).json()
    client.patch(f"/api/projects/{created['projectId']}", json={'archived': True})

    response = client.get('/api/projects', params={'include_archived': False})
    assert created['projectId'] not in [p['projectId'] for p in response.json()]

    response = client.get('/api/projects', params={'include_archived': True})
    assert created['projectId'] in [p['projectId'] for p in response.json()]


def test_update_project_patches_only_provided_fields(client):
    created = client.post('/api/projects', json={'projectName': 'Malaria Category', 'client': 'Client A'}).json()
    response = client.patch(f"/api/projects/{created['projectId']}", json={'status': 'Data Review'})
    assert response.status_code == 200
    body = response.json()
    assert body['status'] == 'Data Review'
    assert body['client'] == 'Client A'  # untouched by the patch
    assert body['updatedAt'] != created['updatedAt']


def test_update_missing_project_returns_404(client):
    response = client.patch('/api/projects/does-not-exist', json={'status': 'Complete'})
    assert response.status_code == 404


def test_delete_project(client):
    created = client.post('/api/projects', json={'projectName': 'Delete Me'}).json()
    response = client.delete(f"/api/projects/{created['projectId']}")
    assert response.status_code == 204
    assert client.get(f"/api/projects/{created['projectId']}").status_code == 404


def test_delete_missing_project_returns_404(client):
    response = client.delete('/api/projects/does-not-exist')
    assert response.status_code == 404


def test_duplicate_project_copies_fields_with_new_id_and_name(client):
    created = client.post(
        '/api/projects',
        json={'projectName': 'Seasoning Cube Analysis', 'client': 'Client A', 'status': 'Data Review'},
    ).json()
    response = client.post(f"/api/projects/{created['projectId']}/duplicate")
    assert response.status_code == 201
    duplicate = response.json()
    assert duplicate['projectId'] != created['projectId']
    assert duplicate['projectName'] == 'Seasoning Cube Analysis Copy'
    assert duplicate['client'] == 'Client A'
    assert duplicate['status'] == 'Data Review'
    assert duplicate['archived'] is False


def test_duplicate_missing_project_returns_404(client):
    response = client.post('/api/projects/does-not-exist/duplicate')
    assert response.status_code == 404


def test_unimplemented_routes_return_501_with_roadmap_note(client):
    # Upload preview (a deliberate, not-currently-planned gap — mapping
    # applies automatically instead of through a preview/confirm step; see
    # services/api/README.md). Picked because it won't become real
    # partway through this session, unlike mapping-templates/stations/
    # versions/exports before it.
    response = client.get('/api/projects/does-not-matter/uploads/does-not-matter/preview')
    assert response.status_code == 501
    assert 'roadmap' in response.json()
