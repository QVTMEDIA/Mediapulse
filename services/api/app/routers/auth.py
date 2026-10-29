from fastapi import APIRouter, Depends, HTTPException

from ..auth import get_current_user
from ..config import get_settings
from ..repositories.activity_log import ActivityLogRepository, get_activity_log_repository
from ..repositories.projects import ProjectsRepository, get_projects_repository
from ..repositories.users import UserRecord, UsersRepository, get_users_repository
from ..schemas.users import (
    LoginIn,
    RegisterIn,
    TokenOut,
    UpdateActiveProjectIn,
    UpdateAvatarIn,
    UpdateProfileIn,
    UserOut,
)
from ..security import create_access_token, hash_password, verify_password

router = APIRouter(prefix='/api/auth', tags=['auth'])


def _to_out(record: UserRecord) -> UserOut:
    return UserOut(
        user_id=record.id,
        email=record.email,
        display_name=record.display_name,
        role=record.role,
        created_at=record.created_at,
        avatar_url=record.avatar_data_url,
        last_active_project_id=record.last_active_project_id,
    )


def _token_for(record: UserRecord) -> TokenOut:
    return TokenOut(
        access_token=create_access_token(record.id, record.email, record.role),
        user=_to_out(record),
    )


@router.post('/register', response_model=TokenOut, status_code=201)
def register(
    payload: RegisterIn,
    users_repo: UsersRepository = Depends(get_users_repository),
    activity_repo: ActivityLogRepository = Depends(get_activity_log_repository),
):
    required_code = get_settings().register_invite_code
    # Checked before the duplicate-email lookup below, on purpose: an
    # unauthenticated caller with no invite code shouldn't be able to use
    # this endpoint's 409/201 split to probe which emails already have
    # accounts.
    if required_code and payload.invite_code != required_code:
        raise HTTPException(status_code=403, detail='Invalid or missing invite code.')
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
    activity_repo.record(
        actor_id=record.id, actor_name=record.display_name, action='user.registered',
        summary=f'{record.display_name} created an account ({role}).',
    )
    return _token_for(record)


@router.post('/login', response_model=TokenOut)
def login(
    payload: LoginIn,
    users_repo: UsersRepository = Depends(get_users_repository),
    activity_repo: ActivityLogRepository = Depends(get_activity_log_repository),
):
    record = users_repo.get_by_email(payload.email)
    # Same 401 + message whether the email doesn't exist or the password is
    # wrong — distinguishing them would let a caller enumerate registered
    # emails one guess at a time.
    if record is None or not verify_password(payload.password, record.password_hash):
        raise HTTPException(status_code=401, detail='Incorrect email or password.')
    activity_repo.record(
        actor_id=record.id, actor_name=record.display_name, action='user.signed_in',
        summary=f'{record.display_name} signed in.',
    )
    return _token_for(record)


@router.get('/me', response_model=UserOut)
def me(current_user: UserRecord = Depends(get_current_user)):
    return _to_out(current_user)


@router.patch('/me', response_model=UserOut)
def update_me(
    payload: UpdateProfileIn,
    current_user: UserRecord = Depends(get_current_user),
    users_repo: UsersRepository = Depends(get_users_repository),
    activity_repo: ActivityLogRepository = Depends(get_activity_log_repository),
):
    if payload.new_password is not None:
        # current_password is required to change it -- an already-valid
        # bearer token alone shouldn't be enough to lock out the real owner
        # of the account from a hijacked or shared browser session.
        if not payload.current_password or not verify_password(payload.current_password, current_user.password_hash):
            raise HTTPException(status_code=401, detail='Incorrect current password.')
    password_hash = hash_password(payload.new_password) if payload.new_password is not None else None
    record = users_repo.update_profile(current_user.id, display_name=payload.display_name, password_hash=password_hash)
    # Two independent, optionally-simultaneous changes on this one endpoint
    # (see UpdateProfileIn's own docstring) -- logged as up to two separate
    # entries rather than one combined one, so each reads clearly on its own
    # in the activity feed.
    if payload.display_name is not None and payload.display_name != current_user.display_name:
        activity_repo.record(
            actor_id=record.id, actor_name=record.display_name, action='user.profile_updated',
            summary=f'{current_user.display_name} renamed their account to "{record.display_name}".',
        )
    if password_hash is not None:
        activity_repo.record(
            actor_id=record.id, actor_name=record.display_name, action='user.password_changed',
            summary=f'{record.display_name} changed their password.',
        )
    return _to_out(record)


@router.put('/me/avatar', response_model=UserOut)
def update_avatar(
    payload: UpdateAvatarIn,
    current_user: UserRecord = Depends(get_current_user),
    users_repo: UsersRepository = Depends(get_users_repository),
    activity_repo: ActivityLogRepository = Depends(get_activity_log_repository),
):
    record = users_repo.update_avatar(current_user.id, payload.avatar_data_url)
    activity_repo.record(
        actor_id=record.id, actor_name=record.display_name, action='user.avatar_updated',
        summary=f'{record.display_name} updated their profile photo.',
    )
    return _to_out(record)


@router.delete('/me/avatar', response_model=UserOut)
def remove_avatar(
    current_user: UserRecord = Depends(get_current_user),
    users_repo: UsersRepository = Depends(get_users_repository),
    activity_repo: ActivityLogRepository = Depends(get_activity_log_repository),
):
    record = users_repo.update_avatar(current_user.id, None)
    activity_repo.record(
        actor_id=record.id, actor_name=record.display_name, action='user.avatar_removed',
        summary=f'{record.display_name} removed their profile photo.',
    )
    return _to_out(record)


@router.put('/me/active-project', response_model=UserOut)
def update_active_project(
    payload: UpdateActiveProjectIn,
    current_user: UserRecord = Depends(get_current_user),
    users_repo: UsersRepository = Depends(get_users_repository),
    projects_repo: ProjectsRepository = Depends(get_projects_repository),
):
    """Called whenever the frontend switches which project is active, so
    the app can open back to it on this user's next login instead of
    always defaulting to whichever project anyone most recently updated.
    Fire-and-forget from the frontend's point of view -- its own in-memory
    activeProjectId state already drives the current session, this just
    records it for next time."""
    if payload.project_id is not None and projects_repo.get_project(payload.project_id) is None:
        raise HTTPException(status_code=404, detail='Project not found')
    record = users_repo.update_last_active_project(current_user.id, payload.project_id)
    return _to_out(record)
