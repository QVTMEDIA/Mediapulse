import csv
import io

from fastapi import APIRouter, Depends, HTTPException, Response

from ..auth import get_current_user
from ..match_jobs import get_match_job, start_match_job
from ..matches import compute_matches
from ..repositories.brands import BrandsRepository, get_brands_repository
from ..repositories.matches import MatchesRepository, RatingMatchRecord, get_matches_repository
from ..repositories.projects import ProjectsRepository, get_projects_repository
from ..repositories.ratings import RatingsRepository, get_ratings_repository
from ..repositories.uploads import UploadsRepository, get_uploads_repository
from ..schemas.matches import MatchCorrection, MatchJobOut, RatingMatchOut
from ..schemas.ratings import RatingRowOut

router = APIRouter(prefix='/api/projects/{project_id}/matches', tags=['matches'], dependencies=[Depends(get_current_user)])


def _to_out(record: RatingMatchRecord) -> RatingMatchOut:
    return RatingMatchOut(
        rating_match_id=record.id,
        media_activity_id=record.media_activity_id,
        matched_rating_id=record.matched_rating_id,
        match_status=record.match_status,
        match_confidence=record.match_confidence,
        match_key=record.match_key,
        corrected_at=record.corrected_at,
    )


def _rating_row_to_out(record) -> RatingRowOut:
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


def _job_to_out(job) -> MatchJobOut:
    return MatchJobOut(
        job_id=job.id, project_id=job.project_id, status=job.status, error=job.error,
        total=job.total, processed=job.processed,
    )


@router.post('/jobs', response_model=MatchJobOut, status_code=202)
def start_job(
    project_id: str,
    mode: str = 'ensure',
    matches_repo: MatchesRepository = Depends(get_matches_repository),
    uploads_repo: UploadsRepository = Depends(get_uploads_repository),
    ratings_repo: RatingsRepository = Depends(get_ratings_repository),
    projects_repo: ProjectsRepository = Depends(get_projects_repository),
):
    if projects_repo.get_project(project_id) is None:
        raise HTTPException(status_code=404, detail='Project not found')
    if mode not in ('ensure', 'recompute', 'recompute_exact'):
        raise HTTPException(status_code=422, detail='mode must be ensure, recompute, or recompute_exact')
    job = start_match_job(project_id, mode, matches_repo, uploads_repo, ratings_repo)
    return _job_to_out(job)


@router.get('/jobs/{job_id}', response_model=MatchJobOut)
def get_job(project_id: str, job_id: str, projects_repo: ProjectsRepository = Depends(get_projects_repository)):
    if projects_repo.get_project(project_id) is None:
        raise HTTPException(status_code=404, detail='Project not found')
    job = get_match_job(job_id)
    if job is None or job.project_id != project_id:
        raise HTTPException(status_code=404, detail='Match job not found for this project')
    return _job_to_out(job)


@router.get('', response_model=list[RatingMatchOut])
def list_matches(
    project_id: str,
    matches_repo: MatchesRepository = Depends(get_matches_repository),
    uploads_repo: UploadsRepository = Depends(get_uploads_repository),
    ratings_repo: RatingsRepository = Depends(get_ratings_repository),
    projects_repo: ProjectsRepository = Depends(get_projects_repository),
):
    """Computes matches for any media_activity row that doesn't have one yet
    (exact-key lookup, then grp_calculator's fuzzy suggestion engine), then
    returns the project's full current match list. Idempotent — rows that
    already have a match (including manual corrections) are never
    recomputed here. If ratings are attached after matches were already
    computed, call POST .../matches/recompute to retry 'unmatched' rows."""
    if projects_repo.get_project(project_id) is None:
        raise HTTPException(status_code=404, detail='Project not found')
    media_activity = uploads_repo.list_media_activity(project_id)
    rating_rows = ratings_repo.list_project_rating_rows(project_id)
    records = matches_repo.ensure_matches_computed(project_id, media_activity, rating_rows)
    return [_to_out(record) for record in records]


