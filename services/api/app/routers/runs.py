from fastapi import APIRouter, Depends, HTTPException

from ..auth import get_current_user
from ..calculations import compute_run
from ..calculation_jobs import get_calculation_job, start_calculation_job
from ..repositories.brands import BrandsRepository, get_brands_repository
from ..repositories.calculations import CalculationsRepository, get_calculations_repository
from ..repositories.matches import MatchesRepository, get_matches_repository
from ..repositories.projects import ProjectsRepository, get_projects_repository
from ..repositories.ratings import RatingsRepository, get_ratings_repository
from ..repositories.uploads import UploadsRepository, get_uploads_repository
from ..schemas.calculations import (
    BrandShareOut,
    CalculationJobOut,
    DaypartShareOut,
    GrpCalculationRowOut,
    GrpRunSummaryOut,
    ProgrammeShareOut,
    SpotEfficiencyOut,
    StationShareOut,
    TrendPointOut,
)

router = APIRouter(prefix='/api/projects/{project_id}', tags=['calculation'], dependencies=[Depends(get_current_user)])

# spot-volume-vs-GRP flagging (PRODUCT_ROADMAP.md's Overview view): a
# brand/station combo is "weak inventory" when its own GRP-per-spot is under
# half the category's average GRP-per-spot for the run, and it has enough
# spots for that to be a real pattern rather than one unlucky placement.
# Both numbers are judgment calls with no single objectively-correct value —
# picked to be conservative (flags only clearly-below-average buys, not
# anything under the mean) rather than aggressive, since a false "weak"
# flag on a real advertiser's real campaign has real reputational cost.
SPOT_EFFICIENCY_WEAK_RATIO = 0.5
SPOT_EFFICIENCY_MIN_SPOTS = 5


def _brand_names(brands_repo: BrandsRepository, project_id: str) -> dict:
    """{brand_id: name} for every brand in the project, fetched once.

    Every route below used to call brands_repo.get_brand(project_id, ...)
    once per *row* of whatever it just listed (once per station, per
    programme, per daypart, per matched calculation row -- not once per
    distinct brand) to attach a display name. Each of those calls opens its
    own fresh Postgres connection (db.py's get_connection() is one
    connection per call, by design -- see its docstring), so a run with a
    few dozen stations or a few thousand matched rows meant a few dozen or
    a few thousand sequential connection round trips just to label rows
    that only ever reference a handful of brands. Found live: a real
    project's /stations (34 rows) took ~45s and /dayparts (more distinct
    groups) timed out outright, both fixed by this single change. One
    list_brands() call replaces all of that -- same one connection a
    single get_brand() call would have opened anyway."""
    return {brand.id: brand.name for brand in brands_repo.list_brands(project_id)}


def _run_to_out(record) -> GrpRunSummaryOut:
    return GrpRunSummaryOut(
        run_id=record.id,
        project_id=record.project_id,
        total_brands=record.total_brands,
        total_spots=record.total_spots,
        total_grps=record.total_grps,
        total_spend=record.total_spend,
        matched_rows=record.matched_rows,
        unmatched_rows=record.unmatched_rows,
        is_current=record.is_current,
        generated_at=record.generated_at,
    )


def _job_to_out(job) -> CalculationJobOut:
    return CalculationJobOut(
        job_id=job.id,
        project_id=job.project_id,
        status=job.status,
        error=job.error,
        run=_run_to_out(job.run) if job.run else None,
    )


@router.post('/calculate', response_model=GrpRunSummaryOut, status_code=201)
def calculate(
    project_id: str,
    projects_repo: ProjectsRepository = Depends(get_projects_repository),
    uploads_repo: UploadsRepository = Depends(get_uploads_repository),
    ratings_repo: RatingsRepository = Depends(get_ratings_repository),
    matches_repo: MatchesRepository = Depends(get_matches_repository),
    calculations_repo: CalculationsRepository = Depends(get_calculations_repository),
):
    """Ensures matches are computed (same lazy-compute as GET .../matches,
    so calling this directly without having called GET .../matches first
    still works), then calculates a new run. Every call creates a new run —
    there's no dedup/"nothing changed" short-circuit yet, so recalculating
    an unchanged project produces a second identical-looking run."""
    if projects_repo.get_project(project_id) is None:
        raise HTTPException(status_code=404, detail='Project not found')

    media_activity = uploads_repo.list_media_activity(project_id)
    rating_rows = ratings_repo.list_project_rating_rows(project_id)
    match_records = matches_repo.ensure_matches_computed(project_id, media_activity, rating_rows)

    match_by_activity_id = {match.media_activity_id: match for match in match_records}
    rating_by_id = {rating.id: rating for rating in rating_rows}

    result = compute_run(media_activity, match_by_activity_id, rating_by_id)
    run_record = calculations_repo.create_run(project_id, result)
    return _run_to_out(run_record)


