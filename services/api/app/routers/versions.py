from fastapi import APIRouter, Depends, HTTPException

from ..auth import get_current_user, require_role
from ..repositories.calculations import CalculationsRepository, get_calculations_repository
from ..repositories.projects import ProjectsRepository, get_projects_repository
from ..repositories.users import UserRecord
from ..schemas.versions import ProjectVersionOut

router = APIRouter(prefix='/api/projects/{project_id}/versions', tags=['versions'], dependencies=[Depends(get_current_user)])


def _describe(record) -> str:
    return (
        f'{record.total_brands} brand{"s" if record.total_brands != 1 else ""}, '
        f'{record.total_spots} spot{"s" if record.total_spots != 1 else ""}, '
        f'{record.total_grps:.1f} GRPs '
        f'({record.matched_rows} matched, {record.unmatched_rows} unmatched)'
    )


def _to_out(record) -> ProjectVersionOut:
    return ProjectVersionOut(
        version_id=record.id,
        project_id=record.project_id,
        run_id=record.id,
        description=_describe(record),
        is_current=record.is_current,
        created_at=record.generated_at,
    )


@router.get('', response_model=list[ProjectVersionOut])
def list_versions(
    project_id: str,
    calculations_repo: CalculationsRepository = Depends(get_calculations_repository),
    projects_repo: ProjectsRepository = Depends(get_projects_repository),
):
    """Per PRODUCT_ROADMAP.md: 'each recalculation ... becomes a version
    with a timestamp' — every grp_runs row already is exactly that, so this
    is computed on read (same pattern as GET .../validation-issues) rather
    than a second write path duplicating what create_run already records."""
    if projects_repo.get_project(project_id) is None:
        raise HTTPException(status_code=404, detail='Project not found')
    return [_to_out(record) for record in calculations_repo.list_runs(project_id)]


@router.post('/{version_id}/restore', response_model=ProjectVersionOut)
def restore_version(
    project_id: str,
    version_id: str,
    calculations_repo: CalculationsRepository = Depends(get_calculations_repository),
    projects_repo: ProjectsRepository = Depends(get_projects_repository),
    _current_user: UserRecord = Depends(require_role('owner', 'admin')),
):
    """Pins GET .../runs/latest (and therefore the Overview/Reports/Activity
    screens) back to an earlier run, without deleting the newer one or
    anything it calculated — every run's grp_calculations rows stay put
    regardless of which run is 'current'. Role-gated the same as
    archiving/deleting a project: it changes what everyone sees as the
    project's current numbers, not just the caller's own view."""
    if projects_repo.get_project(project_id) is None:
        raise HTTPException(status_code=404, detail='Project not found')
    record = calculations_repo.restore_run(project_id, version_id)
    if record is None:
        raise HTTPException(status_code=404, detail='Version not found for this project')
    return _to_out(record)
