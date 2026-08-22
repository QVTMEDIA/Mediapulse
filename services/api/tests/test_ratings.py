import io

import pytest
from fastapi.testclient import TestClient

from app.auth import get_current_user
from app.main import app
from app.repositories.mapping_templates import InMemoryMappingTemplatesRepository, get_mapping_templates_repository
from app.repositories.projects import InMemoryProjectsRepository, get_projects_repository
from app.repositories.ratings import InMemoryRatingsRepository, get_ratings_repository

from ._auth_helpers import make_test_user


@pytest.fixture
def client():
    projects_repo = InMemoryProjectsRepository()
    ratings_repo = InMemoryRatingsRepository()
    mapping_templates_repo = InMemoryMappingTemplatesRepository()
    app.dependency_overrides[get_projects_repository] = lambda: projects_repo
    app.dependency_overrides[get_ratings_repository] = lambda: ratings_repo
    app.dependency_overrides[get_mapping_templates_repository] = lambda: mapping_templates_repo
    app.dependency_overrides[get_current_user] = lambda: make_test_user()
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


SAMPLE_ROWS = [
    {'medium': 'TV', 'station': 'TVC', 'day': 'Monday', 'programme': 'Prime Time', 'timeBand': '19:00-20:00', 'rating': 1.2},
    {'medium': 'TV', 'station': 'AIT', 'day': 'Tue', 'programme': 'News', 'timeBand': '20:00-21:00', 'rating': 2.1},
    # duplicate of the first row's key
    {'medium': 'tv', 'station': ' TVC ', 'day': 'mon', 'programme': 'Prime  Time', 'timeBand': '19:00-20:00', 'rating': 1.4},
    # invalid: missing station
    {'medium': 'Radio', 'station': '', 'day': 'Wed', 'programme': 'Drive Time', 'rating': 3.0},
]


def test_create_dataset_computes_row_count_invalid_and_duplicate_counts(client):
    response = client.post(
        '/api/ratings-datasets',
        json={'provider': 'Agency A', 'period': 'Q1 2026', 'market': 'Nigeria', 'mediaTypes': ['TV', 'Radio'], 'rows': SAMPLE_ROWS},
    )
    assert response.status_code == 201
    body = response.json()
    assert body['rows'] == 4
    assert body['invalidRows'] == 1
    assert body['duplicateKeys'] == 1  # the TVC/Mon/Prime Time key appears twice
    assert body['status'] == 'Needs Review'
    assert 'ratingsDatasetId' in body


def test_create_dataset_is_ready_when_no_invalid_rows(client):
    response = client.post(
        '/api/ratings-datasets',
        json={'provider': 'Agency A', 'rows': SAMPLE_ROWS[:2]},
    )
    assert response.json()['status'] == 'Ready'
    assert response.json()['invalidRows'] == 0
    assert response.json()['duplicateKeys'] == 0


def test_create_dataset_rejects_unknown_media_type(client):
    response = client.post('/api/ratings-datasets', json={'mediaTypes': ['Digital']})
    assert response.status_code == 422


def test_list_ratings_datasets_filters_by_search(client):
    client.post('/api/ratings-datasets', json={'provider': 'Nielsen', 'period': 'Q1 2026'})
    client.post('/api/ratings-datasets', json={'provider': 'GeoPoll', 'period': 'Q2 2026'})

    response = client.get('/api/ratings-datasets', params={'search': 'nielsen'})
    providers = [d['provider'] for d in response.json()]
    assert providers == ['Nielsen']


def test_list_rows_for_dataset(client):
    created = client.post('/api/ratings-datasets', json={'provider': 'Agency A', 'rows': SAMPLE_ROWS[:2]}).json()
    response = client.get(f"/api/ratings-datasets/{created['ratingsDatasetId']}/rows")
    assert response.status_code == 200
    rows = response.json()
    assert len(rows) == 2
    assert rows[0]['station'] == 'TVC'


def test_list_rows_for_missing_dataset_returns_404(client):
    response = client.get('/api/ratings-datasets/does-not-exist/rows')
    assert response.status_code == 404