@router.post('/calculate/jobs', response_model=CalculationJobOut, status_code=202)
def start_calculate_job(
    project_id: str,
    projects_repo: ProjectsRepository = Depends(get_projects_repository),
    uploads_repo: UploadsRepository = Depends(get_uploads_repository),
    ratings_repo: RatingsRepository = Depends(get_ratings_repository),
    matches_repo: MatchesRepository = Depends(get_matches_repository),
    calculations_repo: CalculationsRepository = Depends(get_calculations_repository),
):
    if projects_repo.get_project(project_id) is None:
        raise HTTPException(status_code=404, detail='Project not found')
    job = start_calculation_job(project_id, uploads_repo, ratings_repo, matches_repo, calculations_repo)
    return _job_to_out(job)


@router.get('/calculate/jobs/{job_id}', response_model=CalculationJobOut)
def get_calculate_job(
    project_id: str,
    job_id: str,
    projects_repo: ProjectsRepository = Depends(get_projects_repository),
):
    if projects_repo.get_project(project_id) is None:
        raise HTTPException(status_code=404, detail='Project not found')
    job = get_calculation_job(job_id)
    if job is None or job.project_id != project_id:
        raise HTTPException(status_code=404, detail='Calculation job not found for this project')
    return _job_to_out(job)


@router.get('/runs', response_model=list[GrpRunSummaryOut])
def list_runs(
    project_id: str,
    calculations_repo: CalculationsRepository = Depends(get_calculations_repository),
    projects_repo: ProjectsRepository = Depends(get_projects_repository),
):
    if projects_repo.get_project(project_id) is None:
        raise HTTPException(status_code=404, detail='Project not found')
    return [_run_to_out(record) for record in calculations_repo.list_runs(project_id)]


@router.get('/runs/latest', response_model=GrpRunSummaryOut)
def get_latest_run(
    project_id: str,
    calculations_repo: CalculationsRepository = Depends(get_calculations_repository),
    projects_repo: ProjectsRepository = Depends(get_projects_repository),
):
    if projects_repo.get_project(project_id) is None:
        raise HTTPException(status_code=404, detail='Project not found')
    record = calculations_repo.get_latest_run(project_id)
    if record is None:
        raise HTTPException(status_code=404, detail='No runs yet for this project')
    return _run_to_out(record)


@router.get('/runs/{run_id}/brand-shares', response_model=list[BrandShareOut])
def get_brand_shares(
    project_id: str,
    run_id: str,
    calculations_repo: CalculationsRepository = Depends(get_calculations_repository),
    brands_repo: BrandsRepository = Depends(get_brands_repository),
    projects_repo: ProjectsRepository = Depends(get_projects_repository),
):
    if projects_repo.get_project(project_id) is None:
        raise HTTPException(status_code=404, detail='Project not found')
    shares = calculations_repo.list_brand_shares(project_id, run_id)
    if shares is None:
        raise HTTPException(status_code=404, detail='Run not found for this project')

    brand_names = _brand_names(brands_repo, project_id)
    results = []
    for share in shares:
        results.append(BrandShareOut(
            run_id=share.run_id,
            brand_id=share.brand_id,
            brand=brand_names.get(share.brand_id, 'Unknown brand'),
            total_grps=share.total_grps,
            tv_grps=share.tv_grps,
            cable_tv_grps=share.cable_tv_grps,
            radio_grps=share.radio_grps,
            sov=share.sov,
            spots=share.spots,
            avg_rating=share.avg_rating,
            total_spend=share.total_spend,
            soe=share.soe,
            tv_spend=share.tv_spend,
            cable_tv_spend=share.cable_tv_spend,
            radio_spend=share.radio_spend,
        ))
    return results


