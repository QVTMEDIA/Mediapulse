from collections import OrderedDict
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.concurrency import run_in_threadpool

from ..auth import get_current_user, require_role
from ..parsing import ParsedMediaRow, parse_brand_report, parse_composite_report
from ..repositories.brands import BrandsRepository, get_brands_repository
from ..repositories.calculations import CalculationsRepository, get_calculations_repository
from ..repositories.mapping_templates import MappingTemplatesRepository, get_mapping_templates_repository
from ..repositories.matches import MatchesRepository, get_matches_repository
from ..repositories.projects import ProjectsRepository, get_projects_repository
from ..repositories.uploads import (
    MediaActivityInsert,
    MediaActivityRecord,
    UploadRecord,
    UploadsRepository,
    get_uploads_repository,
)
from ..parsing import MappingWarning
from ..schemas.common import MappingWarningOut
from ..schemas.uploads import MediaActivityRowOut, UploadBatchOut, UploadJobOut
from ..upload_jobs import UploadJob, advance, get_upload_job, set_total, start_upload_job

router = APIRouter(prefix='/api/projects/{project_id}', tags=['uploads'], dependencies=[Depends(get_current_user)])

SUPPORTED_UPLOAD_KINDS = ('brand_report', 'composite_report')


def _upload_to_out(record: UploadRecord, mapping_warnings: 'list[MappingWarning] | None' = None) -> UploadBatchOut:
    return UploadBatchOut(
        upload_id=record.id,
        project_id=record.project_id,
        brand_id=record.brand_id,
        file_name=record.file_name,
        kind=record.kind,
        mapped_rows=record.mapped_rows,
        issue_rows=record.issue_rows,
        uploaded_at=record.uploaded_at,
        mapping_warnings=[
            MappingWarningOut(field=w.field, template_column=w.template_column, detected_column=w.detected_column)
            for w in (mapping_warnings or [])
        ],
    )


def _upload_job_to_out(job: UploadJob) -> UploadJobOut:
    return UploadJobOut(
        job_id=job.id, status=job.status, error=job.error, total=job.total, processed=job.processed,
        upload=job.result if job.result else None,
    )


def _activity_to_out(record: MediaActivityRecord) -> MediaActivityRowOut:
    return MediaActivityRowOut(
        media_activity_id=record.id,
        project_id=record.project_id,
        brand_id=record.brand_id,
        upload_id=record.upload_id,
        medium=record.medium,
        station=record.station,
        activity_date=record.activity_date,
        day=record.day,
        programme=record.programme,
        spots=record.spots,
        cost=record.cost,
        time_band=record.time_band,
        region=record.region,
        source_file=record.source_file,
    )


@router.get('/uploads', response_model=list[UploadBatchOut])
def list_uploads(
    project_id: str,
    repo: UploadsRepository = Depends(get_uploads_repository),
    projects_repo: ProjectsRepository = Depends(get_projects_repository),
):
    if projects_repo.get_project(project_id) is None:
        raise HTTPException(status_code=404, detail='Project not found')
    return [_upload_to_out(record) for record in repo.list_uploads(project_id)]


