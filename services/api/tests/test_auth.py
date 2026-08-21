import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.repositories.projects import InMemoryProjectsRepository, get_projects_repository
from app.repositories.users import InMemoryUsersRepository, get_users_repository


@pytest.fixture
def client():
    users_repo = InMemoryUsersRepository()
    projects_repo = InMemoryProjectsRepository()
    app.dependency_overrides[get_users_repository] = lambda: users_repo
    app.dependency_overrides[get_projects_repository] = lambda: projects_repo
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()


def _register(client, email='owner@example.com', password='correct horse', display_name='Owner'):
    return client.post(
        '/api/auth/register',
        json={'email': email, 'password': password, 'displayName': display_name},
    )


def test_register_returns_token_and_user(client):
    response = _register(client)
    assert response.status_code == 201
    body = response.json()
    assert body['tokenType'] == 'bearer'
    assert body['accessToken']
    assert body['user']['email'] == 'owner@example.com'
    assert body['user']['displayName'] == 'Owner'
    assert 'passwordHash' not in body['user']
    assert 'password_hash' not in body['user']


def test_first_registered_user_becomes_owner(client):
    body = _register(client).json()
    assert body['user']['role'] == 'owner'


def test_second_registered_user_becomes_member(client):
    _register(client, email='first@example.com')
    body = _register(client, email='second@example.com').json()
    assert body['user']['role'] == 'member'


def test_register_rejects_duplicate_email(client):
    _register(client, email='dup@example.com')
    response = _register(client, email='dup@example.com')
    assert response.status_code == 409


def test_register_rejects_short_password(client):
    response = _register(client, password='short')
    assert response.status_code == 422


def test_register_rejects_malformed_email(client):
    response = _register(client, email='not-an-email')
    assert response.status_code == 422


def test_login_succeeds_with_correct_password(client):
    _register(client, email='user@example.com', password='correct horse battery')
    response = client.post('/api/auth/login', json={'email': 'user@example.com', 'password': 'correct horse battery'})
    assert response.status_code == 200
    assert response.json()['user']['email'] == 'user@example.com'


def test_login_rejects_wrong_password(client):
    _register(client, email='user@example.com', password='correct horse battery')
    response = client.post('/api/auth/login', json={'email': 'user@example.com', 'password': 'wrong password'})
    assert response.status_code == 401


def test_login_rejects_unknown_email(client):
    response = client.post('/api/auth/login', json={'email': 'ghost@example.com', 'password': 'whatever1'})
    assert response.status_code == 401


def test_login_is_case_insensitive_on_email(client):
    _register(client, email='Mixed.Case@Example.com', password='correct horse battery')
    response = client.post('/api/auth/login', json={'email': 'mixed.case@example.com', 'password': 'correct horse battery'})
    assert response.status_code == 200


def test_me_returns_current_user_for_valid_token(client):
    token = _register(client, email='user@example.com').json()['accessToken']
    response = client.get('/api/auth/me', headers={'Authorization': f'Bearer {token}'})
    assert response.status_code == 200
    assert response.json()['email'] == 'user@example.com'


def test_me_rejects_missing_token(client):
    response = client.get('/api/auth/me')
    assert response.status_code == 401


def test_me_rejects_garbage_token(client):
    response = client.get('/api/auth/me', headers={'Authorization': 'Bearer not-a-real-token'})
    assert response.status_code == 401


def test_projects_route_requires_authentication(client):
    response = client.get('/api/projects')
    assert response.status_code == 401


def test_projects_route_accepts_valid_token(client):
    token = _register(client).json()['accessToken']
    response = client.get('/api/projects', headers={'Authorization': f'Bearer {token}'})
    assert response.status_code == 200


def test_member_cannot_delete_project(client):
    _register(client, email='owner@example.com')  # bootstrap owner
    member_token = _register(client, email='member@example.com').json()['accessToken']
    owner_token = client.post(
        '/api/auth/login', json={'email': 'owner@example.com', 'password': 'correct horse'}
    ).json()['accessToken']

    created = client.post(
        '/api/projects', json={'projectName': 'Member Cannot Delete'}, headers={'Authorization': f'Bearer {owner_token}'}
    ).json()

    response = client.delete(
        f"/api/projects/{created['projectId']}", headers={'Authorization': f'Bearer {member_token}'}
    )
    assert response.status_code == 403