def test_attach_dataset_to_project_and_list_it(client):
    project = client.post('/api/projects', json={'projectName': 'Seasoning Q1'}).json()
    dataset = client.post('/api/ratings-datasets', json={'provider': 'Nielsen'}).json()

    attach = client.post(
        f"/api/projects/{project['projectId']}/ratings-datasets/{dataset['ratingsDatasetId']}/attach"
    )
    assert attach.status_code == 204

    listed = client.get(f"/api/projects/{project['projectId']}/ratings-datasets")
    assert listed.status_code == 200
    assert [d['ratingsDatasetId'] for d in listed.json()] == [dataset['ratingsDatasetId']]


def test_attach_dataset_to_missing_project_returns_404(client):
    dataset = client.post('/api/ratings-datasets', json={'provider': 'Nielsen'}).json()
    response = client.post(f"/api/projects/does-not-exist/ratings-datasets/{dataset['ratingsDatasetId']}/attach")
    assert response.status_code == 404


def test_attach_missing_dataset_returns_404(client):
    project = client.post('/api/projects', json={'projectName': 'Seasoning Q1'}).json()
    response = client.post(f"/api/projects/{project['projectId']}/ratings-datasets/does-not-exist/attach")
    assert response.status_code == 404


def test_project_datasets_list_is_empty_when_nothing_attached(client):
    project = client.post('/api/projects', json={'projectName': 'Seasoning Q1'}).json()
    response = client.get(f"/api/projects/{project['projectId']}/ratings-datasets")
    assert response.json() == []


RATINGS_CSV = (
    b'Channel,Day,Programme,Rating\n'
    b'TVC,Monday,Prime Time,1.2\n'
    b'AIT,Tuesday,News,2.5\n'
)


def _upload_ratings(client, content=RATINGS_CSV, filename='ratings.csv', **form):
    files = {'file': (filename, io.BytesIO(content), 'text/csv')}
    return client.post('/api/ratings-datasets/upload', files=files, data=form)


def test_upload_ratings_file_with_only_a_timeband_column_still_maps(client):
    # Regression test for a real incident: a real radio audience-reach file
    # (Channel/WD/Timeband/Rch %, no Programme column at all — a normal
    # shape for this kind of source, not broken data) came back "0 rows,
    # every row invalid" because 'programme' (required) had nowhere to
    # fall back to once 'time_band' became a separate field. See
    # grp_calculator.resolve_effective_programme.
    content = (
        b'Channel,WD,Timeband,Rch %\n'
        b'Abuja Cool FM,Sun,09:30-09:45,0.16\n'
        b'Edo Speed FM,Fri,07:15-07:30,0.92\n'
    )
    response = _upload_ratings(client, content=content, filename='reach.csv', default_medium='Radio')
    assert response.status_code == 201
    body = response.json()
    assert body['rows'] == 2
    assert body['invalidRows'] == 0
    assert body['status'] == 'Ready'
    assert body.get('issues') in (None, [])

    rows = client.get(f"/api/ratings-datasets/{body['ratingsDatasetId']}/rows").json()
    assert len(rows) == 2
    assert all(row['medium'] == 'Radio' for row in rows)
    assert sorted(row['rating'] for row in rows) == [0.16, 0.92]


def test_upload_ratings_file_parses_real_spreadsheet(client):
    response = _upload_ratings(client, provider='Nielsen', period='Q1 2026')
    assert response.status_code == 201
    body = response.json()
    assert body['provider'] == 'Nielsen'
    assert body['rows'] == 2
    assert body['invalidRows'] == 0
    assert body['status'] == 'Ready'

    rows = client.get(f"/api/ratings-datasets/{body['ratingsDatasetId']}/rows").json()
    stations = sorted(row['station'] for row in rows)
    assert stations == ['AIT', 'TVC']
    assert all(row['medium'] == 'TV' for row in rows)


def test_upload_ratings_file_respects_default_medium(client):
    response = _upload_ratings(client, default_medium='Radio')
    assert response.status_code == 201
    dataset_id = response.json()['ratingsDatasetId']
    rows = client.get(f"/api/ratings-datasets/{dataset_id}/rows").json()
    assert all(row['medium'] == 'Radio' for row in rows)


