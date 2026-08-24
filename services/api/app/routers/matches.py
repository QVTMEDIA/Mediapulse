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
    if mode not in ('ensure', 'recompute'):
        raise HTTPException(status_code=422, detail='mode must be ensure or recompute')
    job = start_match_job(project_id, mode, matches_repo, uploads_repo, ratings_repo)
    return MatchJobOut(job_id=job.id, project_id=job.project_id, status=job.status)


@router.get('/jobs/{job_id}', response_model=MatchJobOut)
def get_job(project_id: str, job_id: str, projects_repo: ProjectsRepository = Depends(get_projects_repository)):
    if projects_repo.get_project(project_id) is None:
        raise HTTPException(status_code=404, detail='Project not found')
    job = get_match_job(job_id)
    if job is None or job.project_id != project_id:
        raise HTTPException(status_code=404, detail='Match job not found for this project')
    return MatchJobOut(job_id=job.id, project_id=job.project_id, status=job.status, error=job.error)


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
    brand_names: dict = {}

    def _brand_name(brand_id: str) -> str:
        if brand_id not in brand_names:
            brand = brands_repo.get_brand(project_id, brand_id)
            brand_names[brand_id] = brand.name if brand else 'Unknown brand'
        return brand_names[brand_id]

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow([
        'Brand', 'Medium', 'Station', 'Day', 'Programme / Time Band', 'Spots', 'Cost',
        'Match Status', 'Match Confidence',
        'Matched Rating Station', 'Matched Rating Day', 'Matched Rating Programme / Time Band', 'Matched Rating (%)',
        'Corrected At',
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
            activity.spots if activity else '',
            activity.cost if activity else None,
            match.match_status,
            match.match_confidence,
            rating.station if rating else '',
            rating.day if rating else '',
            rating.programme if rating else '',
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

        for result in compute_matches(unmatched_activity, rating_rows):
            if result.match_status == 'unmatched':
                continue
            existing_match = unmatched_by_activity_id[result.media_activity_id]
            matches_repo.update_match(
                existing_match.id, result.matched_rating_id, result.match_status, result.match_confidence
            )

    return [_to_out(record) for record in matches_repo.list_matches(project_id)]
