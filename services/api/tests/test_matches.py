import io
import time

import pytest
from fastapi.testclient import TestClient

from app.auth import get_current_user
from app.main import app
from app.repositories.brands import InMemoryBrandsRepository, get_brands_repository
from app.repositories.mapping_templates import InMemoryMappingTemplatesRepository, get_mapping_templates_repository
from app.repositories.matches import InMemoryMatchesRepository, get_matches_repository
from app.repositories.projects import InMemoryProjectsRepository, get_projects_repository
from app.repositories.ratings import InMemoryRatingsRepository, get_ratings_repository
from app.repositories.uploads import InMemoryUploadsRepository, get_uploads_repository

from ._auth_helpers import make_test_user


def _returning(instance):
    # A plain `lambda instance=instance: instance` looks like it captures
    # correctly, but FastAPI inspects an override callable's OWN signature
    # and treats a bare (non-Depends) parameter as a query parameter of the
    # endpoint — so `instance` stops being "this closure's fixed value" and
    # becomes something FastAPI tries to resolve per-request, breaking
    # identity across calls. A proper zero-arg closure sidesteps that.
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


@pytest.fixture
def brand(client, project):
    return client.post(f"/api/projects/{project['projectId']}/brands", json={'name': 'Brand A'}).json()


# TVC/Monday/Prime Time -> exact match. AIT Lagos/Tuesday/News -> same medium+day
# as a rating on "AIT" (different station text) with an identical programme,
# so it should come back as a fuzzy 'suggested' match. XYZ FM/Wednesday/Drive
# Time has nothing in the ratings library for that day at all -> unmatched.
UPLOAD_CSV = (
    b'Channel,Programme,Day,Spots\n'
    b'TVC,Prime Time,Monday,3\n'
    b'AIT Lagos,News,Tuesday,2\n'
    b'XYZ FM,Drive Time,Wednesday,1\n'
)


def _attach_ratings(client, project_id):
    dataset = client.post(
        '/api/ratings-datasets',
        json={
            'provider': 'Nielsen',
            'rows': [
                {'medium': 'TV', 'station': 'TVC', 'day': 'Monday', 'programme': 'Prime Time', 'rating': 1.2},
                {'medium': 'TV', 'station': 'AIT', 'day': 'Tuesday', 'programme': 'News', 'rating': 2.1},
            ],
        },
    ).json()
    client.post(f"/api/projects/{project_id}/ratings-datasets/{dataset['ratingsDatasetId']}/attach")
    return dataset


def _upload(client, project_id, brand_id):
    files = {'file': ('report.csv', io.BytesIO(UPLOAD_CSV), 'text/csv')}
    return client.post(f'/api/projects/{project_id}/uploads', files=files, data={'brand_id': brand_id})


def test_matches_computed_as_exact_suggested_and_unmatched(client, project, brand):
    _upload(client, project['projectId'], brand['brandId'])
    _attach_ratings(client, project['projectId'])

    response = client.get(f"/api/projects/{project['projectId']}/matches")
    assert response.status_code == 200
    matches = response.json()
    assert len(matches) == 3

    by_status = {}
    for match in matches:
        by_status.setdefault(match['matchStatus'], []).append(match)

    assert len(by_status.get('exact', [])) == 1
    assert by_status['exact'][0]['matchedRatingId'] is not None
    assert by_status['exact'][0]['matchConfidence'] is None

    assert len(by_status.get('suggested', [])) == 1
    suggested = by_status['suggested'][0]
    assert suggested['matchedRatingId'] is not None
    assert suggested['matchConfidence'] == pytest.approx(1.0)

    assert len(by_status.get('unmatched', [])) == 1
    assert by_status['unmatched'][0]['matchedRatingId'] is None


def test_match_job_completes_and_persists_results(client, project, brand):
    _upload(client, project['projectId'], brand['brandId'])
    _attach_ratings(client, project['projectId'])

    response = client.post(f"/api/projects/{project['projectId']}/matches/jobs?mode=ensure")
    assert response.status_code == 202
    job = response.json()
    assert job['status'] in ('queued', 'running', 'completed')

    for _ in range(40):
        if job['status'] in ('completed', 'failed'):
            break
        time.sleep(0.05)
        job = client.get(f"/api/projects/{project['projectId']}/matches/jobs/{job['jobId']}").json()

    assert job['status'] == 'completed'
    assert len(client.get(f"/api/projects/{project['projectId']}/matches").json()) == 3