@router.get('/ratings', response_model=list[RatingRowOut])
def list_matched_ratings(
    project_id: str,
    matches_repo: MatchesRepository = Depends(get_matches_repository),
    ratings_repo: RatingsRepository = Depends(get_ratings_repository),
    projects_repo: ProjectsRepository = Depends(get_projects_repository),
):
    """Only the specific ratings rows this project's current matches
    actually point at -- built for the Matches screen, which used to fetch
    every row of every attached ratings dataset (via GET .../ratings-
    datasets/{id}/rows, once per dataset) just to describe the handful its
    matches reference. Found live: a project with one 24,696-row ratings
    dataset made that initial page load fetch a 7MB+ JSON response
    (~33s) every single time the screen opened, regardless of how many of
    those rows were actually matched to anything. Does not compute
    matches itself (unlike GET .../matches) -- call that first, or let the
    frontend's existing ensure-job do it, so this reads current state
    rather than triggering the same lazy-compute a second time."""
    if projects_repo.get_project(project_id) is None:
        raise HTTPException(status_code=404, detail='Project not found')
    matched_rating_ids = {
        record.matched_rating_id
        for record in matches_repo.list_matches(project_id)
        if record.matched_rating_id
    }
    rows = ratings_repo.list_rows_by_ids(matched_rating_ids)
    return [_rating_row_to_out(row) for row in rows]


@router.get('/export')
def export_matches(
    project_id: str,
    matches_repo: MatchesRepository = Depends(get_matches_repository),
    uploads_repo: UploadsRepository = Depends(get_uploads_repository),
    ratings_repo: RatingsRepository = Depends(get_ratings_repository),
    projects_repo: ProjectsRepository = Depends(get_projects_repository),
    brands_repo: BrandsRepository = Depends(get_brands_repository),
):
    """Downloadable CSV of the project's full current match state: the media
    spend activity and the rating it matched to, side by side in one row --
    the join the Matches screen's UI already does client-side (activityById/
    ratingsById lookups) to display both, done once here instead of asking
    every consumer of the data to redo it.

    Deliberately not folded into the Export Centre's run-scoped xlsx
    workbook (app/exports.py): that workbook's "Unmatched Records" sheet
    already documents why matching is project-wide, not run-scoped state --
    it isn't frozen the way calculated GRPs are, so a match report has no
    natural "point in time" to freeze either. This always reflects
    current match state and needs no run (or any calculation at all) to
    exist. Plain CSV rather than .xlsx: one flat table, no formatting/
    multi-sheet structure worth the openpyxl workbook-building machinery
    that only build_workbook() needs.
    """
    if projects_repo.get_project(project_id) is None:
        raise HTTPException(status_code=404, detail='Project not found')

    media_activity = uploads_repo.list_media_activity(project_id)
    rating_rows = ratings_repo.list_project_rating_rows(project_id)
    records = matches_repo.ensure_matches_computed(project_id, media_activity, rating_rows)

    activity_by_id = {row.id: row for row in media_activity}
    ratings_by_id = {row.id: row for row in rating_rows}
    # One list_brands() call instead of one brands_repo.get_brand() call per
    # distinct brand seen in the export -- each get_brand() opens its own
    # fresh Postgres connection (db.py's get_connection() is one connection
    # per call), so this was already better than the per-row version of the
    # same mistake found and fixed in routers/runs.py, but still paid a
    # separate connection per brand rather than one connection, period.
    brand_names = {brand.id: brand.name for brand in brands_repo.list_brands(project_id)}

    def _brand_name(brand_id: str) -> str:
        return brand_names.get(brand_id, 'Unknown brand')

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow([
        'Brand', 'Medium', 'Station', 'Day', 'Programme', 'Time Band', 'Spots', 'Cost',
        'Match Status', 'Match Confidence',
        'Matched Rating Station', 'Matched Rating Day', 'Matched Rating Programme', 'Matched Rating Time Band',
        'Matched Rating (%)', 'Corrected At',
    ])
    for match in records:
        activity = activity_by_id.get(match.media_activity_id)
        rating = ratings_by_id.get(match.matched_rating_id) if match.matched_rating_id else None
        writer.writerow([
            _brand_name(activity.brand_id) if activity else '',
            activity.medium if activity else '',
            activity.station if activity else '',
            activity.day if activity else '',
            activity.programme if activity else '',
            activity.time_band if activity else '',
            activity.spots if activity else '',
            activity.cost if activity else None,
            match.match_status,
            match.match_confidence,
            rating.station if rating else '',
            rating.day if rating else '',
            rating.programme if rating else '',
            rating.time_band if rating else '',
            rating.rating if rating else None,
            match.corrected_at,
        ])

    project = projects_repo.get_project(project_id)
    safe_name = ''.join(c if c.isalnum() or c in ' -_' else '_' for c in project.name).strip() or 'mediapulse'
    file_name = f'{safe_name.replace(" ", "_")}_match_report.csv'
    return Response(
        content=buffer.getvalue(),
        media_type='text/csv',
        headers={'Content-Disposition': f'attachment; filename="{file_name}"'},
    )


