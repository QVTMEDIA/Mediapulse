from fastapi import APIRouter, Depends, HTTPException

from ..auth import get_current_user
from ..repositories.projects import ProjectsRepository, get_projects_repository
from ..repositories.ratings import RatingsRepository, get_ratings_repository
from ..repositories.uploads import UploadsRepository, get_uploads_repository
from ..schemas.validation import ValidationIssueOut

router = APIRouter(prefix='/api/projects/{project_id}', tags=['data-quality'], dependencies=[Depends(get_current_user)])


@router.get('/validation-issues', response_model=list[ValidationIssueOut])
def list_validation_issues(
    project_id: str,
    projects_repo: ProjectsRepository = Depends(get_projects_repository),
    ratings_repo: RatingsRepository = Depends(get_ratings_repository),
    uploads_repo: UploadsRepository = Depends(get_uploads_repository),
):
    """Computed on read from data already tracked elsewhere (ratings
    datasets' invalidRows/duplicateKeys, uploads' issueRows) rather than a
    persisted issue log — `db/schema.sql`'s `validation_issues` table isn't
    written to yet. Not run-scoped (`runId` is always null here): these are
    data-quality signals on the ratings/uploads themselves, independent of
    any particular calculation run."""
    if projects_repo.get_project(project_id) is None:
        raise HTTPException(status_code=404, detail='Project not found')

    issues: list[ValidationIssueOut] = []

    for dataset in ratings_repo.list_project_datasets(project_id):
        label = f'Ratings — {dataset.provider or "Untitled dataset"}'
        if dataset.invalid_rows:
            issues.append(ValidationIssueOut(
                issue_id=f'ratings-{dataset.id}-invalid',
                project_id=project_id,
                severity='warning',
                area=label,
                message=f'{dataset.invalid_rows} rating row(s) are missing a required field or have an '
                         'out-of-range rating and were excluded.',
                rows=dataset.invalid_rows,
            ))
        if dataset.duplicate_keys:
            issues.append(ValidationIssueOut(
                issue_id=f'ratings-{dataset.id}-duplicates',
                project_id=project_id,
                severity='warning',
                area=label,
                message=f'{dataset.duplicate_keys} station/day/programme key(s) have more than one rating row.',
                rows=dataset.duplicate_keys,
            ))

    for upload in uploads_repo.list_uploads(project_id):
        if upload.issue_rows:
            issues.append(ValidationIssueOut(
                issue_id=f'upload-{upload.id}-issues',
                project_id=project_id,
                severity='warning',
                area=f'Upload — {upload.file_name}',
                message=f'{upload.issue_rows} row(s) were skipped: missing a match field or an invalid spot count.',
                rows=upload.issue_rows,
            ))

    return issues
