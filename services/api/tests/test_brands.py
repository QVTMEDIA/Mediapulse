import pytest
from fastapi.testclient import TestClient

from app.auth import get_current_user
from app.main import app
from app.repositories.brands import InMemoryBrandsRepository, get_brands_repository
from app.repositories.projects import InMemoryProjectsRepository, get_projects_repository

from ._auth_helpers import make_test_user


@pytest.fixture
def client():
    projects_repo = InMemoryProjectsRepository()
    brands_repo = InMemoryBrandsRepository()
    app.dependency_overrides[get_projects_repository] = lambda: projects_repo
    app.dependency_overrides[get_brands_repository] = lambda: brands_repo
    app.dependency_overrides[get_current_user] = lambda: make_test_user()
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def project(client):
    return client.post('/api/projects', json={'projectName': 'Seasoning Q1'}).json()


def test_create_brand(client, project):
    response = client.post(f"/api/projects/{project['projectId']}/brands", json={'name': 'Brand A'})
    assert response.status_code == 201
    body = response.json()
    assert body['name'] == 'Brand A'
    assert body['projectId'] == project['projectId']
    assert 'brandId' in body
    assert 'createdAt' in body


def test_create_brand_requires_name(client, project):
    response = client.post(f"/api/projects/{project['projectId']}/brands", json={'name': ''})
    assert response.status_code == 422


def test_create_brand_for_missing_project_returns_404(client):
    response = client.post('/api/projects/does-not-exist/brands', json={'name': 'Brand A'})
    assert response.status_code == 404


def test_create_duplicate_brand_name_returns_409(client, project):
    client.post(f"/api/projects/{project['projectId']}/brands", json={'name': 'Brand A'})
    response = client.post(f"/api/projects/{project['projectId']}/brands", json={'name': 'Brand A'})
    assert response.status_code == 409


def test_same_brand_name_allowed_in_different_projects(client, project):
    other_project = client.post('/api/projects', json={'projectName': 'Malaria Category'}).json()
    client.post(f"/api/projects/{project['projectId']}/brands", json={'name': 'Brand A'})
    response = client.post(f"/api/projects/{other_project['projectId']}/brands", json={'name': 'Brand A'})
    assert response.status_code == 201


def test_list_brands_sorted_by_name(client, project):
    client.post(f"/api/projects/{project['projectId']}/brands", json={'name': 'Brand C'})
    client.post(f"/api/projects/{project['projectId']}/brands", json={'name': 'Brand A'})
    client.post(f"/api/projects/{project['projectId']}/brands", json={'name': 'Brand B'})

    response = client.get(f"/api/projects/{project['projectId']}/brands")
    assert response.status_code == 200
    assert [b['name'] for b in response.json()] == ['Brand A', 'Brand B', 'Brand C']


def test_list_brands_for_missing_project_returns_404(client):
    response = client.get('/api/projects/does-not-exist/brands')
    assert response.status_code == 404


def test_list_brands_empty_for_new_project(client, project):
    response = client.get(f"/api/projects/{project['projectId']}/brands")
    assert response.json() == []
