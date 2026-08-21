import io

import pytest
from fastapi.testclient import TestClient

from app.auth import get_current_user
from app.main import app
from app.repositories.brands import InMemoryBrandsRepository, get_brands_repository
from app.repositories.mapping_templates import InMemoryMappingTemplatesRepository, get_mapping_templates_repository
from app.repositories.projects import InMemoryProjectsRepository, get_projects_repository
from app.repositories.ratings import InMemoryRatingsRepository, get_ratings_repository
from app.repositories.uploads import InMemoryUploadsRepository, get_uploads_repository

from ._auth_helpers import make_test_user


def _returning(instance):
    # See services/api/README.md's "Test fixture pitfall" note.
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
        get_mapping_templates_repository: InMemoryMappingTemplatesRepository(),
    }
    for dependency, instance in overrides.items():
        app.dependency_overrides[dependency] = _returning(instance)
    app.dependency_overrides[get_current_user] = _returning(make_test_user())
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def project(client):
    return client.post('/api/projects', json={'projectName': 'Seasoning Q1'}).json()


def test_no_issues_for_a_clean_project(client, project):
    response = client.get(f"/api/projects/{project['projectId']}/validation-issues")
    assert response.status_code == 200
    assert response.json() == []


def test_reports_invalid_and_duplicate_ratings_rows(client, project):
    dataset = client.post(
        '/api/ratings-datasets',
        json={
            'provider': 'Nielsen',
            'rows': [
                {'medium': 'TV', 'station': 'TVC', 'day': 'Monday', 'programme': 'Prime Time', 'rating': 1.2},
                {'medium': 'TV', 'station': 'TVC', 'day': 'Monday', 'programme': 'Prime Time', 'rating': 1.4},
                {'medium': '', 'station': '', 'day': 'Wednesday', 'rating': None},
            ],
        },
    ).json()
    client.post(f"/api/projects/{project['projectId']}/ratings-datasets/{dataset['ratingsDatasetId']}/attach")

    issues = client.get(f"/api/projects/{project['projectId']}/validation-issues").json()
    areas = {issue['area']: issue for issue in issues}
    assert 'Ratings — Nielsen' in areas
    messages = [i['message'] for i in issues if i['area'] == 'Ratings — Nielsen']
    assert any('invalid' in m.lower() or 'missing' in m.lower() for m in messages)
    assert any('more than one rating row' in m for m in messages)
    assert all(i['severity'] == 'warning' for i in issues)
    assert all(i['runId'] is None for i in issues)


def test_only_attached_datasets_are_reported(client, project):
    client.post('/api/ratings-datasets', json={
        'provider': 'Unattached', 'rows': [{'medium': '', 'station': '', 'day': '', 'rating': None}],
    })
    issues = client.get(f"/api/projects/{project['projectId']}/validation-issues").json()
    assert issues == []


def test_reports_upload_issue_rows(client, project):
    brand = client.post(f"/api/projects/{project['projectId']}/brands", json={'name': 'Brand A'}).json()
    content = (
        b'Channel,Programme,Day,Spots\n'
        b'TVC,Prime Time,Monday,3\n'
        b',News,Tuesday,2\n'  # missing Channel -> an issue row
    )
    files = {'file': ('report.csv', io.BytesIO(content), 'text/csv')}
    client.post(
        f"/api/projects/{project['projectId']}/uploads",
        files=files, data={'brand_id': brand['brandId']},
    )

    issues = client.get(f"/api/projects/{project['projectId']}/validation-issues").json()
    upload_issues = [i for i in issues if i['area'] == 'Upload — report.csv']
    assert len(upload_issues) == 1
    assert upload_issues[0]['rows'] == 1


def test_validation_issues_rejects_missing_project(client):
    response = client.get('/api/projects/does-not-exist/validation-issues')
    assert response.status_code == 404
