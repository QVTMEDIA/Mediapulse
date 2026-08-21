from fastapi import APIRouter, Depends, HTTPException

from ..auth import require_role
from ..repositories.users import VALID_ROLES, UserRecord, UsersRepository, get_users_repository
from ..schemas.users import UpdateRoleIn, UserOut

router = APIRouter(prefix='/api/users', tags=['users'])


def _to_out(record: UserRecord) -> UserOut:
    return UserOut(
        user_id=record.id,
        email=record.email,
        display_name=record.display_name,
        role=record.role,
        created_at=record.created_at,
    )


@router.get('', response_model=list[UserOut])
def list_users(
    users_repo: UsersRepository = Depends(get_users_repository),
    _current_user: UserRecord = Depends(require_role('owner', 'admin')),
):
    return [_to_out(record) for record in users_repo.list_users()]


@router.patch('/{user_id}/role', response_model=UserOut)
def update_role(
    user_id: str,
    payload: UpdateRoleIn,
    users_repo: UsersRepository = Depends(get_users_repository),
    current_user: UserRecord = Depends(require_role('owner')),
):
    if payload.role not in VALID_ROLES:
        raise HTTPException(status_code=422, detail=f'role must be one of {", ".join(VALID_ROLES)}.')
    if user_id == current_user.id and payload.role != 'owner':
        # Not a security rule (an owner could still demote themselves via
        # direct SQL) — a usability one: a lone owner accidentally locking
        # themselves out of role management with no one left to undo it.
        raise HTTPException(status_code=422, detail="You can't change your own role away from owner.")
    record = users_repo.update_role(user_id, payload.role)
    if record is None:
        raise HTTPException(status_code=404, detail='User not found')
    return _to_out(record)
