from fastapi import APIRouter, Depends, HTTPException, Response

from ..auth import get_current_user
from ..exports import TEMPLATE_MIME, build_workbook
from ..repositories.brands import BrandsRepository, get_brands_repository
from ..repositories.calculations import CalculationsRepository, get_calculations_repository
from ..repositories.exports import VALID_FORMATS, ExportsRepository, get_exports_repository
from ..repositories.matches import MatchesRepository, get_matches_repository
from ..repositories.projects import ProjectsRepository, get_projects_repository
from ..repositories.ratings import RatingsRepository, get_ratings_repository
from ..repositories.uploads import UploadsRepository, get_uploads_repository
from ..repositories.users import UserRecord
from ..schemas.exports import ExportCreate, ExportJobOut

router = APIRouter(prefix='/api/projects/{project_id}/exports', tags=['exports'], dependencies=[Depends(get_current_user)])


def _to_out(record) -> ExportJobOut:
    return ExportJobOut(
        export_id=record.id,
        project_id=record.project_id,
        run_id=record.run_id,
        format=record.format,
        generated_at=record.generated_at,
        download_url=f'/api/projects/{record.project_id}/exports/{record.id}/download',
    )


@router.post('', response_model=ExportJobOut, status_code=201)
def create_export(
    project_id: str,
    payload: ExportCreate,
    projects_repo: ProjectsRepository = Depends(get_projects_repository),
    calculations_repo: CalculationsRepository = Depends(get_calculations_repository),
    exports_repo: ExportsRepository = Depends(get_exports_repository),
    current_user: UserRecord = Depends(get_current_user),
):
    """Only records which run this export is for — the workbook itself is
    built on demand by GET .../download, not here, so this stays fast
    regardless of how much calculated history a project has."""
    if projects_repo.get_project(project_id) is None:
        raise HTTPException(status_code=404, detail='Project not found')
    if payload.format not in VALID_FORMATS:
        raise HTTPException(
            status_code=422,
            detail=f'format must be one of {", ".join(VALID_FORMATS)} — xlsx_summary/pdf/csv are not built yet (see PRODUCT_ROADMAP.md).',
        )

    if payload.run_id is not None:
        run = next((r for r in calculations_repo.list_runs(project_id) if r.id == payload.run_id), None)
        if run is None:
            raise HTTPException(status_code=404, detail='Run not found for this project')
        run_id = run.id
    else:
        # Frozen here, not re-resolved at download time — so downloading
        # this export next week still reflects "the run that was current
        # when this export was requested," even if a newer run (or a
        # version-history restore) has since changed what
        # GET .../runs/latest returns. An export is a point-in-time
        # artifact, not a live view — consistent with the audit rule this
        # schema exists to satisfy.
        latest = calculations_repo.get_latest_run(project_id)
        run_id = latest.id if latest else None

    record = exports_repo.create_export(project_id, run_id, payload.format, current_user.id)
    return _to_out(record)


@router.get('', response_model=list[ExportJobOut])
def list_exports(
    project_id: str,
    projects_repo: ProjectsRepository = Depends(get_projects_repository),
    exports_repo: ExportsRepository = Depends(get_exports_repository),
):
    if projects_repo.get_project(project_id) is None:
        raise HTTPException(status_code=404, detail='Project not found')
    return [_to_out(record) for record in exports_repo.list_exports(project_id)]


@router.get('/{export_id}', response_model=ExportJobOut)
def get_export(
    project_id: str,
    export_id: str,
    projects_repo: ProjectsRepository = Depends(get_projects_repository),
    exports_repo: ExportsRepository = Depends(get_exports_repository),
):
    if projects_repo.get_project(project_id) is None:
        raise HTTPException(status_code=404, detail='Project not found')
    record = exports_repo.get_export(project_id, export_id)
    if record is None:
        raise HTTPException(status_code=404, detail='Export not found for this project')
    return _to_out(record)


