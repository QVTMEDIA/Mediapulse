from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from ..auth import get_current_user, require_role
from ..repositories.activity_log import ActivityLogRepository, get_activity_log_repository
from ..repositories.projects import (
    ProjectRecord,
    ProjectsRepository,
    get_projects_repository,
)
from ..repositories.users import UserRecord
from ..schemas.projects import ProjectCreate, ProjectOut, ProjectUpdate

# Baseline: every route needs a logged-in user (any role). Archiving and
# deleting additionally require owner/admin — enforced per-route below,
# since PATCH handles both a plain field edit (any role) and the
# archive/unarchive toggle (owner/admin only) through the same endpoint.
router = APIRouter(prefix='/api/projects', tags=['projects'], dependencies=[Depends(get_current_user)])


def _to_out(record: ProjectRecord) -> ProjectOut:
    return ProjectOut(
        project_id=record.id,
        project_name=record.name,
        project_owner=record.owner_name,
        client=record.client,
        category=record.category,
        market=record.market,
        start_date=record.start_date,
        end_date=record.end_date,
        target_audience=record.target_audience,
        media_types=record.media_types,
        ratings_provider=record.ratings_provider,
        ratings_period=record.ratings_period,
        status=record.status,
        archived=record.archived,
        notes=record.notes,
        created_at=record.created_at,
        updated_at=record.updated_at,
    )


@router.get('', response_model=list[ProjectOut])
def list_projects(
    search: str = Query(default=''),
    status: Optional[str] = Query(default=None),
    include_archived: bool = Query(default=True),
    repo: ProjectsRepository = Depends(get_projects_repository),
):
    records = repo.list_projects(search=search, status=status, include_archived=include_archived)
    return [_to_out(record) for record in records]


@router.post('', response_model=ProjectOut, status_code=201)
def create_project(
    payload: ProjectCreate,
    repo: ProjectsRepository = Depends(get_projects_repository),
    current_user: UserRecord = Depends(get_current_user),
    activity_repo: ActivityLogRepository = Depends(get_activity_log_repository),
):
    record = repo.create_project(payload)
    activity_repo.record(
        actor_id=current_user.id, actor_name=current_user.display_name, action='project.created',
        summary=f'{current_user.display_name} created project "{record.name}".',
        project_id=record.id, project_name=record.name,
    )
    return _to_out(record)


@router.get('/{project_id}', response_model=ProjectOut)
def get_project(project_id: str, repo: ProjectsRepository = Depends(get_projects_repository)):
    record = repo.get_project(project_id)
    if record is None:
        raise HTTPException(status_code=404, detail='Project not found')
    return _to_out(record)


@router.patch('/{project_id}', response_model=ProjectOut)
def update_project(
    project_id: str,
    payload: ProjectUpdate,
    repo: ProjectsRepository = Depends(get_projects_repository),
    current_user: UserRecord = Depends(get_current_user),
    activity_repo: ActivityLogRepository = Depends(get_activity_log_repository),
):
    # Archiving/unarchiving is a role-gated action; every other field on this
    # same endpoint is editable by any logged-in user. `exclude_unset` so a
    # patch that never mentions `archived` at all doesn't trip this check.
    if 'archived' in payload.model_fields_set and current_user.role not in ('owner', 'admin'):
        raise HTTPException(status_code=403, detail='Only an owner or admin can archive or unarchive a project.')
    record = repo.update_project(project_id, payload)
    if record is None:
        raise HTTPException(status_code=404, detail='Project not found')
    if 'archived' in payload.model_fields_set:
        action = 'project.archived' if record.archived else 'project.unarchived'
        verb = 'archived' if record.archived else 'unarchived'
        activity_repo.record(
            actor_id=current_user.id, actor_name=current_user.display_name, action=action,
            summary=f'{current_user.display_name} {verb} project "{record.name}".',
            project_id=record.id, project_name=record.name,
        )
    return _to_out(record)


@router.delete('/{project_id}', status_code=204)
def delete_project(
    project_id: str,
    repo: ProjectsRepository = Depends(get_projects_repository),
    current_user: UserRecord = Depends(require_role('owner', 'admin')),
    activity_repo: ActivityLogRepository = Depends(get_activity_log_repository),
):
    # Fetched before deleting, purely so the activity-log entry below can
    # name the project -- repo.delete_project itself only returns a bool.
    record = repo.get_project(project_id)
    if record is None or not repo.delete_project(project_id):
        raise HTTPException(status_code=404, detail='Project not found')
    activity_repo.record(
        actor_id=current_user.id, actor_name=current_user.display_name, action='project.deleted',
        summary=f'{current_user.display_name} deleted project "{record.name}".',
    )


@router.post('/{project_id}/duplicate', response_model=ProjectOut, status_code=201)
def duplicate_project(
    project_id: str,
    repo: ProjectsRepository = Depends(get_projects_repository),
    current_user: UserRecord = Depends(get_current_user),
    activity_repo: ActivityLogRepository = Depends(get_activity_log_repository),
):
    record = repo.duplicate_project(project_id)
    if record is None:
        raise HTTPException(status_code=404, detail='Project not found')
    activity_repo.record(
        actor_id=current_user.id, actor_name=current_user.display_name, action='project.duplicated',
        summary=f'{current_user.display_name} duplicated a project as "{record.name}".',
        project_id=record.id, project_name=record.name,
    )
    return _to_out(record)