def test_duplicate_unresolved_rows_do_not_crash_matching(client, project, brand):
    ratings = (
        b'Channel,Day,Programme,Rating\n'
        b'Other FM,Monday,Morning Show,1.2\n'
    )
    files = {'file': ('ratings.csv', io.BytesIO(ratings), 'text/csv')}
    dataset = client.post('/api/ratings-datasets/upload', files=files).json()
    client.post(f"/api/projects/{project['projectId']}/ratings-datasets/{dataset['ratingsDatasetId']}/attach")

    media = (
        b'Channel,Programme,Day,Spots\n'
        b'Unknown FM,Drive Time,Monday,3\n'
        b'Unknown FM,Drive Time,Monday,2\n'
    )
    files = {'file': ('report.csv', io.BytesIO(media), 'text/csv')}
    client.post(
        f"/api/projects/{project['projectId']}/uploads",
        files=files,
        data={'brand_id': brand['brandId'], 'default_medium': 'Radio'},
    )

    response = client.get(f"/api/projects/{project['projectId']}/matches")
    assert response.status_code == 200
    assert len(response.json()) == 2


def test_matches_dated_ratings_to_media_rows(client, project, brand):
    content = (
        b'Channel,Date,Programme,Rating\n'
        b'TVC,2026-08-17,Prime Time,1.2\n'
    )
    files = {'file': ('dated-ratings.csv', io.BytesIO(content), 'text/csv')}
    dataset = client.post('/api/ratings-datasets/upload', files=files).json()
    client.post(f"/api/projects/{project['projectId']}/ratings-datasets/{dataset['ratingsDatasetId']}/attach")

    media = (
        b'Channel,Programme,Day,Spots\n'
        b'TVC,Prime Time,Monday,3\n'
    )
    files = {'file': ('report.csv', io.BytesIO(media), 'text/csv')}
    client.post(
        f"/api/projects/{project['projectId']}/uploads",
        files=files,
        data={'brand_id': brand['brandId']},
    )

    response = client.get(f"/api/projects/{project['projectId']}/matches")
    assert response.status_code == 200
    matches = response.json()
    assert len(matches) == 1
    assert matches[0]['matchStatus'] == 'exact'


def test_matches_time_bands_on_media_and_ratings_rows(client, project, brand):
    ratings = (
        b'Channel,Day,Programme,Time Band,Rating\n'
        b'TVC,Monday,Prime Time,19:00-20:00,1.2\n'
    )
    files = {'file': ('ratings.csv', io.BytesIO(ratings), 'text/csv')}
    dataset = client.post('/api/ratings-datasets/upload', files=files).json()
    client.post(f"/api/projects/{project['projectId']}/ratings-datasets/{dataset['ratingsDatasetId']}/attach")

    media = (
        b'Channel,Programme,Time Band,Day,Spots\n'
        b'TVC,Prime Time,19:00-20:00,Monday,3\n'
    )
    files = {'file': ('report.csv', io.BytesIO(media), 'text/csv')}
    client.post(
        f"/api/projects/{project['projectId']}/uploads",
        files=files,
        data={'brand_id': brand['brandId']},
    )

    matches = client.get(f"/api/projects/{project['projectId']}/matches").json()
    assert len(matches) == 1
    assert matches[0]['matchStatus'] == 'exact'


def test_exact_match_accepts_media_time_inside_rating_15_minute_band(client, project, brand):
    dataset = client.post(
        '/api/ratings-datasets',
        json={'provider': 'Nielsen', 'rows': [{
            'medium': 'Radio', 'station': 'Cool FM', 'day': 'Monday',
            'programme': 'Vendor Programme', 'timeBand': '1:00 - 1:15', 'rating': 1.2,
        }]},
    ).json()
    client.post(f"/api/projects/{project['projectId']}/ratings-datasets/{dataset['ratingsDatasetId']}/attach")

    media = b'Channel,Programme,Time Band,Day,Spots\nCool FM,Any Programme,1:07:43,Monday,3\n'
    files = {'file': ('report.csv', io.BytesIO(media), 'text/csv')}
    client.post(
        f"/api/projects/{project['projectId']}/uploads",
        files=files,
        data={'brand_id': brand['brandId'], 'default_medium': 'Radio'},
    )

    matches = client.get(f"/api/projects/{project['projectId']}/matches").json()
    assert len(matches) == 1
    assert matches[0]['matchStatus'] == 'exact'


