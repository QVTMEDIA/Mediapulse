from fastapi import APIRouter, Depends, Query

from ..auth import get_current_user
from ..repositories.activity_log import ActivityLogRepository, get_activity_log_repository
from ..schemas.activity_log import ActivityLogEntryOut, ActivityLogPageOut

router = APIRouter(prefix='/api/activity-log', tags=['activity-log'], dependencies=[Depends(get_current_user)])

PAGE_SIZE_DEFAULT = 20
PAGE_SIZE_MAX = 100


def _to_out(entry) -> ActivityLogEntryOut:
    return ActivityLogEntryOut(
        entry_id=entry.id,
        actor_id=entry.actor_id,
        actor_name=entry.actor_name,
        action=entry.action,
        summary=entry.summary,
        project_id=entry.project_id,
        project_name=entry.project_name,
        created_at=entry.created_at,
    )


@router.get('', response_model=ActivityLogPageOut)
def list_activity_log(
    limit: int = Query(default=PAGE_SIZE_DEFAULT, ge=1, le=PAGE_SIZE_MAX),
    offset: int = Query(default=0, ge=0),
    repo: ActivityLogRepository = Depends(get_activity_log_repository),
):
    """Account-wide, not scoped to one project -- every signed-in user can
    see it, same visibility as the Team panel in Settings (see
    db/schema.sql's activity_log comment for why this matches `users.role`
    being global rather than per-project). Paginated rather than the whole
    account's history in one response, same reasoning as
    GET .../ratings-datasets/{id}/rows."""
    page = repo.list_entries(limit=limit, offset=offset)
    return ActivityLogPageOut(entries=[_to_out(entry) for entry in page.entries], total=page.total)
