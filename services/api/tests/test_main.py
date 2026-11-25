import pytest
from fastapi.testclient import TestClient
from psycopg.errors import InvalidTextRepresentation

from app.auth import get_current_user
from app.main import app
from app.repositories.projects import get_projects_repository

from ._auth_helpers import make_test_user


class _RaisesInvalidUuid:
    """Stands in for any Postgres-backed repository's get-by-id method when
    handed a malformed id. Every id column in db/schema.sql is `uuid`, and
    no repository validates an id's shape before querying with it -- an
    invalid one (not what InMemory*Repository's tests ever exercise) makes
    Postgres itself raise this, for real, on every id-based route in the
    app. See app/main.py's invalid_id_format_handler."""

    def get_project(self, project_id):
        raise InvalidTextRepresentation(f'invalid input syntax for type uuid: "{project_id}"')


@pytest.fixture
def client():
    app.dependency_overrides[get_projects_repository] = lambda: _RaisesInvalidUuid()
    app.dependency_overrides[get_current_user] = lambda: make_test_user(role='owner')
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def test_malformed_id_returns_404_not_500(client):
    # Regression: this 500'd in production (GET /api/projects/does-not-exist)
    # because nothing between the path parameter and the `WHERE id = %s`
    # query ever checks the id looks like a UUID -- Postgres's own rejection
    # of the bad literal reached the client as a bare 500 instead of the 404
    # a not-found id means everywhere else in this API.
    response = client.get('/api/projects/does-not-exist')
    assert response.status_code == 404
    assert response.json() == {'detail': 'Not found.'}
