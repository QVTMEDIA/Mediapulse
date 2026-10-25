from __future__ import annotations

import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Optional

from .calculations import compute_run, resolve_rating_by_id
from .repositories.calculations import GrpRunRecord

# How long a finished (or abandoned) job stays in _jobs before start_
# calculation_job() reaps it -- see _evict_stale_jobs(). Nothing ever
# removed an entry before this: _jobs grew by one dict entry, forever, for
# every single Calculate click for as long as this process stays up. Long
# enough that a slow poller (or a human who walked away mid-job) still
# finds its job; short enough that a long-running deploy's own job history
# can't grow without bound.
_JOB_RETENTION_SECONDS = 3600

# compute_run()'s GRP aggregation and the matching engine's own fuzzy-
# suggestion scoring are both vectorized (pandas/rapidfuzz) rather than a
# plain Python per-row loop in this file the way match_jobs.py's recompute
# has, so there's no row count to report real-time progress against the
# way MatchJob.processed/total does. Progress here is stage-based instead:
# a fixed number of discrete, genuinely-completed steps (not a simulated/
# interpolated percentage) -- every step below is one real unit of work in
# _run_calculation, in order.
CALCULATION_STAGE_COUNT = 6


@dataclass
class CalculationJob:
    id: str
    project_id: str
    status: str = 'queued'
    error: Optional[str] = None
    run: Optional[GrpRunRecord] = None
    total: int = CALCULATION_STAGE_COUNT
    processed: int = 0
    # Monotonic, not wall-clock -- immune to the system clock ever being
    # adjusted. Only used by _evict_stale_jobs() below; never serialized.
    created_at: float = field(default_factory=time.monotonic)


_jobs: dict[str, CalculationJob] = {}
_jobs_lock = threading.Lock()
_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix='calculation-job')


def _evict_stale_jobs() -> None:
    cutoff = time.monotonic() - _JOB_RETENTION_SECONDS
    with _jobs_lock:
        stale_ids = [job_id for job_id, job in _jobs.items() if job.created_at < cutoff]
        for job_id in stale_ids:
            del _jobs[job_id]


def _set_status(
    job_id: str,
    status: str,
    *,
    error: Optional[str] = None,
    run: Optional[GrpRunRecord] = None,
) -> None:
    with _jobs_lock:
        job = _jobs.get(job_id)
        if job:
            job.status = status
            job.error = error
            job.run = run


def _advance(job_id: str) -> None:
    with _jobs_lock:
        job = _jobs.get(job_id)
        if job:
            job.processed += 1


def _run_calculation(job_id, project_id, uploads_repo, ratings_repo, matches_repo, calculations_repo):
    _set_status(job_id, 'running')
    try:
        media_activity = uploads_repo.list_media_activity(project_id)
        _advance(job_id)

        rating_rows = ratings_repo.list_project_rating_rows(project_id)
        _advance(job_id)

        match_records = matches_repo.ensure_matches_computed(project_id, media_activity, rating_rows)
        _advance(job_id)

        match_by_activity_id = {match.media_activity_id: match for match in match_records}
        rating_by_id = resolve_rating_by_id(rating_rows, match_records, ratings_repo)
        _advance(job_id)

        result = compute_run(media_activity, match_by_activity_id, rating_by_id)
        _advance(job_id)

        run_record = calculations_repo.create_run(project_id, result)
        _advance(job_id)

        _set_status(job_id, 'completed', run=run_record)
    except Exception as exc:
        _set_status(job_id, 'failed', error=str(exc))


def start_calculation_job(project_id, uploads_repo, ratings_repo, matches_repo, calculations_repo) -> CalculationJob:
    _evict_stale_jobs()
    job = CalculationJob(id=str(uuid.uuid4()), project_id=project_id)
    with _jobs_lock:
        _jobs[job.id] = job
    _executor.submit(_run_calculation, job.id, project_id, uploads_repo, ratings_repo, matches_repo, calculations_repo)
    return job


def get_calculation_job(job_id: str) -> Optional[CalculationJob]:
    with _jobs_lock:
        return _jobs.get(job_id)