@router.post('/{rating_match_id}/correct', response_model=RatingMatchOut)
def correct_match(
    project_id: str,
    rating_match_id: str,
    payload: MatchCorrection,
    matches_repo: MatchesRepository = Depends(get_matches_repository),
    ratings_repo: RatingsRepository = Depends(get_ratings_repository),
    projects_repo: ProjectsRepository = Depends(get_projects_repository),
):
    if projects_repo.get_project(project_id) is None:
        raise HTTPException(status_code=404, detail='Project not found')
    if matches_repo.get_match_for_project(project_id, rating_match_id) is None:
        raise HTTPException(status_code=404, detail='Match not found for this project')
    if payload.matched_rating_id is not None:
        # Was an unenforced gap: a bad/foreign id used to fail silently into
        # "unmatched" at calculate time instead of erroring here where the
        # caller can actually see it. Matters more now that the frontend
        # lets a user manually assign a rating rather than only confirming
        # a suggestion the backend already validated.
        valid_rating_ids = {rating.id for rating in ratings_repo.list_project_rating_rows(project_id)}
        if payload.matched_rating_id not in valid_rating_ids:
            raise HTTPException(
                status_code=422, detail='matchedRatingId is not a rating attached to this project'
            )
    record = matches_repo.correct_match(rating_match_id, payload.matched_rating_id)
    return _to_out(record)


@router.post('/recompute', response_model=list[RatingMatchOut])
def recompute_matches(
    project_id: str,
    matches_repo: MatchesRepository = Depends(get_matches_repository),
    uploads_repo: UploadsRepository = Depends(get_uploads_repository),
    ratings_repo: RatingsRepository = Depends(get_ratings_repository),
    projects_repo: ProjectsRepository = Depends(get_projects_repository),
):
    """Not in API_CONTRACT.md's original route list — added to close a gap
    noted when Phase 1 shipped: GET /matches only fills gaps for rows with
    no match record at all, so a row already marked 'unmatched' never got
    retried after new ratings were attached later. This re-attempts exact +
    fuzzy matching for 'unmatched' rows only — 'exact', 'suggested', and
    'manual' rows are already decided and are never touched here."""
    if projects_repo.get_project(project_id) is None:
        raise HTTPException(status_code=404, detail='Project not found')

    existing = matches_repo.list_matches(project_id)
    unmatched_by_activity_id = {m.media_activity_id: m for m in existing if m.match_status == 'unmatched'}
    if unmatched_by_activity_id:
        media_activity = uploads_repo.list_media_activity(project_id)
        unmatched_activity = [a for a in media_activity if a.id in unmatched_by_activity_id]
        rating_rows = ratings_repo.list_project_rating_rows(project_id)

        # Batched into one update_matches_bulk() call rather than one
        # update_match() call per resolved row -- same fix, same reason, as
        # match_jobs.py's _run_recompute (the job-based version of this same
        # operation the Matches screen actually calls).
        updates = [
            (unmatched_by_activity_id[result.media_activity_id].id, result.matched_rating_id, result.match_status, result.match_confidence)
            for result in compute_matches(unmatched_activity, rating_rows)
            if result.match_status != 'unmatched'
        ]
        matches_repo.update_matches_bulk(updates)

    return [_to_out(record) for record in matches_repo.list_matches(project_id)]
