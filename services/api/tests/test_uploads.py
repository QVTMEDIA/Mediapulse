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
    return client.post('/api/projects', json={'projectName': 'Seasoning Q1'}).json()


@pytest.fixture
def brand(client, project):
    return client.post(f"/api/projects/{project['projectId']}/brands", json={'name': 'Brand A'}).json()


SAMPLE_CSV = (
    b'Channel,Programme,Day,Spots\n'
    b'TVC,Prime Time,Monday,3\n'
    b'AIT,News,Tuesday,2\n'
)


def _post_upload(client, project_id, brand_id, content=SAMPLE_CSV, filename='report.csv', **form):
    files = {'file': (filename, io.BytesIO(content), 'text/csv')}
    data = {'brand_id': brand_id, **form}
    return client.post(f'/api/projects/{project_id}/uploads', files=files, data=data)


def test_upload_brand_report_creates_media_activity(client, project, brand):
    response = _post_upload(client, project['projectId'], brand['brandId'])
    assert response.status_code == 201
    body = response.json()
    assert body['fileName'] == 'report.csv'
    assert body['kind'] == 'brand_report'
    assert body['mappedRows'] == 2
    assert body['issueRows'] == 0
    assert body['brandId'] == brand['brandId']

    activity = client.get(f"/api/projects/{project['projectId']}/media-activity").json()
    assert len(activity) == 2
    stations = sorted(row['station'] for row in activity)
    assert stations == ['AIT', 'TVC']
    assert all(row['medium'] == 'TV' for row in activity)
    assert all(row['brandId'] == brand['brandId'] for row in activity)
    assert all(row['sourceFile'] == 'report.csv' for row in activity)


def test_upload_with_no_cost_column_leaves_cost_null(client, project, brand):
    # null, not 0 — "no spend column was ever mapped" and "confirmed zero
    # spend" are different things, same convention as unmatched GRP rows.
    _post_upload(client, project['projectId'], brand['brandId'])
    activity = client.get(f"/api/projects/{project['projectId']}/media-activity").json()
    assert all(row['cost'] is None for row in activity)


def test_upload_resolves_cost_from_a_direct_cost_column(client, project, brand):
    csv = (
        b'Channel,Programme,Day,Spots,Cost\n'
        b'TVC,Prime Time,Monday,3,15000\n'
        b'AIT,News,Tuesday,2,10000\n'
    )
    _post_upload(client, project['projectId'], brand['brandId'], content=csv)
    activity = client.get(f"/api/projects/{project['projectId']}/media-activity").json()
    by_station = {row['station']: row for row in activity}
    assert by_station['TVC']['cost'] == pytest.approx(15000)
    assert by_station['AIT']['cost'] == pytest.approx(10000)


def test_upload_resolves_cost_from_spots_times_rate_when_no_direct_cost(client, project, brand):
    csv = (
        b'Channel,Programme,Day,Spots,Rate\n'
        b'TVC,Prime Time,Monday,3,6200\n'
    )
    _post_upload(client, project['projectId'], brand['brandId'], content=csv)
    activity = client.get(f"/api/projects/{project['projectId']}/media-activity").json()
    assert activity[0]['cost'] == pytest.approx(3 * 6200)


def test_upload_appears_in_uploads_list(client, project, brand):
    _post_upload(client, project['projectId'], brand['brandId'])
    uploads = client.get(f"/api/projects/{project['projectId']}/uploads").json()
    assert len(uploads) == 1
    assert uploads[0]['fileName'] == 'report.csv'


def test_upload_respects_default_medium_override(client, project, brand):
    response = _post_upload(client, project['projectId'], brand['brandId'], default_medium='Radio')
    assert response.status_code == 201
    activity = client.get(f"/api/projects/{project['projectId']}/media-activity").json()
    assert all(row['medium'] == 'Radio' for row in activity)


def test_upload_rejects_missing_project(client, brand):
    response = _post_upload(client, 'does-not-exist', brand['brandId'])
    assert response.status_code == 404


def test_upload_rejects_missing_brand(client, project):
    response = _post_upload(client, project['projectId'], 'does-not-exist')
    assert response.status_code == 404


def test_upload_rejects_unsupported_kind(client, project, brand):
    response = _post_upload(client, project['projectId'], brand['brandId'], kind='ratings')
    assert response.status_code == 422


def test_upload_rejects_blocked_xlsm_extension(client, project, brand):
    response = _post_upload(
        client, project['projectId'], brand['brandId'], content=b'not really excel', filename='report.xlsm'
    )
    assert response.status_code == 422
    assert 'xlsm' in response.json()['detail'].lower()


