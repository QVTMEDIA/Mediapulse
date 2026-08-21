import io

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
    # See services/api/README.md's "Test fixture pitfall" note — a
    # parameterized lambda here gets misread by FastAPI as a query param.
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
    app.dependency_overrides[get_current_user] = _returning(make_test_user())
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


@pytest.fixture
def project(client):
    return client.post('/api/projects', json={'projectName': 'Seasoning Q1'}).json()


def _brand(client, project_id, name):
    return client.post(f'/api/projects/{project_id}/brands', json={'name': name}).json()


def _upload(client, project_id, brand_id, csv_bytes, filename='report.csv'):
    files = {'file': (filename, io.BytesIO(csv_bytes), 'text/csv')}
    response = client.post(f'/api/projects/{project_id}/uploads', files=files, data={'brand_id': brand_id})
    assert response.status_code == 201, response.text
    return response.json()


def _attach_ratings(client, project_id, rows):
    dataset = client.post('/api/ratings-datasets', json={'provider': 'Nielsen', 'rows': rows}).json()
    client.post(f"/api/projects/{project_id}/ratings-datasets/{dataset['ratingsDatasetId']}/attach")
    return dataset


BRAND_A_CSV = (
    b'Channel,Programme,Day,Spots\n'
    b'TVC,Prime Time,Monday,3\n'
    b'AIT,News,Tuesday,2\n'
)

BRAND_A_RATINGS = [
    {'medium': 'TV', 'station': 'TVC', 'day': 'Monday', 'programme': 'Prime Time', 'rating': 1.2},
    {'medium': 'TV', 'station': 'AIT', 'day': 'Tuesday', 'programme': 'News', 'rating': 2.5},
]


def test_calculate_computes_grp_and_run_summary(client, project):
    brand = _brand(client, project['projectId'], 'Brand A')
    _upload(client, project['projectId'], brand['brandId'], BRAND_A_CSV)
    _attach_ratings(client, project['projectId'], BRAND_A_RATINGS)

    response = client.post(f"/api/projects/{project['projectId']}/calculate")
    assert response.status_code == 201
    run = response.json()
    assert run['matchedRows'] == 2
    assert run['unmatchedRows'] == 0
    assert run['totalBrands'] == 1
    assert run['totalSpots'] == 5
    assert run['totalGrps'] == pytest.approx(3 * 1.2 + 2 * 2.5)  # 8.6


def test_calculate_computes_matches_implicitly_without_prior_get(client, project):
    # calling /calculate without ever calling GET /matches first must still work
    brand = _brand(client, project['projectId'], 'Brand A')
    _upload(client, project['projectId'], brand['brandId'], BRAND_A_CSV)
    _attach_ratings(client, project['projectId'], BRAND_A_RATINGS)

    response = client.post(f"/api/projects/{project['projectId']}/calculate")
    assert response.status_code == 201
    assert response.json()['matchedRows'] == 2


def test_calculate_with_no_ratings_leaves_everything_unmatched(client, project):
    brand = _brand(client, project['projectId'], 'Brand A')
    _upload(client, project['projectId'], brand['brandId'], BRAND_A_CSV)

    response = client.post(f"/api/projects/{project['projectId']}/calculate")
    assert response.status_code == 201
    run = response.json()
    assert run['matchedRows'] == 0
    assert run['unmatchedRows'] == 2
    assert run['totalGrps'] == 0
    assert run['totalBrands'] == 1  # the brand still shows up with zero GRPs, not omitted


def test_brand_shares_split_correctly_across_two_brands(client, project):
    brand_a = _brand(client, project['projectId'], 'Brand A')
    brand_b = _brand(client, project['projectId'], 'Brand B')
    _upload(client, project['projectId'], brand_a['brandId'], BRAND_A_CSV)
    _upload(
        client, project['projectId'], brand_b['brandId'],
        b'Channel,Programme,Day,Spots\nChannels,Business Hour,Wednesday,4\n', filename='brand_b.csv',
    )
    _attach_ratings(client, project['projectId'], BRAND_A_RATINGS + [
        {'medium': 'TV', 'station': 'Channels', 'day': 'Wednesday', 'programme': 'Business Hour', 'rating': 3.0},
    ])

    run = client.post(f"/api/projects/{project['projectId']}/calculate").json()
    shares = client.get(f"/api/projects/{project['projectId']}/runs/{run['runId']}/brand-shares").json()
    assert len(shares) == 2

    by_name = {s['brand']: s for s in shares}
    assert by_name['Brand A']['totalGrps'] == pytest.approx(8.6)
    assert by_name['Brand B']['totalGrps'] == pytest.approx(12.0)  # 4 spots * 3.0
    assert by_name['Brand A']['sov'] + by_name['Brand B']['sov'] == pytest.approx(100.0)
    assert by_name['Brand A']['tvGrps'] == pytest.approx(8.6)
    assert by_name['Brand A']['radioGrps'] == pytest.approx(0.0)
    assert by_name['Brand A']['avgRating'] == pytest.approx((1.2 + 2.5) / 2)


