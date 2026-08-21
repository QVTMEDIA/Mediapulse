from fastapi import APIRouter, Depends, HTTPException

from ..auth import get_current_user
from ..repositories.users import UserRecord, UsersRepository, get_users_repository
from ..schemas.users import LoginIn, RegisterIn, TokenOut, UserOut
from ..security import create_access_token, hash_password, verify_password

router = APIRouter(prefix='/api/auth', tags=['auth'])


def _to_out(record: UserRecord) -> UserOut:
    return UserOut(
        user_id=record.id,
        email=record.email,
        display_name=record.display_name,
        role=record.role,
        created_at=record.created_at,
    )


def _token_for(record: UserRecord) -> TokenOut:
    return TokenOut(
        access_token=create_access_token(record.id, record.email, record.role),
        user=_to_out(record),
    )


@router.post('/register', response_model=TokenOut, status_code=201)
def register(payload: RegisterIn, users_repo: UsersRepository = Depends(get_users_repository)):
    if users_repo.get_by_email(payload.email) is not None:
        raise HTTPException(status_code=409, detail='An account with this email already exists.')
    # Bootstrap: the very first account on a fresh deployment becomes the
    # owner (there's no one else yet who could grant that role); every
    # self-registration after that starts as 'member' and needs an existing
    # owner/admin to promote them via PATCH /api/users/{userId}/role.
    role = 'owner' if users_repo.count_users() == 0 else 'member'
    record = users_repo.create_user(
        email=payload.email,
        display_name=payload.display_name or payload.email.split('@')[0],
        password_hash=hash_password(payload.password),
        role=role,
    )
    return _token_for(record)


@router.post('/login', response_model=TokenOut)
def login(payload: LoginIn, users_repo: UsersRepository = Depends(get_users_repository)):
    record = users_repo.get_by_email(payload.email)
    # Same 401 + message whether the email doesn't exist or the password is
    # wrong — distinguishing them would let a caller enumerate registered
    # emails one guess at a time.
    if record is None or not verify_password(payload.password, record.password_hash):
        raise HTTPException(status_code=401, detail='Incorrect email or password.')
    return _token_for(record)


@router.get('/me', response_model=UserOut)
def me(current_user: UserRecord = Depends(get_current_user)):
    return _to_out(current_user)
