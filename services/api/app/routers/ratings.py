from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile
from pydantic import ValidationError

from ..auth import get_current_user
from ..parsing import parse_ratings_file
from ..repositories.mapping_templates import MappingTemplatesRepository, get_mapping_templates_repository
from ..repositories.projects import ProjectsRepository, get_projects_repository
from ..repositories.ratings import (
    RatingsDatasetRecord,
    RatingsRepository,
    get_ratings_repository,
)
from ..parsing import MappingWarning, RatingsRowIssue
from ..schemas.common import MappingWarningOut
from ..schemas.ratings import RatingRowOut, RatingsDatasetCreate, RatingsDatasetOut, RatingsRowIssueOut

router = APIRouter(prefix='/api', tags=['ratings-library'], dependencies=[Depends(get_current_user)])

# Cap on how many dropped-row explanations the upload response carries — a
# file that rejects thousands of rows shouldn't balloon the response; the
# dataset's own invalidRows count still reports the true total regardless.
MAX_REPORTED_ISSUES = 100


def _dataset_to_out(
    record: RatingsDatasetRecord,
    issues: Optional[List[RatingsRowIssue]] = None,
    mapping_warnings: Optional[List[MappingWarning]] = None,
) -> RatingsDatasetOut:
    return RatingsDatasetOut(
        ratings_dataset_id=record.id,
        provider=record.provider,
        period=record.period,
        market=record.market,
        audience=record.audience,
        media_types=record.media_types,
        rows=record.row_count,
        invalid_rows=record.invalid_rows,
        duplicate_keys=record.duplicate_keys,
        status=record.status,
        uploaded_at=record.uploaded_at,
        issues=(
            [
                RatingsRowIssueOut(
                    row_number=issue.row_number, reason=issue.reason, medium=issue.medium, station=issue.station,
                    day=issue.day, programme=issue.programme, rating=issue.rating,
                )
                for issue in issues[:MAX_REPORTED_ISSUES]
            ]
            if issues
            else None
        ),
        mapping_warnings=[
            MappingWarningOut(field=w.field, template_column=w.template_column, detected_column=w.detected_column)
            for w in (mapping_warnings or [])
        ],
    )


def _row_to_out(record) -> RatingRowOut:
    return RatingRowOut(
        rating_row_id=record.id,
        ratings_dataset_id=record.ratings_dataset_id,
        medium=record.medium,
        station=record.station,
        day=record.day,
        programme=record.programme,
        time_band=record.time_band,
        rating=record.rating,
        start_time=record.start_time,
        end_time=record.end_time,
        week=record.week,
        month=record.month,
    )


@router.get('/ratings-datasets', response_model=list[RatingsDatasetOut])
def list_ratings_datasets(
    search: str = Query(default=''),
    market: Optional[str] = Query(default=None),
    repo: RatingsRepository = Depends(get_ratings_repository),
):
    return [_dataset_to_out(record) for record in repo.list_datasets(search=search, market=market)]


@router.post('/ratings-datasets', response_model=RatingsDatasetOut, status_code=201)
def create_ratings_dataset(
    payload: RatingsDatasetCreate,
    repo: RatingsRepository = Depends(get_ratings_repository),
):
    return _dataset_to_out(repo.create_dataset(payload))