BRAND_A_CSV_WITH_COST = (
    b'Channel,Programme,Day,Spots,Cost\n'
    b'TVC,Prime Time,Monday,3,15000\n'
    b'AIT,News,Tuesday,2,10000\n'
)


def test_run_and_brand_shares_include_spend_and_soe(client, project):
    brand_a = _brand(client, project['projectId'], 'Brand A')
    brand_b = _brand(client, project['projectId'], 'Brand B')
    _upload(client, project['projectId'], brand_a['brandId'], BRAND_A_CSV_WITH_COST)
    _upload(
        client, project['projectId'], brand_b['brandId'],
        b'Channel,Programme,Day,Spots,Cost\nChannels,Business Hour,Wednesday,4,15000\n', filename='brand_b.csv',
    )
    _attach_ratings(client, project['projectId'], BRAND_A_RATINGS + [
        {'medium': 'TV', 'station': 'Channels', 'day': 'Wednesday', 'programme': 'Business Hour', 'rating': 3.0},
    ])

    run = client.post(f"/api/projects/{project['projectId']}/calculate").json()
    assert run['totalSpend'] == pytest.approx(40000)  # 15000 + 10000 + 15000

    shares = client.get(f"/api/projects/{project['projectId']}/runs/{run['runId']}/brand-shares").json()
    by_name = {s['brand']: s for s in shares}
    assert by_name['Brand A']['totalSpend'] == pytest.approx(25000)
    assert by_name['Brand B']['totalSpend'] == pytest.approx(15000)
    assert by_name['Brand A']['soe'] == pytest.approx(25000 / 40000 * 100)
    assert by_name['Brand B']['soe'] == pytest.approx(15000 / 40000 * 100)
    assert by_name['Brand A']['soe'] + by_name['Brand B']['soe'] == pytest.approx(100.0)


def test_spend_accumulates_for_unmatched_rows_too(client, project):
    # SOE is spend-based, not rating-based — a row with no rating match
    # still spent real money and must still count toward SOE, unlike GRP/
    # SOV which only exist for matched rows. No ratings are attached here
    # at all, so every row is unmatched, yet spend/SOE should still reflect
    # the uploaded cost in full.
    brand = _brand(client, project['projectId'], 'Brand A')
    _upload(client, project['projectId'], brand['brandId'], BRAND_A_CSV_WITH_COST)

    run = client.post(f"/api/projects/{project['projectId']}/calculate").json()
    assert run['matchedRows'] == 0
    assert run['unmatchedRows'] == 2
    assert run['totalGrps'] == 0
    assert run['totalSpend'] == pytest.approx(25000)

    shares = client.get(f"/api/projects/{project['projectId']}/runs/{run['runId']}/brand-shares").json()
    assert shares[0]['totalSpend'] == pytest.approx(25000)
    assert shares[0]['soe'] == pytest.approx(100.0)  # only brand in the project, so it's 100% of category spend
    assert shares[0]['sov'] == pytest.approx(0.0)  # no GRPs at all, so SOV is 0 — spend and GRP tell different stories


def test_spend_and_soe_are_zero_when_no_cost_column_mapped(client, project):
    brand = _brand(client, project['projectId'], 'Brand A')
    _upload(client, project['projectId'], brand['brandId'], BRAND_A_CSV)  # no Cost/Rate column
    _attach_ratings(client, project['projectId'], BRAND_A_RATINGS)

    run = client.post(f"/api/projects/{project['projectId']}/calculate").json()
    assert run['totalSpend'] == 0

    shares = client.get(f"/api/projects/{project['projectId']}/runs/{run['runId']}/brand-shares").json()
    assert shares[0]['totalSpend'] == 0
    assert shares[0]['soe'] == 0