def test_exact_matching_uses_time_band_instead_of_programme(client, project, brand):
    dataset = client.post(
        '/api/ratings-datasets',
        json={
            'provider': 'Nielsen',
            'rows': [{
                'medium': 'Radio',
                'station': 'Cool FM',
                'day': 'Monday',
                'programme': 'Vendor Programme Name',
                'timeBand': '19:00-20:00',
                'rating': 1.2,
            }],
        },
    ).json()
    client.post(f"/api/projects/{project['projectId']}/ratings-datasets/{dataset['ratingsDatasetId']}/attach")

    media = (
        b'Channel,Programme,Time Band,Day,Spots\n'
        b'Cool FM,Different Programme Name,19:00-20:00,Monday,3\n'
    )
    files = {'file': ('report.csv', io.BytesIO(media), 'text/csv')}
    client.post(
        f"/api/projects/{project['projectId']}/uploads",
        files=files,
        data={'brand_id': brand['brandId'], 'default_medium': 'Radio'},
    )

    matches = client.get(f"/api/projects/{project['projectId']}/matches").json()
    assert len(matches) == 1
    assert matches[0]['matchStatus'] == 'exact'


def test_matches_are_computed_once_and_then_persisted(client, project, brand):
    _upload(client, project['projectId'], brand['brandId'])
    _attach_ratings(client, project['projectId'])

    first = client.get(f"/api/projects/{project['projectId']}/matches").json()
    second = client.get(f"/api/projects/{project['projectId']}/matches").json()
    assert {m['ratingMatchId'] for m in first} == {m['ratingMatchId'] for m in second}


def test_matches_without_any_ratings_are_all_unmatched(client, project, brand):
    _upload(client, project['projectId'], brand['brandId'])
    matches = client.get(f"/api/projects/{project['projectId']}/matches").json()
    assert len(matches) == 3
    assert all(m['matchStatus'] == 'unmatched' for m in matches)
    assert all(m['matchedRatingId'] is None for m in matches)


def test_correct_match_sets_manual_status(client, project, brand):
    _upload(client, project['projectId'], brand['brandId'])
    dataset = _attach_ratings(client, project['projectId'])
    matches = client.get(f"/api/projects/{project['projectId']}/matches").json()
    unmatched = next(m for m in matches if m['matchStatus'] == 'unmatched')
    rows = client.get(f"/api/ratings-datasets/{dataset['ratingsDatasetId']}/rows").json()
    target_rating_id = rows[0]['ratingRowId']

    response = client.post(
        f"/api/projects/{project['projectId']}/matches/{unmatched['ratingMatchId']}/correct",
        json={'matchedRatingId': target_rating_id},
    )
    assert response.status_code == 200
    body = response.json()
    assert body['matchStatus'] == 'manual'
    assert body['matchedRatingId'] == target_rating_id
    assert body['correctedAt'] is not None


def test_correct_match_to_null_marks_manually_unmatched(client, project, brand):
    _upload(client, project['projectId'], brand['brandId'])
    matches = client.get(f"/api/projects/{project['projectId']}/matches").json()
    match_id = matches[0]['ratingMatchId']

    response = client.post(
        f"/api/projects/{project['projectId']}/matches/{match_id}/correct", json={'matchedRatingId': None}
    )
    assert response.status_code == 200
    body = response.json()
    assert body['matchStatus'] == 'manual'
    assert body['matchedRatingId'] is None


def test_correct_match_rejects_rating_not_attached_to_project(client, project, brand):
    _upload(client, project['projectId'], brand['brandId'])
    matches = client.get(f"/api/projects/{project['projectId']}/matches").json()
    unmatched = next(m for m in matches if m['matchStatus'] == 'unmatched')

    # a real rating row, but never attached to this project
    foreign_dataset = client.post(
        '/api/ratings-datasets',
        json={'provider': 'Other', 'rows': [{'medium': 'TV', 'station': 'XYZ FM', 'day': 'Wednesday', 'programme': 'Drive Time', 'rating': 3.0}]},
    ).json()
    foreign_rating_id = client.get(f"/api/ratings-datasets/{foreign_dataset['ratingsDatasetId']}/rows").json()[0]['ratingRowId']

    response = client.post(
        f"/api/projects/{project['projectId']}/matches/{unmatched['ratingMatchId']}/correct",
        json={'matchedRatingId': foreign_rating_id},
    )
    assert response.status_code == 422


