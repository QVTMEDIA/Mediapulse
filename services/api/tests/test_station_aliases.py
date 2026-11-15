import pytest
from fastapi.testclient import TestClient

from app.auth import get_current_user
from app.main import app
from app.repositories.activity_log import InMemoryActivityLogRepository, get_activity_log_repository
from app.repositories.station_aliases import InMemoryStationAliasesRepository, get_station_aliases_repository

from ._auth_helpers import make_test_user


def _returning(instance):
    def _get():
        return instance

    return _get


@pytest.fixture
def client():
    overrides = {
        get_station_aliases_repository: InMemoryStationAliasesRepository(),
        get_activity_log_repository: InMemoryActivityLogRepository(),
    }
    for dependency, instance in overrides.items():
        app.dependency_overrides[dependency] = _returning(instance)
    app.dependency_overrides[get_current_user] = _returning(make_test_user())
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_create_and_list_station_aliases(client):
    response = client.post(
        '/api/station-aliases', json={'aliasName': 'TVC Lagos', 'canonicalName': 'Lagos, TV Continental (TVC E)'}
    )
    assert response.status_code == 201
    body = response.json()
    assert body['aliasName'] == 'TVC Lagos'
    assert body['canonicalName'] == 'Lagos, TV Continental (TVC E)'
    assert body['createdByName']

    listed = client.get('/api/station-aliases').json()
    assert len(listed) == 1
    assert listed[0]['stationAliasId'] == body['stationAliasId']


def test_create_station_alias_for_an_already_aliased_name_replaces_it(client):
    client.post('/api/station-aliases', json={'aliasName': 'TVC Lagos', 'canonicalName': 'Wrong Station'})
    client.post('/api/station-aliases', json={'aliasName': 'tvc   lagos', 'canonicalName': 'Lagos, TV Continental (TVC E)'})

    listed = client.get('/api/station-aliases').json()
    assert len(listed) == 1
    assert listed[0]['canonicalName'] == 'Lagos, TV Continental (TVC E)'


def test_delete_station_alias(client):
    created = client.post(
        '/api/station-aliases', json={'aliasName': 'TVC Lagos', 'canonicalName': 'Lagos, TV Continental (TVC E)'}
    ).json()

    response = client.delete(f"/api/station-aliases/{created['stationAliasId']}")
    assert response.status_code == 204
    assert client.get('/api/station-aliases').json() == []


def test_delete_unknown_station_alias_404s(client):
    response = client.delete('/api/station-aliases/does-not-exist')
    assert response.status_code == 404


def test_create_station_alias_rejects_blank_fields(client):
    response = client.post('/api/station-aliases', json={'aliasName': '', 'canonicalName': 'Lagos, TV Continental'})
    assert response.status_code == 422