def test_runs_list_and_latest(client, project):
    brand = _brand(client, project['projectId'], 'Brand A')
    _upload(client, project['projectId'], brand['brandId'], BRAND_A_CSV)
    _attach_ratings(client, project['projectId'], BRAND_A_RATINGS)

    first = client.post(f"/api/projects/{project['projectId']}/calculate").json()
    second = client.post(f"/api/projects/{project['projectId']}/calculate").json()

    runs = client.get(f"/api/projects/{project['projectId']}/runs").json()
    assert {r['runId'] for r in runs} == {first['runId'], second['runId']}

    latest = client.get(f"/api/projects/{project['projectId']}/runs/latest")
    assert latest.status_code == 200
    assert latest.json()['runId'] == second['runId']


def test_runs_latest_404_when_none_yet(client, project):
    response = client.get(f"/api/projects/{project['projectId']}/runs/latest")
    assert response.status_code == 404


def test_calculate_rejects_missing_project(client):
    response = client.post('/api/projects/does-not-exist/calculate')
    assert response.status_code == 404


def test_runs_list_rejects_missing_project(client):
    response = client.get('/api/projects/does-not-exist/runs')
    assert response.status_code == 404


def test_brand_shares_rejects_missing_run(client, project):
    response = client.get(f"/api/projects/{project['projectId']}/runs/does-not-exist/brand-shares")
    assert response.status_code == 404


def test_brand_shares_are_scoped_per_project(client, project):
    brand = _brand(client, project['projectId'], 'Brand A')
    _upload(client, project['projectId'], brand['brandId'], BRAND_A_CSV)
    _attach_ratings(client, project['projectId'], BRAND_A_RATINGS)
    run = client.post(f"/api/projects/{project['projectId']}/calculate").json()

    other_project = client.post('/api/projects', json={'projectName': 'Malaria Category'}).json()
    response = client.get(f"/api/projects/{other_project['projectId']}/runs/{run['runId']}/brand-shares")
    assert response.status_code == 404


def test_calculations_list_every_matched_row_with_audit_fields(client, project):
    brand = _brand(client, project['projectId'], 'Brand A')
    _upload(client, project['projectId'], brand['brandId'], BRAND_A_CSV)
    _attach_ratings(client, project['projectId'], BRAND_A_RATINGS)
    run = client.post(f"/api/projects/{project['projectId']}/calculate").json()

    rows = client.get(f"/api/projects/{project['projectId']}/runs/{run['runId']}/calculations").json()
    assert len(rows) == 2  # matched rows only — see app/calculations.py

    by_station = {row['station']: row for row in rows}
    assert by_station['TVC']['rating'] == pytest.approx(1.2)
    assert by_station['TVC']['spots'] == 3
    assert by_station['TVC']['grp'] == pytest.approx(3.6)
    assert by_station['TVC']['brand'] == 'Brand A'
    assert by_station['TVC']['day'] == 'Monday'
    assert by_station['TVC']['programme'] == 'Prime Time'
    assert 'grpCalculationId' in by_station['TVC']
    assert 'calculatedAt' in by_station['TVC']
    # sorted GRP descending, per list_calculations
    assert rows[0]['grp'] >= rows[1]['grp']


def test_calculations_excludes_unmatched_rows(client, project):
    brand = _brand(client, project['projectId'], 'Brand A')
    _upload(client, project['projectId'], brand['brandId'], BRAND_A_CSV)
    # no ratings attached -> nothing matches
    run = client.post(f"/api/projects/{project['projectId']}/calculate").json()

    rows = client.get(f"/api/projects/{project['projectId']}/runs/{run['runId']}/calculations").json()
    assert rows == []


def test_calculations_rejects_missing_run(client, project):
    response = client.get(f"/api/projects/{project['projectId']}/runs/does-not-exist/calculations")
    assert response.status_code == 404