def test_correct_match_rejects_nonexistent_rating_id(client, project, brand):
    _upload(client, project['projectId'], brand['brandId'])
    matches = client.get(f"/api/projects/{project['projectId']}/matches").json()
    match_id = matches[0]['ratingMatchId']

    response = client.post(
        f"/api/projects/{project['projectId']}/matches/{match_id}/correct",
        json={'matchedRatingId': 'does-not-exist'},
    )
    assert response.status_code == 422


def test_correct_missing_match_returns_404(client, project, brand):
    _upload(client, project['projectId'], brand['brandId'])
    response = client.post(
        f"/api/projects/{project['projectId']}/matches/does-not-exist/correct", json={'matchedRatingId': None}
    )
    assert response.status_code == 404


def test_matches_rejects_missing_project(client):
    response = client.get('/api/projects/does-not-exist/matches')
    assert response.status_code == 404


def test_correct_rejects_missing_project(client):
    response = client.post(
        '/api/projects/does-not-exist/matches/some-id/correct', json={'matchedRatingId': None}
    )
    assert response.status_code == 404


def test_matches_are_scoped_per_project(client, project, brand):
    _upload(client, project['projectId'], brand['brandId'])

    other_project = client.post('/api/projects', json={'projectName': 'Malaria Category'}).json()
    other_brand = client.post(
        f"/api/projects/{other_project['projectId']}/brands", json={'name': 'Brand X'}
    ).json()
    _upload(client, other_project['projectId'], other_brand['brandId'])

    matches_a = client.get(f"/api/projects/{project['projectId']}/matches").json()
    matches_b = client.get(f"/api/projects/{other_project['projectId']}/matches").json()
    assert len(matches_a) == 3
    assert len(matches_b) == 3
    assert {m['ratingMatchId'] for m in matches_a}.isdisjoint({m['ratingMatchId'] for m in matches_b})

    # correcting a match in project A must not be reachable via project B
    response = client.post(
        f"/api/projects/{other_project['projectId']}/matches/{matches_a[0]['ratingMatchId']}/correct",
        json={'matchedRatingId': None},
    )
    assert response.status_code == 404


def test_recompute_retries_unmatched_rows_after_new_ratings_attached(client, project, brand):
    _upload(client, project['projectId'], brand['brandId'])
    before = client.get(f"/api/projects/{project['projectId']}/matches").json()
    assert all(m['matchStatus'] == 'unmatched' for m in before)  # no ratings yet

    # now attach ratings that cover two of the three unmatched rows
    _attach_ratings(client, project['projectId'])

    response = client.post(f"/api/projects/{project['projectId']}/matches/recompute")
    assert response.status_code == 200
    after = {m['ratingMatchId']: m for m in response.json()}

    statuses = sorted(m['matchStatus'] for m in after.values())
    assert statuses == ['exact', 'suggested', 'unmatched']
    # the previously-unmatched rows kept their ids — recompute updates in place
    assert set(after.keys()) == {m['ratingMatchId'] for m in before}


def test_recompute_never_touches_manual_corrections(client, project, brand):
    _upload(client, project['projectId'], brand['brandId'])
    matches = client.get(f"/api/projects/{project['projectId']}/matches").json()
    target = matches[0]
    client.post(
        f"/api/projects/{project['projectId']}/matches/{target['ratingMatchId']}/correct",
        json={'matchedRatingId': None},
    )

    _attach_ratings(client, project['projectId'])
    client.post(f"/api/projects/{project['projectId']}/matches/recompute")

    refreshed = next(
        m for m in client.get(f"/api/projects/{project['projectId']}/matches").json()
        if m['ratingMatchId'] == target['ratingMatchId']
    )
    assert refreshed['matchStatus'] == 'manual'  # untouched by recompute


def test_recompute_is_a_noop_with_no_unmatched_rows(client, project, brand):
    _upload(client, project['projectId'], brand['brandId'])
    _attach_ratings(client, project['projectId'])
    client.get(f"/api/projects/{project['projectId']}/matches")  # compute everything first

    for match in client.get(f"/api/projects/{project['projectId']}/matches").json():
        if match['matchStatus'] == 'unmatched':
            client.post(
                f"/api/projects/{project['projectId']}/matches/{match['ratingMatchId']}/correct",
                json={'matchedRatingId': None},
            )

    before = client.get(f"/api/projects/{project['projectId']}/matches").json()
    response = client.post(f"/api/projects/{project['projectId']}/matches/recompute")
    assert response.status_code == 200
    assert response.json() == before


def test_recompute_rejects_missing_project(client):
    response = client.post('/api/projects/does-not-exist/matches/recompute')
    assert response.status_code == 404