def test_member_cannot_archive_project(client):
    _register(client, email='owner@example.com')
    member_token = _register(client, email='member2@example.com').json()['accessToken']
    owner_token = client.post(
        '/api/auth/login', json={'email': 'owner@example.com', 'password': 'correct horse'}
    ).json()['accessToken']

    created = client.post(
        '/api/projects', json={'projectName': 'Member Cannot Archive'}, headers={'Authorization': f'Bearer {owner_token}'}
    ).json()

    response = client.patch(
        f"/api/projects/{created['projectId']}",
        json={'archived': True},
        headers={'Authorization': f'Bearer {member_token}'},
    )
    assert response.status_code == 403


def test_member_can_edit_non_archive_fields(client):
    owner_token = _register(client, email='owner3@example.com').json()['accessToken']
    member_token = _register(client, email='member3@example.com').json()['accessToken']

    created = client.post(
        '/api/projects', json={'projectName': 'Editable By Member'}, headers={'Authorization': f'Bearer {owner_token}'}
    ).json()

    response = client.patch(
        f"/api/projects/{created['projectId']}",
        json={'client': 'New Client'},
        headers={'Authorization': f'Bearer {member_token}'},
    )
    assert response.status_code == 200
    assert response.json()['client'] == 'New Client'


def test_owner_can_delete_and_archive(client):
    owner_token = _register(client, email='owner4@example.com').json()['accessToken']
    created = client.post(
        '/api/projects', json={'projectName': 'Owner Can Manage'}, headers={'Authorization': f'Bearer {owner_token}'}
    ).json()

    archived = client.patch(
        f"/api/projects/{created['projectId']}",
        json={'archived': True},
        headers={'Authorization': f'Bearer {owner_token}'},
    )
    assert archived.status_code == 200
    assert archived.json()['archived'] is True

    deleted = client.delete(f"/api/projects/{created['projectId']}", headers={'Authorization': f'Bearer {owner_token}'})
    assert deleted.status_code == 204


def test_list_users_requires_admin_or_owner(client):
    _register(client, email='owner5@example.com')  # bootstrap owner
    member_token = _register(client, email='member5@example.com').json()['accessToken']
    response = client.get('/api/users', headers={'Authorization': f'Bearer {member_token}'})
    assert response.status_code == 403


def test_owner_can_list_users(client):
    owner_token = _register(client, email='owner6@example.com').json()['accessToken']
    _register(client, email='member6@example.com')
    response = client.get('/api/users', headers={'Authorization': f'Bearer {owner_token}'})
    assert response.status_code == 200
    emails = [u['email'] for u in response.json()]
    assert set(emails) == {'owner6@example.com', 'member6@example.com'}


def test_owner_can_promote_a_member_to_admin(client):
    owner_token = _register(client, email='owner7@example.com').json()['accessToken']
    member_body = _register(client, email='member7@example.com').json()
    member_id = member_body['user']['userId']

    response = client.patch(
        f'/api/users/{member_id}/role',
        json={'role': 'admin'},
        headers={'Authorization': f'Bearer {owner_token}'},
    )
    assert response.status_code == 200
    assert response.json()['role'] == 'admin'


def test_owner_cannot_demote_themselves(client):
    owner_body = _register(client, email='owner8@example.com').json()
    owner_token = owner_body['accessToken']
    owner_id = owner_body['user']['userId']

    response = client.patch(
        f'/api/users/{owner_id}/role',
        json={'role': 'member'},
        headers={'Authorization': f'Bearer {owner_token}'},
    )
    assert response.status_code == 422


def test_update_role_rejects_unknown_role(client):
    owner_body = _register(client, email='owner9@example.com').json()
    owner_token = owner_body['accessToken']
    member_body = _register(client, email='member9@example.com').json()
    member_id = member_body['user']['userId']

    response = client.patch(
        f'/api/users/{member_id}/role',
        json={'role': 'superuser'},
        headers={'Authorization': f'Bearer {owner_token}'},
    )
    assert response.status_code == 422