@router.get('/runs/{run_id}/calculations', response_model=list[GrpCalculationRowOut])
def get_calculations(
    project_id: str,
    run_id: str,
    calculations_repo: CalculationsRepository = Depends(get_calculations_repository),
    brands_repo: BrandsRepository = Depends(get_brands_repository),
    projects_repo: ProjectsRepository = Depends(get_projects_repository),
):
    """Not in API_CONTRACT.md's original route list — added because the spot-
    level GRP screen in PRODUCT_ROADMAP.md ("every calculated number traces
    back to its inputs") needs somewhere to read grp_calculations back out
    row by row; only the brand-shares aggregate was exposed before this."""
    if projects_repo.get_project(project_id) is None:
        raise HTTPException(status_code=404, detail='Project not found')
    calculations = calculations_repo.list_calculations(project_id, run_id)
    if calculations is None:
        raise HTTPException(status_code=404, detail='Run not found for this project')

    brand_names = _brand_names(brands_repo, project_id)
    results = []
    for row in calculations:
        results.append(GrpCalculationRowOut(
            grp_calculation_id=row.id,
            run_id=row.run_id,
            media_activity_id=row.media_activity_id,
            brand_id=row.brand_id,
            brand=brand_names.get(row.brand_id, 'Unknown brand'),
            station=row.station,
            programme=row.programme,
            day=row.day,
            medium=row.medium,
            spots=row.spots,
            rating=row.rating,
            grp=row.grp,
            calculated_at=row.calculated_at,
        ))
    return results


@router.get('/runs/{run_id}/stations', response_model=list[StationShareOut])
def get_station_shares(
    project_id: str,
    run_id: str,
    calculations_repo: CalculationsRepository = Depends(get_calculations_repository),
    brands_repo: BrandsRepository = Depends(get_brands_repository),
    projects_repo: ProjectsRepository = Depends(get_projects_repository),
):
    """GRP/spots per (brand, station) for a run — which stations a
    competitor's media weight is actually coming from, per
    PRODUCT_ROADMAP.md's Stations screen. Reuses the grp_by_station view
    (db/schema.sql) rather than re-deriving the join in Python."""
    if projects_repo.get_project(project_id) is None:
        raise HTTPException(status_code=404, detail='Project not found')
    shares = calculations_repo.list_station_shares(project_id, run_id)
    if shares is None:
        raise HTTPException(status_code=404, detail='Run not found for this project')

    brand_names = _brand_names(brands_repo, project_id)
    results = []
    for share in shares:
        results.append(StationShareOut(
            run_id=share.run_id, brand_id=share.brand_id, brand=brand_names.get(share.brand_id, 'Unknown brand'),
            station=share.station, total_grps=share.total_grps, spots=share.spots,
        ))
    return results


@router.get('/runs/{run_id}/spot-efficiency', response_model=list[SpotEfficiencyOut])
def get_spot_efficiency(
    project_id: str,
    run_id: str,
    calculations_repo: CalculationsRepository = Depends(get_calculations_repository),
    brands_repo: BrandsRepository = Depends(get_brands_repository),
    projects_repo: ProjectsRepository = Depends(get_projects_repository),
):
    """spot-volume-vs-GRP flagging (PRODUCT_ROADMAP.md's Overview view) —
    which brand/station combinations bought a high volume of spots for a
    weak GRP return. Computed on every read from the same per-(brand,
    station) aggregate the Stations screen already uses (list_station_shares
    — matched rows only, since an unmatched row has no GRP to be
    "efficient" or "weak" about), not stored anywhere: "weak" is this
    endpoint's own judgment call against the category's own average for
    this run, not a fact worth persisting or carrying between runs."""
    if projects_repo.get_project(project_id) is None:
        raise HTTPException(status_code=404, detail='Project not found')
    shares = calculations_repo.list_station_shares(project_id, run_id)
    if shares is None:
        raise HTTPException(status_code=404, detail='Run not found for this project')

    category_total_grps = sum(share.total_grps for share in shares)
    category_total_spots = sum(share.spots for share in shares)
    category_avg_grp_per_spot = (category_total_grps / category_total_spots) if category_total_spots else 0.0
    weak_ceiling = category_avg_grp_per_spot * SPOT_EFFICIENCY_WEAK_RATIO

    brand_names = _brand_names(brands_repo, project_id)
    results = []
    for share in shares:
        grp_per_spot = (share.total_grps / share.spots) if share.spots else 0.0
        is_weak = (
            category_avg_grp_per_spot > 0
            and share.spots >= SPOT_EFFICIENCY_MIN_SPOTS
            and grp_per_spot < weak_ceiling
        )
        results.append(SpotEfficiencyOut(
            run_id=share.run_id, brand_id=share.brand_id, brand=brand_names.get(share.brand_id, 'Unknown brand'),
            station=share.station, spots=share.spots, total_grps=share.total_grps,
            grp_per_spot=grp_per_spot, is_weak=is_weak,
        ))
    return sorted(results, key=lambda r: r.grp_per_spot)


