from fastapi import APIRouter, Depends, HTTPException

from ..auth import get_current_user
from ..repositories.activity_log import ActivityLogRepository, get_activity_log_repository
from ..repositories.station_aliases import StationAliasesRepository, get_station_aliases_repository
from ..repositories.users import UserRecord
from ..schemas.station_aliases import StationAliasCreate, StationAliasOut

router = APIRouter(prefix='/api/station-aliases', tags=['station-aliases'], dependencies=[Depends(get_current_user)])


def _to_out(record) -> StationAliasOut:
    return StationAliasOut(
        station_alias_id=record.id,
        alias_name=record.alias_name,
        canonical_name=record.canonical_name,
        created_by_name=record.created_by_name,
        created_at=record.created_at,
    )


@router.get('', response_model=list[StationAliasOut])
def list_station_aliases(repo: StationAliasesRepository = Depends(get_station_aliases_repository)):
    """Account-wide, not scoped to one project -- a station's real identity
    doesn't change depending on which project's data mentions it, same
    reasoning as the Activity Log."""
    return [_to_out(record) for record in repo.list_aliases()]


@router.post('', response_model=StationAliasOut, status_code=201)
def create_station_alias(
    payload: StationAliasCreate,
    repo: StationAliasesRepository = Depends(get_station_aliases_repository),
    current_user: UserRecord = Depends(get_current_user),
    activity_repo: ActivityLogRepository = Depends(get_activity_log_repository),
):
    """Creating an alias for a name that's already aliased replaces its
    canonical_name (see the repository's ON CONFLICT ... DO UPDATE) rather
    than erroring -- the Matches screen's "save as alias" affordance (see
    app/routers/matches.py's correct_match) calls this the same way whether
    or not that exact raw name has been aliased before."""
    record = repo.create_alias(
        alias_name=payload.alias_name, canonical_name=payload.canonical_name,
        created_by=current_user.id, created_by_name=current_user.display_name,
    )
    activity_repo.record(
        actor_id=current_user.id, actor_name=current_user.display_name, action='station_alias.created',
        summary=f'{current_user.display_name} set "{payload.alias_name}" as an alias for "{payload.canonical_name}".',
    )
    return _to_out(record)


@router.delete('/{station_alias_id}', status_code=204)
def delete_station_alias(
    station_alias_id: str,
    repo: StationAliasesRepository = Depends(get_station_aliases_repository),
    current_user: UserRecord = Depends(get_current_user),
    activity_repo: ActivityLogRepository = Depends(get_activity_log_repository),
):
    existing = next((record for record in repo.list_aliases() if record.id == station_alias_id), None)
    if existing is None:
        raise HTTPException(status_code=404, detail='Station alias not found')
    repo.delete_alias(station_alias_id)
    activity_repo.record(
        actor_id=current_user.id, actor_name=current_user.display_name, action='station_alias.deleted',
        summary=f'{current_user.display_name} removed the station alias "{existing.alias_name}".',
    )