@router.get('/{export_id}/download')
def download_export(
    project_id: str,
    export_id: str,
    projects_repo: ProjectsRepository = Depends(get_projects_repository),
    exports_repo: ExportsRepository = Depends(get_exports_repository),
    calculations_repo: CalculationsRepository = Depends(get_calculations_repository),
    brands_repo: BrandsRepository = Depends(get_brands_repository),
    uploads_repo: UploadsRepository = Depends(get_uploads_repository),
    matches_repo: MatchesRepository = Depends(get_matches_repository),
    ratings_repo: RatingsRepository = Depends(get_ratings_repository),
):
    """Not in API_CONTRACT.md's original route list (which only specified a
    downloadUrl field, not a route shape for it) — regenerates the .xlsx
    from the export's frozen run_id on every call rather than reading a
    stored file, since no object storage is configured in this environment
    (see the comment on PostgresExportsRepository in
    app/repositories/exports.py). The regenerated bytes are identical every
    time for a given export: grp_calculations/brand_shares/the
    station+programme views are immutable per run — nothing about a past
    run's calculated rows changes after the fact. Ratings/matches used for
    "Unmatched Records" are project-wide state, not run-scoped (matching
    isn't frozen per run the way calculation results are), so that one
    sheet reflects the project's current match state, not a point-in-time
    snapshot — documented here since it's the one sheet where that's true."""
    project = projects_repo.get_project(project_id)
    if project is None:
        raise HTTPException(status_code=404, detail='Project not found')
    record = exports_repo.get_export(project_id, export_id)
    if record is None:
        raise HTTPException(status_code=404, detail='Export not found for this project')

    run = None
    brand_shares: list = []
    calculations: list = []
    station_shares: list = []
    programme_shares: list = []
    if record.run_id is not None:
        run = next((r for r in calculations_repo.list_runs(project_id) if r.id == record.run_id), None)
        brand_shares = calculations_repo.list_brand_shares(project_id, record.run_id) or []
        calculations = calculations_repo.list_calculations(project_id, record.run_id) or []
        station_shares = calculations_repo.list_station_shares(project_id, record.run_id) or []
        programme_shares = calculations_repo.list_programme_shares(project_id, record.run_id) or []

    def _brand_name(brand_id: str) -> str:
        brand = brands_repo.get_brand(project_id, brand_id)
        return brand.name if brand else 'Unknown brand'

    brand_shares_out = [
        {
            'brand': _brand_name(s.brand_id), 'total_grps': s.total_grps, 'tv_grps': s.tv_grps,
            'radio_grps': s.radio_grps, 'sov': s.sov, 'spots': s.spots, 'avg_rating': s.avg_rating,
        }
        for s in brand_shares
    ]
    calculations_out = [
        {
            'brand': _brand_name(row.brand_id), 'station': row.station, 'programme': row.programme,
            'day': row.day, 'medium': row.medium, 'spots': row.spots, 'rating': row.rating,
            'grp': row.grp, 'calculated_at': row.calculated_at,
        }
        for row in calculations
    ]
    station_out = [
        {'brand': _brand_name(s.brand_id), 'station': s.station, 'total_grps': s.total_grps, 'spots': s.spots}
        for s in station_shares
    ]
    programme_out = [
        {'brand': _brand_name(s.brand_id), 'programme': s.programme, 'total_grps': s.total_grps, 'spots': s.spots}
        for s in programme_shares
    ]

    media_activity_by_id = {row.id: row for row in uploads_repo.list_media_activity(project_id)}
    unmatched_out = []
    for match in matches_repo.list_matches(project_id):
        if match.match_status != 'unmatched':
            continue
        activity = media_activity_by_id.get(match.media_activity_id)
        if activity is None:
            continue
        unmatched_out.append({
            'brand': _brand_name(activity.brand_id), 'medium': activity.medium, 'station': activity.station,
            'programme': activity.programme, 'day': activity.day, 'spots': activity.spots,
            'match_status': match.match_status,
        })

    ratings_out = [
        {'medium': r.medium, 'station': r.station, 'day': r.day, 'programme': r.programme,
         'time_band': r.time_band, 'rating': r.rating}
        for r in ratings_repo.list_project_rating_rows(project_id)
    ]

    workbook_bytes = build_workbook(
        project=project, run=run, brand_shares=brand_shares_out, calculations=calculations_out,
        station_shares=station_out, programme_shares=programme_out, unmatched_rows=unmatched_out,
        ratings_rows=ratings_out, generated_at=str(record.generated_at),
    )
    safe_name = ''.join(c if c.isalnum() or c in ' -_' else '_' for c in project.name).strip() or 'mediapulse'
    file_name = f'{safe_name.replace(" ", "_")}_export.xlsx'
    return Response(
        content=workbook_bytes,
        media_type=TEMPLATE_MIME,
        headers={'Content-Disposition': f'attachment; filename="{file_name}"'},
    )