@router.post('/uploads', response_model=UploadBatchOut, status_code=201)
async def create_upload(
    project_id: str,
    kind: str = Form('brand_report'),
    brand_id: Optional[str] = Form(None),
    default_medium: str = Form('TV'),
    source_label: Optional[str] = Form(None),
    save_as_template: bool = Form(False),
    # Added alongside mappingWarnings (see parsing.py's MappingWarning): a
    # warning alone still left no way to actually act on a stale template
    # short of retyping a different source_label (losing the label's
    # identity/future auto-save) or clearing it entirely (which also drops
    # save_as_template's "remember this for next time" behavior). This
    # skips *applying* the saved template to this one upload without
    # touching what's stored — save_as_template (unchanged) is still the
    # only thing that overwrites it, so checking both together is the
    # one-shot "fix this stale template" workflow.
    ignore_saved_template: bool = Form(False),
    file: UploadFile = File(...),
    repo: UploadsRepository = Depends(get_uploads_repository),
    projects_repo: ProjectsRepository = Depends(get_projects_repository),
    brands_repo: BrandsRepository = Depends(get_brands_repository),
    templates_repo: MappingTemplatesRepository = Depends(get_mapping_templates_repository),
):
    """kind='brand_report' needs brand_id (one brand per file). kind=
    'composite_report' ignores brand_id — it reads a Brand column from the
    file itself and resolves/creates a brand per distinct name found, so a
    single upload can span several competitors at once. Either kind: if
    source_label is given and a saved mapping_template exists for it, that
    mapping is used instead of auto-detection (falling back to auto-detect
    per field if the template's column is missing from this particular
    file) — unless ignore_saved_template is set, which skips applying it
    for this one upload only (the stored template itself is untouched
    unless save_as_template is also set); the first successful upload for
    a not-yet-seen source_label (or any upload with save_as_template=true)
    saves the mapping actually used as a template, so later uploads from
    the same source map automatically. The response's mappingWarnings
    names any field where the template's column disagreed with what fresh
    auto-detection would have picked for this file — see parsing.py's
    MappingWarning for why that's worth surfacing rather than silently
    trusting the template."""
    if projects_repo.get_project(project_id) is None:
        raise HTTPException(status_code=404, detail='Project not found')
    if kind not in SUPPORTED_UPLOAD_KINDS:
        raise HTTPException(
            status_code=422,
            detail=f'Unsupported upload kind "{kind}". Supported: {", ".join(SUPPORTED_UPLOAD_KINDS)} '
            '(ratings uploads use POST /api/ratings-datasets/upload instead).',
        )
    if kind == 'brand_report':
        if not brand_id:
            raise HTTPException(status_code=422, detail='brand_id is required for kind=brand_report')
        if brands_repo.get_brand(project_id, brand_id) is None:
            raise HTTPException(status_code=404, detail='Brand not found for this project')

    existing_template = templates_repo.get_by_source_label(source_label) if source_label else None
    # Deliberately kept separate from mapping_override: ignore_saved_template
    # only decides what gets *applied* to this parse, not whether the save
    # logic below (which asks "did a template already exist for this label")
    # treats this as a fresh label.
    mapping_override = existing_template.field_mapping if existing_template and not ignore_saved_template else None

    data = await file.read()
    file_name = file.filename or 'uploaded_file'

    def _parse_and_build_inserts():
        # Synchronous (pandas parsing, plus brand_ids_by_name's per-distinct-
        # brand DB round trips for composite_report) -- run off the event
        # loop below via run_in_threadpool, same reasoning as
        # routers/ratings.py's upload endpoint: without it, a large file
        # freezes every other request this backend serves (including
        # Render's own health check) for as long as parsing+brand lookups
        # take. See db.py's insert_rows_batched for the matching fix on the
        # insert side, and CHANGELOG.md.
        if kind == 'brand_report':
            parsed = parse_brand_report(data, file_name, default_medium, mapping_override)
            inserts = [MediaActivityInsert(brand_id=brand_id, row=row) for row in parsed.rows]
            return inserts, brand_id, parsed.issue_rows, parsed.mapping, parsed.mapping_warnings
        composite = parse_composite_report(data, file_name, default_medium, mapping_override)
        brand_ids_by_name: "OrderedDict[str, str]" = OrderedDict()
        inserts = []
        for row in composite.rows:
            if row.brand_name not in brand_ids_by_name:
                brand_ids_by_name[row.brand_name] = brands_repo.get_or_create_brand(
                    project_id, row.brand_name
                ).id
            inserts.append(MediaActivityInsert(
                brand_id=brand_ids_by_name[row.brand_name],
                row=ParsedMediaRow(
                    medium=row.medium, station=row.station, activity_date=row.activity_date, day=row.day,
                    programme=row.programme, spots=row.spots, source_file=row.source_file,
                    source_row_number=None, cost=row.cost, time_band=row.time_band, region=row.region,
                ),
            ))
        return inserts, None, composite.issue_rows, composite.mapping, composite.mapping_warnings

    try:
        inserts, upload_brand_id, issue_rows, mapping_used, mapping_warnings = await run_in_threadpool(
            _parse_and_build_inserts
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    if source_label and (existing_template is None or save_as_template):
        templates_repo.save_template(source_label, mapping_used)
    elif source_label:
        templates_repo.touch_used(source_label)

    upload_record, _activity_records = await run_in_threadpool(
        repo.create_upload_with_activity, project_id, upload_brand_id, file_name, kind, inserts, issue_rows=issue_rows
    )
    return _upload_to_out(upload_record, mapping_warnings)


def _build_project_upload_inserts(project_id, kind, brand_id, default_medium, mapping_override, data, file_name, brands_repo):
    """Parsing + insert-row-building half of create_upload above, factored
    out so _run_project_upload_job below (which needs it to run entirely
    inside a background job thread, not via run_in_threadpool awaited from
    the request handler) and create_upload's own closure don't duplicate
    the brand_report/composite_report branching."""
    if kind == 'brand_report':
        parsed = parse_brand_report(data, file_name, default_medium, mapping_override)
        inserts = [MediaActivityInsert(brand_id=brand_id, row=row) for row in parsed.rows]
        return inserts, brand_id, parsed.issue_rows, parsed.mapping, parsed.mapping_warnings
    composite = parse_composite_report(data, file_name, default_medium, mapping_override)
    brand_ids_by_name: "OrderedDict[str, str]" = OrderedDict()
    inserts = []
    for row in composite.rows:
        if row.brand_name not in brand_ids_by_name:
            brand_ids_by_name[row.brand_name] = brands_repo.get_or_create_brand(project_id, row.brand_name).id
        inserts.append(MediaActivityInsert(
            brand_id=brand_ids_by_name[row.brand_name],
            row=ParsedMediaRow(
                medium=row.medium, station=row.station, activity_date=row.activity_date, day=row.day,
                programme=row.programme, spots=row.spots, source_file=row.source_file,
                source_row_number=None, cost=row.cost, time_band=row.time_band, region=row.region,
            ),
        ))
    return inserts, None, composite.issue_rows, composite.mapping, composite.mapping_warnings


def _run_project_upload_job(
    job_id, project_id, kind, brand_id, default_medium, mapping_override, data, file_name,
    source_label, save_as_template, existing_template, repo, brands_repo, templates_repo,
) -> UploadBatchOut:
    """Runs entirely in upload_jobs.py's background thread -- parsing and
    the mapping-template save/touch happen here too (not back on the event
    loop the way create_upload's run_in_threadpool version does), so this
    is the only place that does either for a job-based upload. total is
    set as soon as parsing tells us how many rows there are to insert;
    insert_rows_batched's on_batch callback (threaded through
    create_upload_with_activity) advances processed per real batch landed,
    not a simulated percentage."""
    inserts, upload_brand_id, issue_rows, mapping_used, mapping_warnings = _build_project_upload_inserts(
        project_id, kind, brand_id, default_medium, mapping_override, data, file_name, brands_repo
    )
    set_total(job_id, len(inserts))

    if source_label and (existing_template is None or save_as_template):
        templates_repo.save_template(source_label, mapping_used)
    elif source_label:
        templates_repo.touch_used(source_label)

    upload_record, _activity_records = repo.create_upload_with_activity(
        project_id, upload_brand_id, file_name, kind, inserts, issue_rows=issue_rows,
        on_batch=lambda n: advance(job_id, n),
    )
    return _upload_to_out(upload_record, mapping_warnings)


@router.post('/uploads/jobs', response_model=UploadJobOut, status_code=202)
async def start_upload_job_route(
    project_id: str,
    kind: str = Form('brand_report'),
    brand_id: Optional[str] = Form(None),
    default_medium: str = Form('TV'),
    source_label: Optional[str] = Form(None),
    save_as_template: bool = Form(False),
    ignore_saved_template: bool = Form(False),
    file: UploadFile = File(...),
    repo: UploadsRepository = Depends(get_uploads_repository),
    projects_repo: ProjectsRepository = Depends(get_projects_repository),
    brands_repo: BrandsRepository = Depends(get_brands_repository),
    templates_repo: MappingTemplatesRepository = Depends(get_mapping_templates_repository),
):
    """Job-based twin of POST .../uploads, for a real progress bar (see
    app/upload_jobs.py) instead of blocking the whole request until
    parsing + the insert finish -- same validation, parsing, and mapping-
    template behavior otherwise. Poll via GET .../uploads/jobs/{jobId}."""
    if projects_repo.get_project(project_id) is None:
        raise HTTPException(status_code=404, detail='Project not found')
    if kind not in SUPPORTED_UPLOAD_KINDS:
        raise HTTPException(
            status_code=422,
            detail=f'Unsupported upload kind "{kind}". Supported: {", ".join(SUPPORTED_UPLOAD_KINDS)} '
            '(ratings uploads use POST /api/ratings-datasets/upload/jobs instead).',
        )
    if kind == 'brand_report':
        if not brand_id:
            raise HTTPException(status_code=422, detail='brand_id is required for kind=brand_report')
        if brands_repo.get_brand(project_id, brand_id) is None:
            raise HTTPException(status_code=404, detail='Brand not found for this project')

    existing_template = templates_repo.get_by_source_label(source_label) if source_label else None
    mapping_override = existing_template.field_mapping if existing_template and not ignore_saved_template else None

    data = await file.read()
    file_name = file.filename or 'uploaded_file'

    job = start_upload_job(
        _run_project_upload_job, project_id, kind, brand_id, default_medium, mapping_override, data, file_name,
        source_label, save_as_template, existing_template, repo, brands_repo, templates_repo,
        scope=project_id,
    )
    return _upload_job_to_out(job)


@router.get('/uploads/jobs/{job_id}', response_model=UploadJobOut)
def get_upload_job_route(
    project_id: str, job_id: str, projects_repo: ProjectsRepository = Depends(get_projects_repository)
):
    if projects_repo.get_project(project_id) is None:
        raise HTTPException(status_code=404, detail='Project not found')
    job = get_upload_job(job_id)
    if job is None or job.scope != project_id:
        raise HTTPException(status_code=404, detail='Upload job not found for this project')
    return _upload_job_to_out(job)


@router.delete('/uploads/{upload_id}', status_code=204)
def delete_upload(
    project_id: str,
    upload_id: str,
    repo: UploadsRepository = Depends(get_uploads_repository),
    projects_repo: ProjectsRepository = Depends(get_projects_repository),
    matches_repo: MatchesRepository = Depends(get_matches_repository),
    calculations_repo: CalculationsRepository = Depends(get_calculations_repository),
    _current_user=Depends(require_role('owner', 'admin')),
):
    """Data-management action (PRODUCT_ROADMAP.md's Project Settings row).
    Refuses (409) if any of this upload's media_activity rows were ever
    included in a calculated run — deleting it would silently rewrite that
    run's audit trail, which the whole point of grp_calculations is to
    prevent. An upload that was never calculated (a duplicate, a mistake
    caught before clicking Calculate) can always be removed."""
    if projects_repo.get_project(project_id) is None:
        raise HTTPException(status_code=404, detail='Project not found')
    activity_ids = [a.id for a in repo.list_media_activity(project_id) if a.upload_id == upload_id]
    if not activity_ids and not any(u.id == upload_id for u in repo.list_uploads(project_id)):
        raise HTTPException(status_code=404, detail='Upload not found for this project')
    if calculations_repo.has_calculations_for_media_activity(activity_ids):
        raise HTTPException(
            status_code=409,
            detail='This upload has already been included in a calculated run and cannot be deleted, '
            'to protect that run\'s audit trail. Archive or delete the project instead if you need to retire it.',
        )
    matches_repo.delete_matches_for_media_activity(activity_ids)
    if not repo.delete_upload(project_id, upload_id):
        raise HTTPException(status_code=404, detail='Upload not found for this project')


@router.get('/media-activity', response_model=list[MediaActivityRowOut])
def list_media_activity(
    project_id: str,
    repo: UploadsRepository = Depends(get_uploads_repository),
    projects_repo: ProjectsRepository = Depends(get_projects_repository),
):
    if projects_repo.get_project(project_id) is None:
        raise HTTPException(status_code=404, detail='Project not found')
    return [_activity_to_out(record) for record in repo.list_media_activity(project_id)]