def test_upload_ratings_file_drops_out_of_range_rating_and_flags_it(client):
    content = (
        b'Channel,Day,Programme,Rating\n'
        b'TVC,Monday,Prime Time,1.2\n'
        b'AIT,Tuesday,News,150\n'  # out of the 0-100 range grp_calculator enforces
    )
    response = _upload_ratings(client, content=content, filename='partial.csv')
    assert response.status_code == 201
    body = response.json()
    assert body['rows'] == 2  # total rows seen in the file, including the dropped one
    assert body['invalidRows'] == 1
    assert body['status'] == 'Needs Review'

    # Not just a bare count — the actual dropped row, with why, is on the
    # upload response too (this is the only time it's ever available: the
    # row itself is never stored, so there's no other way to see it later).
    assert len(body['issues']) == 1
    assert body['issues'][0]['station'] == 'AIT'
    assert body['issues'][0]['reason'] == 'Invalid or out-of-range rating'
    assert body['issues'][0]['rating'] == 150

    rows = client.get(f"/api/ratings-datasets/{body['ratingsDatasetId']}/rows").json()
    assert len(rows) == 1  # the invalid row was never stored
    assert rows[0]['station'] == 'TVC'


def test_upload_ratings_file_rejecting_every_row_still_explains_why(client):
    # Regression test for a real incident: a file where every row failed to
    # parse a Rating value at all (e.g. the Rating column wasn't detected,
    # or every cell was blank/non-numeric) used to come back as "0 rows,
    # invalidRows: N" with no way to tell why short of inspecting the
    # source file by hand.
    content = (
        b'Channel,Day,Programme,Score\n'  # 'Score', not 'Rating' -> Rating column never detected
        b'TVC,Monday,Prime Time,1.2\n'
        b'AIT,Tuesday,News,2.5\n'
    )
    response = _upload_ratings(client, content=content, filename='wrong_headers.csv')
    assert response.status_code == 201
    body = response.json()
    assert body['rows'] == 2
    assert body['invalidRows'] == 2
    assert len(body['issues']) == 2
    assert all(issue['reason'] == 'Invalid or out-of-range rating' for issue in body['issues'])
    assert all(issue['rating'] is None for issue in body['issues'])  # confirms it's a missing value, not just out of range
    # Match fields (Channel/Day/Programme) still came through fine — proves
    # the failure is specifically the Rating column, not the whole mapping.
    assert {issue['station'] for issue in body['issues']} == {'TVC', 'AIT'}

    rows = client.get(f"/api/ratings-datasets/{body['ratingsDatasetId']}/rows").json()
    assert rows == []


def test_upload_ratings_file_missing_field_reason_differs_from_bad_rating(client):
    content = (
        b'Channel,Day,Programme,Rating\n'
        b'TVC,Monday,Prime Time,1.2\n'
        b',Tuesday,News,2.5\n'  # blank Channel -> missing match field, not a rating problem
    )
    response = _upload_ratings(client, content=content, filename='blank_channel.csv')
    assert response.status_code == 201
    body = response.json()
    assert len(body['issues']) == 1
    assert body['issues'][0]['reason'] == 'Missing rating match field'
    assert body['issues'][0]['rating'] == 2.5  # the rating itself was fine — it's the match field that's missing


def test_upload_ratings_file_rejects_unknown_media_type(client):
    response = _upload_ratings(client, media_types='Digital')
    assert response.status_code == 422


def test_upload_ratings_file_rejects_blocked_xlsm_extension(client):
    response = _upload_ratings(client, content=b'not really excel', filename='ratings.xlsm')
    assert response.status_code == 422
    assert 'xlsm' in response.json()['detail'].lower()


def test_upload_ratings_file_accepts_media_types_list(client):
    response = _upload_ratings(client, media_types='TV,Radio')
    assert response.status_code == 201
    assert response.json()['mediaTypes'] == ['TV', 'Radio']
