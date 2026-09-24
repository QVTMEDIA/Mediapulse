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
    mapping_templates_repo = InMemoryMappingTemplatesRepository()
    app.dependency_overrides[get_projects_repository] = lambda: projects_repo
    app.dependency_overrides[get_brands_repository] = lambda: brands_repo
    app.dependency_overrides[get_uploads_repository] = lambda: uploads_repo
    app.dependency_overrides[get_mapping_templates_repository] = lambda: mapping_templates_repo
    app.dependency_overrides[get_current_user] = lambda: make_test_user()
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def project(client):
    return client.post('/api/projects', json={'projectName': 'SOE Test'}).json()


# Brand A: 200k TV/NTA/Lagos + 150k Radio/CoolFM/Abuja = 350k total.
# Brand B: 90k TV/NTA/Lagos + 160k TV/Channels/Kano = 250k total.
# Category total: 600k.
SOE_CSV = (
    b'Brand,Medium,Station,Region,Day,Programme,Spots,Rate\n'
    b'Brand A,TV,NTA,Lagos,Monday,Breakfast Show,2,100000\n'
    b'Brand A,Radio,Cool FM,Abuja,Tuesday,Drive Time,3,50000\n'
    b'Brand B,TV,NTA,Lagos,Monday,Breakfast Show,1,90000\n'
    b'Brand B,TV,Channels,Kano,Wednesday,News,4,40000\n'
)


def _upload_soe_csv(client, project_id):
    files = {'file': ('spend.csv', io.BytesIO(SOE_CSV), 'text/csv')}
    response = client.post(f'/api/projects/{project_id}/uploads', files=files, data={'kind': 'composite_report'})
    assert response.status_code == 201
    return response.json()


def test_soe_filters_returns_distinct_values_present(client, project):
    _upload_soe_csv(client, project['projectId'])
    response = client.get(f"/api/projects/{project['projectId']}/soe/filters")
    assert response.status_code == 200
    body = response.json()
    assert body['mediums'] == ['Radio', 'TV']
    assert body['stations'] == ['Channels', 'Cool FM', 'NTA']
    assert body['regions'] == ['Abuja', 'Kano', 'Lagos']
    assert body['days'] == ['Monday', 'Tuesday', 'Wednesday']


def test_soe_filters_rejects_missing_project(client):
    response = client.get('/api/projects/does-not-exist/soe/filters')
    assert response.status_code == 404


def test_soe_unfiltered_computes_share_of_total_category_spend(client, project):
    _upload_soe_csv(client, project['projectId'])
    response = client.get(f"/api/projects/{project['projectId']}/soe")
    assert response.status_code == 200
    body = response.json()
    assert body['totalSpend'] == pytest.approx(600_000)
    by_brand = {row['brand']: row for row in body['brands']}
    assert by_brand['Brand A']['spend'] == pytest.approx(350_000)
    assert by_brand['Brand A']['soe'] == pytest.approx(58.3333, rel=1e-3)
    assert by_brand['Brand B']['spend'] == pytest.approx(250_000)
    assert by_brand['Brand B']['soe'] == pytest.approx(41.6667, rel=1e-3)


def test_soe_medium_filter_recomputes_share_within_that_medium_only(client, project):
    _upload_soe_csv(client, project['projectId'])
    response = client.get(f"/api/projects/{project['projectId']}/soe", params={'medium': 'TV'})
    assert response.status_code == 200
    body = response.json()
    assert body['totalSpend'] == pytest.approx(450_000)  # Brand A's radio spend excluded
    by_brand = {row['brand']: row for row in body['brands']}
    assert by_brand['Brand A']['spend'] == pytest.approx(200_000)
    assert by_brand['Brand B']['spend'] == pytest.approx(250_000)


def test_soe_region_filter_isolates_that_region(client, project):
    _upload_soe_csv(client, project['projectId'])
    response = client.get(f"/api/projects/{project['projectId']}/soe", params={'region': 'Lagos'})
    assert response.status_code == 200
    body = response.json()
    assert body['totalSpend'] == pytest.approx(290_000)
    by_brand = {row['brand']: row for row in body['brands']}
    assert set(by_brand) == {'Brand A', 'Brand B'}