def test_calculations_are_scoped_per_project(client, project):
    brand = _brand(client, project['projectId'], 'Brand A')
    _upload(client, project['projectId'], brand['brandId'], BRAND_A_CSV)
    _attach_ratings(client, project['projectId'], BRAND_A_RATINGS)
    run = client.post(f"/api/projects/{project['projectId']}/calculate").json()

    other_project = client.post('/api/projects', json={'projectName': 'Malaria Category'}).json()
    response = client.get(f"/api/projects/{other_project['projectId']}/runs/{run['runId']}/calculations")
    assert response.status_code == 404


def test_station_shares_split_by_brand_and_station(client, project):
    brand_a = _brand(client, project['projectId'], 'Brand A')
    _upload(client, project['projectId'], brand_a['brandId'], BRAND_A_CSV)
    _attach_ratings(client, project['projectId'], BRAND_A_RATINGS)
    run = client.post(f"/api/projects/{project['projectId']}/calculate").json()

    shares = client.get(f"/api/projects/{project['projectId']}/runs/{run['runId']}/stations").json()
    by_station = {s['station']: s for s in shares}
    assert by_station['TVC']['totalGrps'] == pytest.approx(3.6)  # 3 spots * 1.2
    assert by_station['TVC']['spots'] == 3
    assert by_station['AIT']['totalGrps'] == pytest.approx(5.0)  # 2 spots * 2.5
    assert all(s['brand'] == 'Brand A' for s in shares)
    # sorted GRP descending
    assert shares[0]['totalGrps'] >= shares[1]['totalGrps']


def test_station_shares_rejects_missing_run(client, project):
    response = client.get(f"/api/projects/{project['projectId']}/runs/does-not-exist/stations")
    assert response.status_code == 404


def test_programme_shares_split_by_brand_and_programme(client, project):
    brand_a = _brand(client, project['projectId'], 'Brand A')
    _upload(client, project['projectId'], brand_a['brandId'], BRAND_A_CSV)
    _attach_ratings(client, project['projectId'], BRAND_A_RATINGS)
    run = client.post(f"/api/projects/{project['projectId']}/calculate").json()

    shares = client.get(f"/api/projects/{project['projectId']}/runs/{run['runId']}/programmes").json()
    by_programme = {s['programme']: s for s in shares}
    assert by_programme['Prime Time']['totalGrps'] == pytest.approx(3.6)
    assert by_programme['News']['totalGrps'] == pytest.approx(5.0)


def test_programme_shares_rejects_missing_run(client, project):
    response = client.get(f"/api/projects/{project['projectId']}/runs/does-not-exist/programmes")
    assert response.status_code == 404


TREND_CSV = (
    b'Channel,Programme,Day,Spots,Date\n'
    b'TVC,Prime Time,Monday,3,2026-01-05\n'
    b'TVC,Prime Time,Monday,2,2026-01-12\n'
)

TREND_RATINGS = [
    {'medium': 'TV', 'station': 'TVC', 'day': 'Monday', 'programme': 'Prime Time', 'rating': 1.0},
]


def test_trend_groups_by_week_start(client, project):
    brand = _brand(client, project['projectId'], 'Brand A')
    _upload(client, project['projectId'], brand['brandId'], TREND_CSV)
    _attach_ratings(client, project['projectId'], TREND_RATINGS)
    run = client.post(f"/api/projects/{project['projectId']}/calculate").json()

    points = client.get(f"/api/projects/{project['projectId']}/runs/{run['runId']}/trend").json()
    assert len(points) == 2
    weeks = {p['weekStart']: p for p in points}
    assert weeks['2026-01-05']['totalGrps'] == pytest.approx(3.0)
    assert weeks['2026-01-05']['spots'] == 3
    assert weeks['2026-01-12']['totalGrps'] == pytest.approx(2.0)
    # sorted by week ascending
    assert points[0]['weekStart'] < points[1]['weekStart']


def test_trend_excludes_rows_with_no_date(client, project):
    brand = _brand(client, project['projectId'], 'Brand A')
    _upload(client, project['projectId'], brand['brandId'], BRAND_A_CSV)  # no Date column
    _attach_ratings(client, project['projectId'], BRAND_A_RATINGS)
    run = client.post(f"/api/projects/{project['projectId']}/calculate").json()

    points = client.get(f"/api/projects/{project['projectId']}/runs/{run['runId']}/trend").json()
    assert points == []


def test_trend_rejects_missing_run(client, project):
    response = client.get(f"/api/projects/{project['projectId']}/runs/does-not-exist/trend")
    assert response.status_code == 404