@router.get('/runs/{run_id}/programmes', response_model=list[ProgrammeShareOut])
def get_programme_shares(
    project_id: str,
    run_id: str,
    calculations_repo: CalculationsRepository = Depends(get_calculations_repository),
    brands_repo: BrandsRepository = Depends(get_brands_repository),
    projects_repo: ProjectsRepository = Depends(get_projects_repository),
):
    """GRP/spots per (brand, programme) for a run — the Programmes screen's
    contribution breakdown, per PRODUCT_ROADMAP.md."""
    if projects_repo.get_project(project_id) is None:
        raise HTTPException(status_code=404, detail='Project not found')
    shares = calculations_repo.list_programme_shares(project_id, run_id)
    if shares is None:
        raise HTTPException(status_code=404, detail='Run not found for this project')

    brand_names = _brand_names(brands_repo, project_id)
    results = []
    for share in shares:
        results.append(ProgrammeShareOut(
            run_id=share.run_id, brand_id=share.brand_id, brand=brand_names.get(share.brand_id, 'Unknown brand'),
            programme=share.programme, total_grps=share.total_grps, spots=share.spots,
        ))
    return results


@router.get('/runs/{run_id}/dayparts', response_model=list[DaypartShareOut])
def get_daypart_shares(
    project_id: str,
    run_id: str,
    calculations_repo: CalculationsRepository = Depends(get_calculations_repository),
    brands_repo: BrandsRepository = Depends(get_brands_repository),
    projects_repo: ProjectsRepository = Depends(get_projects_repository),
):
    """GRP/spots per (brand, daypart) for a run — the Programmes screen's
    daypart breakdown, per PRODUCT_ROADMAP.md. Grouped by whatever
    time-band/daypart label the vendor's own file supplied
    (media_activity.time_band), not a canonical bucket this app defines —
    see grp_calculator.py's SYNONYMS['time_band'] comment. Reuses the
    grp_by_daypart view (db/schema.sql), same pattern as /stations and
    /programmes."""
    if projects_repo.get_project(project_id) is None:
        raise HTTPException(status_code=404, detail='Project not found')
    shares = calculations_repo.list_daypart_shares(project_id, run_id)
    if shares is None:
        raise HTTPException(status_code=404, detail='Run not found for this project')

    brand_names = _brand_names(brands_repo, project_id)
    results = []
    for share in shares:
        results.append(DaypartShareOut(
            run_id=share.run_id, brand_id=share.brand_id, brand=brand_names.get(share.brand_id, 'Unknown brand'),
            time_band=share.time_band, total_grps=share.total_grps, spots=share.spots,
        ))
    return results


@router.get('/runs/{run_id}/trend', response_model=list[TrendPointOut])
def get_trend(
    project_id: str,
    run_id: str,
    calculations_repo: CalculationsRepository = Depends(get_calculations_repository),
    brands_repo: BrandsRepository = Depends(get_brands_repository),
    projects_repo: ProjectsRepository = Depends(get_projects_repository),
):
    """Weekly GRP/spots per brand for a run, grouped by the Monday-start
    week of each matched row's media_activity.activity_date. Rows with no
    activity_date (most uploads today don't have a Date column mapped)
    are excluded rather than bucketed under some placeholder week."""
    if projects_repo.get_project(project_id) is None:
        raise HTTPException(status_code=404, detail='Project not found')
    points = calculations_repo.list_trend(project_id, run_id)
    if points is None:
        raise HTTPException(status_code=404, detail='Run not found for this project')

    brand_names = _brand_names(brands_repo, project_id)
    results = []
    for point in points:
        results.append(TrendPointOut(
            run_id=point.run_id, brand_id=point.brand_id, brand=brand_names.get(point.brand_id, 'Unknown brand'),
            week_start=point.week_start, total_grps=point.total_grps, spots=point.spots,
        ))
    return results
