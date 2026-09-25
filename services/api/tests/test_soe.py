import io

import pytest
from fastapi.testclient import TestClient

from app.auth import get_current_user
from app.main import app
from app.repositories.soe import InMemorySoeRepository, get_soe_repository

from ._auth_helpers import make_test_user


@pytest.fixture
def client():
    soe_repo = InMemorySoeRepository()
    app.dependency_overrides[get_soe_repository] = lambda: soe_repo
    app.dependency_overrides[get_current_user] = lambda: make_test_user()
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


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


def _upload_soe_csv(client):
    files = {'file': ('spend.csv', io.BytesIO(SOE_CSV), 'text/csv')}
    response = client.post('/api/soe/uploads', files=files)
    assert response.status_code == 201
    return response.json()


def test_soe_upload_is_never_attached_to_any_project(client):
    # No projectId/brandId anywhere in the response -- this data has no
    # project at all, not even one it's excluded-from-matching-but-still-
    # attached-to.
    upload = _upload_soe_csv(client)
    assert 'projectId' not in upload
    assert 'brandId' not in upload
    assert upload['fileName'] == 'spend.csv'
    assert upload['mappedRows'] == 4
    assert upload['issueRows'] == 0


def test_soe_uploads_are_listed_without_any_project_context(client):
    _upload_soe_csv(client)
    response = client.get('/api/soe/uploads')
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 1
    assert body[0]['fileName'] == 'spend.csv'


def test_soe_filters_returns_distinct_values_present(client):
    _upload_soe_csv(client)
    response = client.get('/api/soe/filters')
    assert response.status_code == 200
    body = response.json()
    assert body['mediums'] == ['Radio', 'TV']
    assert body['stations'] == ['Channels', 'Cool FM', 'NTA']
    assert body['regions'] == ['Abuja', 'Kano', 'Lagos']
    assert body['days'] == ['Monday', 'Tuesday', 'Wednesday']


def test_soe_unfiltered_computes_share_of_total_category_spend(client):
    _upload_soe_csv(client)
    response = client.get('/api/soe')
    assert response.status_code == 200
    body = response.json()
    assert body['totalSpend'] == pytest.approx(600_000)
    by_brand = {row['brand']: row for row in body['brands']}
    assert 'brandId' not in body['brands'][0]
    assert by_brand['Brand A']['spend'] == pytest.approx(350_000)
    assert by_brand['Brand A']['soe'] == pytest.approx(58.3333, rel=1e-3)
    assert by_brand['Brand B']['spend'] == pytest.approx(250_000)
    assert by_brand['Brand B']['soe'] == pytest.approx(41.6667, rel=1e-3)


def test_soe_medium_filter_recomputes_share_within_that_medium_only(client):
    _upload_soe_csv(client)
    response = client.get('/api/soe', params={'medium': 'TV'})
    assert response.status_code == 200
    body = response.json()
    assert body['totalSpend'] == pytest.approx(450_000)  # Brand A's radio spend excluded
    by_brand = {row['brand']: row for row in body['brands']}
    assert by_brand['Brand A']['spend'] == pytest.approx(200_000)
    assert by_brand['Brand B']['spend'] == pytest.approx(250_000)


def test_soe_region_filter_isolates_that_region(client):
    _upload_soe_csv(client)
    response = client.get('/api/soe', params={'region': 'Lagos'})
    assert response.status_code == 200
    body = response.json()
    assert body['totalSpend'] == pytest.approx(290_000)
    by_brand = {row['brand']: row for row in body['brands']}
    assert set(by_brand) == {'Brand A', 'Brand B'}


def test_soe_combined_filters_and_together(client):
    _upload_soe_csv(client)
    # Kano only has Brand B's row -- Brand A should disappear entirely.
    response = client.get('/api/soe', params={'medium': 'TV', 'region': 'Kano'})
    assert response.status_code == 200
    body = response.json()
    by_brand = {row['brand']: row for row in body['brands']}
    assert set(by_brand) == {'Brand B'}
    assert by_brand['Brand B']['soe'] == pytest.approx(100.0)


def test_soe_empty_returns_zero_with_no_error(client):
    response = client.get('/api/soe')
    assert response.status_code == 200
    body = response.json()
    assert body['totalSpend'] == 0
    assert body['brands'] == []


def test_soe_requires_authentication():
    with TestClient(app) as anon_client:
        response = anon_client.get('/api/soe')
        assert response.status_code == 401


def test_soe_upload_requires_authentication():
    with TestClient(app) as anon_client:
        files = {'file': ('spend.csv', io.BytesIO(SOE_CSV), 'text/csv')}
        response = anon_client.post('/api/soe/uploads', files=files)
        assert response.status_code == 401


# A second, unrelated upload -- Brand C only, on a station/region/day the
# first upload never touches. Proves upload_id scoping actually isolates
# one file's rows rather than still pooling every upload ever made.
SECOND_UPLOAD_CSV = (
    b'Brand,Medium,Station,Region,Day,Programme,Spots,Rate\n'
    b'Brand C,Radio,Wazobia,Rivers,Friday,Drive Time,2,60000\n'
)


def _upload_second_csv(client):
    files = {'file': ('second.csv', io.BytesIO(SECOND_UPLOAD_CSV), 'text/csv')}
    response = client.post('/api/soe/uploads', files=files)
    assert response.status_code == 201
    return response.json()


def test_soe_upload_id_scopes_to_that_upload_only(client):
    first_upload = _upload_soe_csv(client)
    _upload_second_csv(client)

    response = client.get('/api/soe', params={'upload_id': first_upload['uploadId']})
    assert response.status_code == 200
    body = response.json()
    assert body['totalSpend'] == pytest.approx(600_000)  # only the first upload's rows
    by_brand = {row['brand']: row for row in body['brands']}
    assert set(by_brand) == {'Brand A', 'Brand B'}  # Brand C from the second upload is excluded


def test_soe_omitting_upload_id_pools_every_upload(client):
    first_upload = _upload_soe_csv(client)
    second_upload = _upload_second_csv(client)

    response = client.get('/api/soe')
    assert response.status_code == 200
    body = response.json()
    assert body['totalSpend'] == pytest.approx(720_000)  # 600k + 120k (2 spots x 60000)
    by_brand = {row['brand']: row for row in body['brands']}
    assert set(by_brand) == {'Brand A', 'Brand B', 'Brand C'}
    assert first_upload['uploadId'] != second_upload['uploadId']


def test_soe_filters_upload_id_scopes_facets_to_that_upload_only(client):
    first_upload = _upload_soe_csv(client)
    _upload_second_csv(client)

    response = client.get('/api/soe/filters', params={'upload_id': first_upload['uploadId']})
    assert response.status_code == 200
    body = response.json()
    assert body['regions'] == ['Abuja', 'Kano', 'Lagos']  # Rivers (second upload) excluded
    assert 'Wazobia' not in body['stations']


def test_soe_delete_upload_removes_it_and_its_activity(client):
    upload = _upload_soe_csv(client)
    response = client.delete(f"/api/soe/uploads/{upload['uploadId']}")
    assert response.status_code == 204

    listed = client.get('/api/soe/uploads').json()
    assert listed == []
    soe = client.get('/api/soe').json()
    assert soe['totalSpend'] == 0


def test_soe_delete_rejects_missing_upload(client):
    response = client.delete('/api/soe/uploads/does-not-exist')
    assert response.status_code == 404
