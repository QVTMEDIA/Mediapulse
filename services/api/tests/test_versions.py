import pytest
from fastapi.testclient import TestClient

from app.auth import get_current_user
from app.main import app
from app.repositories.brands import InMemoryBrandsRepository, get_brands_repository
from app.repositories.calculations import InMemoryCalculationsRepository, get_calculations_repository
from app.repositories.mapping_templates import InMemoryMappingTemplatesRepository, get_mapping_templates_repository
from app.repositories.matches import InMemoryMatchesRepository, get_matches_repository
from app.repositories.projects import InMemoryProjectsRepository, get_projects_repository
from app.repositories.ratings import InMemoryRatingsRepository, get_ratings_repository
from app.repositories.uploads import InMemoryUploadsRepository, get_uploads_repository

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
    }
    for dependency, instance in overrides.items():
        app.dependency_overrides[dependency] = _returning(instance)
    app.dependency_overrides[get_current_user] = _returning(make_test_user(role='owner'))
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


UPLOAD_CSV = b'Channel,Programme,Day,Spots\nAIT,Morning Show,Monday,3\n'
RATINGS_ROWS = [{'medium': 'TV', 'station': 'AIT', 'day': 'MON', 'programme': 'Morning Show', 'rating': 5.0}]


def _project(client):
    return client.post('/api/projects', json={'projectName': 'Version History Test'}).json()


def _seed_and_calculate(client, project_id):
    client.post(
        f'/api/projects/{project_id}/uploads',
        data={'kind': 'brand_report', 'brand_id': _brand(client, project_id), 'default_medium': 'TV'},
        files={'file': ('report.csv', UPLOAD_CSV, 'text/csv')},
    )
    dataset = client.post('/api/ratings-datasets', json={'provider': 'P', 'rows': RATINGS_ROWS}).json()
    client.post(f"/api/projects/{project_id}/ratings-datasets/{dataset['ratingsDatasetId']}/attach")
    return client.post(f'/api/projects/{project_id}/calculate').json()


def _brand(client, project_id):
    # Reused across multiple _seed_and_calculate() calls for the same
    # project in a single test — brand names are unique per project, so
    # creating "Brand A" twice would 409.
    existing = client.get(f'/api/projects/{project_id}/brands').json()
    if existing:
        return existing[0]['brandId']
    return client.post(f'/api/projects/{project_id}/brands', json={'name': 'Brand A'}).json()['brandId']


def test_list_versions_empty_for_new_project(client):
    project = _project(client)
    response = client.get(f"/api/projects/{project['projectId']}/versions")
    assert response.status_code == 200
    assert response.json() == []


def test_each_calculate_call_adds_a_version(client):
    project = _project(client)
    _seed_and_calculate(client, project['projectId'])
    _seed_and_calculate(client, project['projectId'])

    response = client.get(f"/api/projects/{project['projectId']}/versions")
    versions = response.json()
    assert len(versions) == 2
    assert sum(1 for v in versions if v['isCurrent']) == 1
    # newest run is current by default
    assert versions[0]['isCurrent'] is True
    assert 'GRP' in versions[0]['description']


def test_restore_pins_latest_to_an_older_run(client):
    project = _project(client)
    project_id = project['projectId']
    first_run = _seed_and_calculate(client, project_id)
    second_run = _seed_and_calculate(client, project_id)
    assert first_run['runId'] != second_run['runId']

    # latest is the second (newest) run before any restore
    latest = client.get(f'/api/projects/{project_id}/runs/latest').json()
    assert latest['runId'] == second_run['runId']
    assert latest['isCurrent'] is True

    response = client.post(f"/api/projects/{project_id}/versions/{first_run['runId']}/restore")
    assert response.status_code == 200
    assert response.json()['isCurrent'] is True
    assert response.json()['runId'] == first_run['runId']

    latest = client.get(f'/api/projects/{project_id}/runs/latest').json()
    assert latest['runId'] == first_run['runId']
    assert latest['isCurrent'] is True

    # the second run is no longer current, but still exists (nothing deleted)
    versions = client.get(f'/api/projects/{project_id}/versions').json()
    assert len(versions) == 2
    second_version = next(v for v in versions if v['runId'] == second_run['runId'])
    assert second_version['isCurrent'] is False
    # its calculations are still readable — restoring doesn't erase history.
    # (2 rows, not 1: the second calculate() ran over both the first and
    # second upload's media_activity, since calculate always covers the
    # whole project rather than just what's new since the last run.)
    calcs = client.get(f"/api/projects/{project_id}/runs/{second_run['runId']}/calculations")
    assert calcs.status_code == 200
    assert len(calcs.json()) == 2


def test_restore_unknown_version_returns_404(client):
    project = _project(client)
    response = client.post(f"/api/projects/{project['projectId']}/versions/does-not-exist/restore")
    assert response.status_code == 404


def test_restore_requires_owner_or_admin(client):
    project = _project(client)
    run = _seed_and_calculate(client, project['projectId'])

    app.dependency_overrides[get_current_user] = _returning(make_test_user(role='member'))
    response = client.post(f"/api/projects/{project['projectId']}/versions/{run['runId']}/restore")
    assert response.status_code == 403


def test_versions_scoped_to_project(client):
    project_a = _project(client)
    project_b = client.post('/api/projects', json={'projectName': 'Other Project'}).json()
    _seed_and_calculate(client, project_a['projectId'])

    response = client.get(f"/api/projects/{project_b['projectId']}/versions")
    assert response.status_code == 200
    assert response.json() == []


def test_versions_for_missing_project_returns_404(client):
    response = client.get('/api/projects/does-not-exist/versions')
    assert response.status_code == 404
