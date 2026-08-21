import io

import pytest
from fastapi.testclient import TestClient

from app.auth import get_current_user
from app.main import app
from app.repositories.brands import InMemoryBrandsRepository, get_brands_repository
from app.repositories.mapping_templates import InMemoryMappingTemplatesRepository, get_mapping_templates_repository
from app.repositories.projects import InMemoryProjectsRepository, get_projects_repository
from app.repositories.uploads import InMemoryUploadsRepository, get_uploads_repository

from ._auth_helpers import make_test_user


@pytest.fixture
def client():
    projects_repo = InMemoryProjectsRepository()
    brands_repo = InMemoryBrandsRepository()
    uploads_repo = InMemoryUploadsRepository()
    templates_repo = InMemoryMappingTemplatesRepository()
    app.dependency_overrides[get_projects_repository] = lambda: projects_repo
    app.dependency_overrides[get_brands_repository] = lambda: brands_repo
    app.dependency_overrides[get_uploads_repository] = lambda: uploads_repo
    app.dependency_overrides[get_mapping_templates_repository] = lambda: templates_repo
    app.dependency_overrides[get_current_user] = lambda: make_test_user()
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def project(client):
    return client.post('/api/projects', json={'projectName': 'Seasoning Q1'}).json()


@pytest.fixture
def brand(client, project):
    return client.post(f"/api/projects/{project['projectId']}/brands", json={'name': 'Brand A'}).json()


def test_create_and_list_mapping_template(client):
    response = client.post(
        '/api/mapping-templates',
        json={'sourceLabel': 'Agency A', 'fieldMapping': {'channel': 'Media Channel', 'programme': 'Show'}},
    )
    assert response.status_code == 201
    body = response.json()
    assert body['sourceLabel'] == 'Agency A'
    assert body['fieldMapping'] == {'channel': 'Media Channel', 'programme': 'Show'}
    assert body['lastUsedAt'] is None

    listed = client.get('/api/mapping-templates').json()
    assert [t['sourceLabel'] for t in listed] == ['Agency A']


def test_create_mapping_template_updates_existing_by_source_label(client):
    client.post('/api/mapping-templates', json={'sourceLabel': 'Agency A', 'fieldMapping': {'channel': 'X'}})
    response = client.post('/api/mapping-templates', json={'sourceLabel': 'Agency A', 'fieldMapping': {'channel': 'Y'}})
    assert response.status_code == 201
    assert response.json()['fieldMapping'] == {'channel': 'Y'}

    listed = client.get('/api/mapping-templates').json()
    assert len(listed) == 1  # updated in place, not duplicated


def test_suggest_returns_saved_template(client):
    client.post('/api/mapping-templates', json={'sourceLabel': 'Agency A', 'fieldMapping': {'channel': 'Media Channel'}})
    response = client.get('/api/mapping-templates/suggest', params={'sourceLabel': 'Agency A'})
    assert response.status_code == 200
    assert response.json()['fieldMapping'] == {'channel': 'Media Channel'}


def test_suggest_404_for_unknown_source_label(client):
    response = client.get('/api/mapping-templates/suggest', params={'sourceLabel': 'Nobody'})
    assert response.status_code == 404


UPLOAD_CSV = b'Channel,Programme,Weekday,Insertions\nTVC,Prime Time,Monday,3\n'


def _upload_with_source(client, project_id, brand_id, source_label, **form):
    files = {'file': ('report.csv', io.BytesIO(UPLOAD_CSV), 'text/csv')}
    data = {'brand_id': brand_id, 'source_label': source_label, **form}
    return client.post(f'/api/projects/{project_id}/uploads', files=files, data=data)


def test_first_upload_from_a_source_saves_the_detected_mapping(client, project, brand):
    response = _upload_with_source(client, project['projectId'], brand['brandId'], 'Agency A')
    assert response.status_code == 201
    assert response.json()['mappedRows'] == 1  # column-synonym detection still found everything

    template = client.get('/api/mapping-templates/suggest', params={'sourceLabel': 'Agency A'}).json()
    assert template['fieldMapping']['channel'] == 'Channel'
    assert template['fieldMapping']['programme'] == 'Programme'
    assert template['fieldMapping']['spots'] == 'Insertions'
    assert template['lastUsedAt'] is None  # saved, not yet "used" via a template lookup


def test_second_upload_from_same_source_reuses_and_touches_the_template(client, project, brand):
    client.post(
        '/api/mapping-templates',
        json={'sourceLabel': 'Agency A', 'fieldMapping': {
            'channel': 'Channel', 'programme': 'Programme', 'day': 'Weekday', 'spots': 'Insertions',
        }},
    )
    response = _upload_with_source(client, project['projectId'], brand['brandId'], 'Agency A')
    assert response.status_code == 201
    assert response.json()['mappedRows'] == 1

    template = client.get('/api/mapping-templates/suggest', params={'sourceLabel': 'Agency A'}).json()
    assert template['lastUsedAt'] is not None  # touched by the upload that reused it


def test_upload_falls_back_to_auto_detect_when_template_column_is_missing(client, project, brand):
    # a stale template pointing at a column this file doesn't have
    client.post(
        '/api/mapping-templates',
        json={'sourceLabel': 'Agency A', 'fieldMapping': {'channel': 'This Column Does Not Exist'}},
    )
    response = _upload_with_source(client, project['projectId'], brand['brandId'], 'Agency A')
    assert response.status_code == 201
    assert response.json()['mappedRows'] == 1  # still parsed correctly via auto-detect fallback

    activity = client.get(f"/api/projects/{project['projectId']}/media-activity").json()
    assert activity[0]['station'] == 'TVC'


def test_save_as_template_true_overwrites_an_existing_template(client, project, brand):
    client.post('/api/mapping-templates', json={'sourceLabel': 'Agency A', 'fieldMapping': {'channel': 'Wrong Column'}})
    response = _upload_with_source(client, project['projectId'], brand['brandId'], 'Agency A', save_as_template='true')
    assert response.status_code == 201

    template = client.get('/api/mapping-templates/suggest', params={'sourceLabel': 'Agency A'}).json()
    assert template['fieldMapping']['channel'] == 'Channel'  # overwritten with what was actually used


def test_upload_without_source_label_does_not_touch_templates(client, project, brand):
    files = {'file': ('report.csv', io.BytesIO(UPLOAD_CSV), 'text/csv')}
    client.post(
        f"/api/projects/{project['projectId']}/uploads", files=files, data={'brand_id': brand['brandId']}
    )
    assert client.get('/api/mapping-templates').json() == []
