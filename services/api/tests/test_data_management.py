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


def _project(client):
    return client.post('/api/projects', json={'projectName': 'Data Management Test'}).json()


def _brand(client, project_id, name='Brand A'):
    return client.post(f'/api/projects/{project_id}/brands', json={'name': name}).json()


UPLOAD_CSV = b'Channel,Programme,Day,Spots\nAIT,Morning Show,Monday,3\n'


def _upload(client, project_id, brand_id):
    return client.post(
        f'/api/projects/{project_id}/uploads',
        data={'kind': 'brand_report', 'brand_id': brand_id, 'default_medium': 'TV'},
        files={'file': ('report.csv', io.BytesIO(UPLOAD_CSV), 'text/csv')},
    ).json()


def _attach_ratings(client, project_id):
    dataset = client.post(
        '/api/ratings-datasets',
        json={'provider': 'P', 'rows': [{'medium': 'TV', 'station': 'AIT', 'day': 'MON', 'programme': 'Morning Show', 'rating': 5.0}]},
    ).json()
    client.post(f"/api/projects/{project_id}/ratings-datasets/{dataset['ratingsDatasetId']}/attach")
    return dataset


# --- delete upload -----------------------------------------------------------


def test_delete_uncalculated_upload_succeeds(client):
    project = _project(client)
    brand = _brand(client, project['projectId'])
    upload = _upload(client, project['projectId'], brand['brandId'])

    response = client.delete(f"/api/projects/{project['projectId']}/uploads/{upload['uploadId']}")
    assert response.status_code == 204

    activity = client.get(f"/api/projects/{project['projectId']}/media-activity").json()
    assert activity == []


def test_delete_upload_removes_its_matches_too(client):
    project = _project(client)
    project_id = project['projectId']
    brand = _brand(client, project_id)
    upload = _upload(client, project_id, brand['brandId'])
    _attach_ratings(client, project_id)
    matches_before = client.get(f'/api/projects/{project_id}/matches').json()
    assert len(matches_before) == 1

    client.delete(f"/api/projects/{project_id}/uploads/{upload['uploadId']}")
    matches_after = client.get(f'/api/projects/{project_id}/matches').json()
    assert matches_after == []


def test_delete_calculated_upload_is_refused(client):
    project = _project(client)
    project_id = project['projectId']
    brand = _brand(client, project_id)
    upload = _upload(client, project_id, brand['brandId'])
    _attach_ratings(client, project_id)
    client.post(f'/api/projects/{project_id}/calculate')

    response = client.delete(f"/api/projects/{project_id}/uploads/{upload['uploadId']}")
    assert response.status_code == 409

    # nothing was touched
    activity = client.get(f'/api/projects/{project_id}/media-activity').json()
    assert len(activity) == 1


def test_delete_missing_upload_returns_404(client):
    project = _project(client)
    response = client.delete(f"/api/projects/{project['projectId']}/uploads/does-not-exist")
    assert response.status_code == 404


def test_delete_upload_requires_owner_or_admin(client):
    project = _project(client)
    brand = _brand(client, project['projectId'])
    upload = _upload(client, project['projectId'], brand['brandId'])

    app.dependency_overrides[get_current_user] = _returning(make_test_user(role='member'))
    response = client.delete(f"/api/projects/{project['projectId']}/uploads/{upload['uploadId']}")
    assert response.status_code == 403


# --- delete brand --------------------------------------------------------


def test_delete_brand_with_no_activity_succeeds(client):
    project = _project(client)
    brand = _brand(client, project['projectId'])
    response = client.delete(f"/api/projects/{project['projectId']}/brands/{brand['brandId']}")
    assert response.status_code == 204
    assert client.get(f"/api/projects/{project['projectId']}/brands").json() == []


def test_delete_uncalculated_brand_removes_its_activity(client):
    project = _project(client)
    project_id = project['projectId']
    brand = _brand(client, project_id)
    _upload(client, project_id, brand['brandId'])

    response = client.delete(f"/api/projects/{project_id}/brands/{brand['brandId']}")
    assert response.status_code == 204
    assert client.get(f'/api/projects/{project_id}/media-activity').json() == []