@router.post('/ratings-datasets/upload', response_model=RatingsDatasetOut, status_code=201)
async def upload_ratings_dataset(
    provider: str = Form(''),
    period: str = Form(''),
    market: str = Form(''),
    audience: str = Form(''),
    media_types: str = Form(''),  # comma-separated, e.g. "TV,Radio" — see MEDIA_TYPE_OPTIONS
    default_medium: str = Form('TV'),
    source_label: Optional[str] = Form(None),
    save_as_template: bool = Form(False),
    # See routers/uploads.py's identical parameter for the full rationale:
    # skips applying a saved template to this one upload without touching
    # what's stored — save_as_template is still the only thing that
    # overwrites it.
    ignore_saved_template: bool = Form(False),
    file: UploadFile = File(...),
    repo: RatingsRepository = Depends(get_ratings_repository),
    templates_repo: MappingTemplatesRepository = Depends(get_mapping_templates_repository),
):
    """Real spreadsheet parsing (header inference, column-synonym detection,
    the same 0-100 rating range / required-field validation grp_calculator's
    Streamlit ratings flow uses) via app/parsing.py, rather than requiring
    rows as a JSON array like POST /ratings-datasets does. source_label works
    the same way as on the media-report upload endpoints: a saved
    mapping_template for that label is applied instead of auto-detection
    (unless ignore_saved_template skips it for this one upload), and a
    not-yet-seen label (or save_as_template=true) saves the mapping
    actually used — see routers/uploads.py for the shared rationale. The
    response's mappingWarnings names any field where the template's column
    disagreed with fresh auto-detection for this file (also shared with
    routers/uploads.py — see parsing.py's MappingWarning)."""
    existing_template = templates_repo.get_by_source_label(source_label) if source_label else None
    mapping_override = existing_template.field_mapping if existing_template and not ignore_saved_template else None

    data = await file.read()
    file_name = file.filename or 'uploaded_file'
    try:
        parsed = parse_ratings_file(data, file_name, default_medium, mapping_override)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    parsed_media_types = [item.strip() for item in media_types.split(',') if item.strip()]
    try:
        payload = RatingsDatasetCreate(
            provider=provider, period=period, market=market, audience=audience,
            media_types=parsed_media_types, rows=parsed.rows,
        )
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    if source_label and (existing_template is None or save_as_template):
        templates_repo.save_template(source_label, parsed.mapping)
    elif source_label:
        templates_repo.touch_used(source_label)

    return _dataset_to_out(
        repo.create_dataset(payload, extra_invalid_rows=parsed.dropped_invalid_rows),
        issues=parsed.issues,
        mapping_warnings=parsed.mapping_warnings,
    )


@router.get('/ratings-datasets/{ratings_dataset_id}/rows', response_model=list[RatingRowOut])
def list_ratings_dataset_rows(
    ratings_dataset_id: str,
    repo: RatingsRepository = Depends(get_ratings_repository),
):
    rows = repo.list_rows(ratings_dataset_id)
    if rows is None:
        raise HTTPException(status_code=404, detail='Ratings dataset not found')
    return [_row_to_out(row) for row in rows]


@router.post('/projects/{project_id}/ratings-datasets/{ratings_dataset_id}/attach', status_code=204)
def attach_ratings_dataset(
    project_id: str,
    ratings_dataset_id: str,
    repo: RatingsRepository = Depends(get_ratings_repository),
    projects_repo: ProjectsRepository = Depends(get_projects_repository),
):
    if projects_repo.get_project(project_id) is None:
        raise HTTPException(status_code=404, detail='Project not found')
    if not repo.attach_to_project(project_id, ratings_dataset_id):
        raise HTTPException(status_code=404, detail='Ratings dataset not found')


@router.delete('/projects/{project_id}/ratings-datasets/{ratings_dataset_id}/attach', status_code=204)
def detach_ratings_dataset(
    project_id: str,
    ratings_dataset_id: str,
    repo: RatingsRepository = Depends(get_ratings_repository),
    projects_repo: ProjectsRepository = Depends(get_projects_repository),
):
    """Data-management action (PRODUCT_ROADMAP.md's Project Settings row).
    Unlike deleting an upload/brand, this needs no audit-trail guard: it
    only removes the project_ratings_datasets join row. The shared
    ratings_datasets/ratings rows are untouched (other projects may still
    use them), and so is anything already calculated — rating_matches and
    grp_calculations reference actual ratings rows directly, not the
    attachment. Detaching only affects future matching for this project."""
    if projects_repo.get_project(project_id) is None:
        raise HTTPException(status_code=404, detail='Project not found')
    if not repo.detach_from_project(project_id, ratings_dataset_id):
        raise HTTPException(status_code=404, detail='Ratings dataset is not attached to this project')


@router.get('/projects/{project_id}/ratings-datasets', response_model=list[RatingsDatasetOut])
def list_project_ratings_datasets(
    project_id: str,
    repo: RatingsRepository = Depends(get_ratings_repository),
):
    return [_dataset_to_out(record) for record in repo.list_project_datasets(project_id)]