def test_soe_combined_filters_and_together(client, project):
    _upload_soe_csv(client, project['projectId'])
    # Kano only has Brand B's row -- Brand A should disappear entirely.
    response = client.get(f"/api/projects/{project['projectId']}/soe", params={'medium': 'TV', 'region': 'Kano'})
    assert response.status_code == 200
    body = response.json()
    by_brand = {row['brand']: row for row in body['brands']}
    assert set(by_brand) == {'Brand B'}
    assert by_brand['Brand B']['soe'] == pytest.approx(100.0)


def test_soe_works_before_any_calculation_has_ever_run(client, project):
    # No POST .../calculate anywhere in this test -- SOE is a live query
    # over media_activity, not a snapshot from a run.
    _upload_soe_csv(client, project['projectId'])
    response = client.get(f"/api/projects/{project['projectId']}/soe")
    assert response.status_code == 200
    assert response.json()['totalSpend'] > 0


def test_soe_empty_project_returns_zero_with_no_error(client, project):
    response = client.get(f"/api/projects/{project['projectId']}/soe")
    assert response.status_code == 200
    body = response.json()
    assert body['totalSpend'] == 0
    assert body['brands'] == []


def test_soe_rejects_missing_project(client):
    response = client.get('/api/projects/does-not-exist/soe')
    assert response.status_code == 404


def test_soe_requires_authentication():
    with TestClient(app) as anon_client:
        response = anon_client.get('/api/projects/whatever/soe')
        assert response.status_code == 401


# A second, unrelated upload to the same project -- Brand C only, on a
# station/region/day the first upload never touches. Proves upload_id
# scoping actually isolates one file's rows rather than still pooling
# every upload a project has ever had.
SECOND_UPLOAD_CSV = (
    b'Brand,Medium,Station,Region,Day,Programme,Spots,Rate\n'
    b'Brand C,Radio,Wazobia,Rivers,Friday,Drive Time,2,60000\n'
)


def _upload_second_csv(client, project_id):
    files = {'file': ('second.csv', io.BytesIO(SECOND_UPLOAD_CSV), 'text/csv')}
    response = client.post(f'/api/projects/{project_id}/uploads', files=files, data={'kind': 'composite_report'})
    assert response.status_code == 201
    return response.json()


def test_soe_upload_id_scopes_to_that_upload_only(client, project):
    first_upload = _upload_soe_csv(client, project['projectId'])
    _upload_second_csv(client, project['projectId'])

    response = client.get(
        f"/api/projects/{project['projectId']}/soe", params={'upload_id': first_upload['uploadId']}
    )
    assert response.status_code == 200
    body = response.json()
    assert body['totalSpend'] == pytest.approx(600_000)  # only the first upload's rows
    by_brand = {row['brand']: row for row in body['brands']}
    assert set(by_brand) == {'Brand A', 'Brand B'}  # Brand C from the second upload is excluded


def test_soe_omitting_upload_id_pools_every_upload(client, project):
    first_upload = _upload_soe_csv(client, project['projectId'])
    second_upload = _upload_second_csv(client, project['projectId'])

    response = client.get(f"/api/projects/{project['projectId']}/soe")
    assert response.status_code == 200
    body = response.json()
    assert body['totalSpend'] == pytest.approx(720_000)  # 600k + 120k (2 spots x 60000)
    by_brand = {row['brand']: row for row in body['brands']}
    assert set(by_brand) == {'Brand A', 'Brand B', 'Brand C'}
    assert first_upload['uploadId'] != second_upload['uploadId']


def test_soe_filters_upload_id_scopes_facets_to_that_upload_only(client, project):
    first_upload = _upload_soe_csv(client, project['projectId'])
    _upload_second_csv(client, project['projectId'])

    response = client.get(
        f"/api/projects/{project['projectId']}/soe/filters", params={'upload_id': first_upload['uploadId']}
    )
    assert response.status_code == 200
    body = response.json()
    assert body['regions'] == ['Abuja', 'Kano', 'Lagos']  # Rivers (second upload) excluded
    assert 'Wazobia' not in body['stations']