def test_delete_brand_only_removes_its_own_activity_not_the_whole_upload(client):
    # A composite_report upload can span multiple brands — deleting one
    # brand should leave the other brand's rows (and the upload record)
    # from that same file intact.
    project = _project(client)
    project_id = project['projectId']
    csv = (
        b'Brand,Channel,Programme,Day,Spots,Rating\n'
        b'Brand One,AIT,Morning Show,Monday,3,5.0\n'
        b'Brand Two,NTA,News,Tuesday,2,3.0\n'
    )
    client.post(
        f'/api/projects/{project_id}/uploads',
        data={'kind': 'composite_report', 'default_medium': 'TV'},
        files={'file': ('composite.csv', io.BytesIO(csv), 'text/csv')},
    )
    brands = {b['name']: b['brandId'] for b in client.get(f'/api/projects/{project_id}/brands').json()}
    assert set(brands) == {'Brand One', 'Brand Two'}

    client.delete(f"/api/projects/{project_id}/brands/{brands['Brand One']}")

    remaining_activity = client.get(f'/api/projects/{project_id}/media-activity').json()
    assert len(remaining_activity) == 1
    assert remaining_activity[0]['brandId'] == brands['Brand Two']
    # the upload record itself is untouched
    assert len(client.get(f'/api/projects/{project_id}/uploads').json()) == 1


def test_delete_calculated_brand_is_refused(client):
    project = _project(client)
    project_id = project['projectId']
    brand = _brand(client, project_id)
    _upload(client, project_id, brand['brandId'])
    _attach_ratings(client, project_id)
    client.post(f'/api/projects/{project_id}/calculate')

    response = client.delete(f"/api/projects/{project_id}/brands/{brand['brandId']}")
    assert response.status_code == 409
    assert len(client.get(f'/api/projects/{project_id}/brands').json()) == 1


def test_delete_missing_brand_returns_404(client):
    project = _project(client)
    response = client.delete(f"/api/projects/{project['projectId']}/brands/does-not-exist")
    assert response.status_code == 404


def test_delete_brand_requires_owner_or_admin(client):
    project = _project(client)
    brand = _brand(client, project['projectId'])
    app.dependency_overrides[get_current_user] = _returning(make_test_user(role='member'))
    response = client.delete(f"/api/projects/{project['projectId']}/brands/{brand['brandId']}")
    assert response.status_code == 403


# --- detach ratings dataset ------------------------------------------------


def test_detach_ratings_dataset_succeeds(client):
    project = _project(client)
    project_id = project['projectId']
    dataset = _attach_ratings(client, project_id)
    assert len(client.get(f'/api/projects/{project_id}/ratings-datasets').json()) == 1

    response = client.delete(f"/api/projects/{project_id}/ratings-datasets/{dataset['ratingsDatasetId']}/attach")
    assert response.status_code == 204
    assert client.get(f'/api/projects/{project_id}/ratings-datasets').json() == []

    # the shared dataset itself still exists in the library
    library = client.get('/api/ratings-datasets').json()
    assert any(d['ratingsDatasetId'] == dataset['ratingsDatasetId'] for d in library)


def test_detach_does_not_require_owner(client):
    # Unlike delete-upload/delete-brand, detaching a ratings dataset never
    # touches the audit trail — any authenticated user can do it, same as
    # attach.
    project = _project(client)
    project_id = project['projectId']
    dataset = _attach_ratings(client, project_id)

    app.dependency_overrides[get_current_user] = _returning(make_test_user(role='member'))
    response = client.delete(f"/api/projects/{project_id}/ratings-datasets/{dataset['ratingsDatasetId']}/attach")
    assert response.status_code == 204


def test_detach_not_attached_dataset_returns_404(client):
    project = _project(client)
    dataset = client.post('/api/ratings-datasets', json={'provider': 'P', 'rows': []}).json()
    response = client.delete(f"/api/projects/{project['projectId']}/ratings-datasets/{dataset['ratingsDatasetId']}/attach")
    assert response.status_code == 404


def test_detach_preserves_existing_matches_and_calculations(client):
    # Detaching removes future matching ability, but a run already
    # calculated against this data keeps working — the audit trail doesn't
    # depend on the attachment still existing.
    project = _project(client)
    project_id = project['projectId']
    brand = _brand(client, project_id)
    _upload(client, project_id, brand['brandId'])
    dataset = _attach_ratings(client, project_id)
    run = client.post(f'/api/projects/{project_id}/calculate').json()

    client.delete(f"/api/projects/{project_id}/ratings-datasets/{dataset['ratingsDatasetId']}/attach")

    calcs = client.get(f"/api/projects/{project_id}/runs/{run['runId']}/calculations")
    assert calcs.status_code == 200
    assert len(calcs.json()) == 1
