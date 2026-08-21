"""FastAPI auth dependencies — `get_current_user` gates a route behind a
valid bearer token; `require_role(...)` additionally gates it by the caller's
global role. See `db/schema.sql`'s comment on the `users` table for why
roles are global rather than per-project."""

from fastapi import Depends, HTTPException
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .repositories.users import UserRecord, UsersRepository, get_users_repository
from .security import InvalidTokenError, decode_access_token

# auto_error=False so a missing header produces our own 401 with a
# consistent {"detail": ...} body, matching every other error path in this
# service, instead of FastAPI's default "Not authenticated" shape.
_bearer_scheme = HTTPBearer(auto_error=False)


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(_bearer_scheme),
    users_repo: UsersRepository = Depends(get_users_repository),
) -> UserRecord:
    if credentials is None:
        raise HTTPException(status_code=401, detail='Not authenticated.')
    try:
        claims = decode_access_token(credentials.credentials)
    except InvalidTokenError:
        raise HTTPException(status_code=401, detail='Invalid or expired token.')
    user = users_repo.get_by_id(claims.user_id)
    if user is None:
        raise HTTPException(status_code=401, detail='Invalid or expired token.')
    return user


def require_role(*allowed_roles: str):
    """`Depends(require_role('owner', 'admin'))` — like `get_current_user`
    but additionally 403s if the caller's role isn't in `allowed_roles`."""

    def _check(user: UserRecord = Depends(get_current_user)) -> UserRecord:
        if user.role not in allowed_roles:
            raise HTTPException(status_code=403, detail=f'Requires one of these roles: {", ".join(allowed_roles)}.')
        return user

    return _check