def test_upload_with_no_data_rows_is_not_an_error(client, project, brand):
    response = _post_upload(
        client, project['projectId'], brand['brandId'],
        content=b'Channel,Programme,Day,Spots\n', filename='empty.csv',
    )
    assert response.status_code == 201
    assert response.json()['mappedRows'] == 0


def test_upload_flags_rows_missing_required_fields_as_issues(client, project, brand):
    content = (
        b'Channel,Programme,Day,Spots\n'
        b'TVC,Prime Time,Monday,3\n'
        b',News,Tuesday,2\n'  # missing Channel -> issue row, excluded from media_activity
    )
    response = _post_upload(client, project['projectId'], brand['brandId'], content=content, filename='partial.csv')
    assert response.status_code == 201
    body = response.json()
    assert body['mappedRows'] == 1
    assert body['issueRows'] == 1


def test_media_activity_rejects_missing_project(client):
    response = client.get('/api/projects/does-not-exist/media-activity')
    assert response.status_code == 404


def test_uploads_list_rejects_missing_project(client):
    response = client.get('/api/projects/does-not-exist/uploads')
    assert response.status_code == 404


COMPOSITE_CSV = (
    # build_composite_report requires a Rating or GRP column to consider a
    # row valid at all — composite reports are meant to carry a vendor's own
    # pre-computed values, unlike brand_report's raw spot lists. This API
    # doesn't store that column (see parse_composite_report's docstring),
    # but it still has to be present for grp_calculator's own validation.
    b'Brand,Channel,Programme,Day,Spots,Rating\n'
    b'Brand A,TVC,Prime Time,Monday,3,1.2\n'
    b'Brand B,AIT,News,Tuesday,2,2.5\n'
    b'Brand A,Channels,Business Hour,Wednesday,1,0.8\n'
)


def _post_composite_upload(client, project_id, content=COMPOSITE_CSV, filename='composite.csv', **form):
    files = {'file': (filename, io.BytesIO(content), 'text/csv')}
    data = {'kind': 'composite_report', **form}
    return client.post(f'/api/projects/{project_id}/uploads', files=files, data=data)


def test_composite_upload_does_not_require_brand_id(client, project):
    response = _post_composite_upload(client, project['projectId'])
    assert response.status_code == 201
    body = response.json()
    assert body['kind'] == 'composite_report'
    assert body['brandId'] is None  # spans more than one brand — see repositories/uploads.py
    assert body['mappedRows'] == 3


def test_composite_upload_creates_one_brand_per_distinct_name(client, project):
    _post_composite_upload(client, project['projectId'])
    brands = client.get(f"/api/projects/{project['projectId']}/brands").json()
    assert sorted(b['name'] for b in brands) == ['Brand A', 'Brand B']


def test_composite_upload_reuses_an_existing_brand_by_name(client, project):
    existing = client.post(f"/api/projects/{project['projectId']}/brands", json={'name': 'Brand A'}).json()
    _post_composite_upload(client, project['projectId'])

    brands = client.get(f"/api/projects/{project['projectId']}/brands").json()
    assert sorted(b['name'] for b in brands) == ['Brand A', 'Brand B']  # not "Brand A" twice

    activity = client.get(f"/api/projects/{project['projectId']}/media-activity").json()
    brand_a_rows = [row for row in activity if row['station'] in ('TVC', 'Channels')]
    assert all(row['brandId'] == existing['brandId'] for row in brand_a_rows)


def test_composite_upload_tags_each_row_with_its_own_brand(client, project):
    _post_composite_upload(client, project['projectId'])
    activity = client.get(f"/api/projects/{project['projectId']}/media-activity").json()
    by_station = {row['station']: row for row in activity}

    brands = {b['name']: b['brandId'] for b in client.get(f"/api/projects/{project['projectId']}/brands").json()}
    assert by_station['TVC']['brandId'] == brands['Brand A']
    assert by_station['Channels']['brandId'] == brands['Brand A']
    assert by_station['AIT']['brandId'] == brands['Brand B']


def test_composite_upload_ignores_brand_id_form_field(client, project, brand):
    # brand_id is meaningless for a multi-brand file — make sure passing one
    # doesn't get silently applied to every row.
    response = _post_composite_upload(client, project['projectId'], brand_id=brand['brandId'])
    assert response.status_code == 201
    activity = client.get(f"/api/projects/{project['projectId']}/media-activity").json()
    assert not all(row['brandId'] == brand['brandId'] for row in activity)
