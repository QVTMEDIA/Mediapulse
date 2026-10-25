from __future__ import annotations

import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Optional

from .matches import compute_matches

# How long a finished (or abandoned) job stays in _jobs before
# start_match_job() reaps it -- see _evict_stale_jobs(). Nothing ever
# removed an entry before this: 'ensure' jobs start on every single visit
# to the Matches screen (see MatchesSection.tsx's refresh(), called from a
# useEffect on mount/project-change, not just the explicit Fast recompute/
# Full scan buttons), so _jobs grew by one dict entry on every page view,
# forever, for as long as this process stayed up -- the highest-frequency
# of this codebase's three job stores (see calculation_jobs.py/
# upload_jobs.py for the other two, same issue, same fix). Long enough
# that a slow poller still finds its job; short enough that a long-running
# deploy's own job history can't grow without bound.
_JOB_RETENTION_SECONDS = 3600


@dataclass
class MatchJob:
    id: str
    project_id: str
    status: str = 'queued'
    error: Optional[str] = None
    # Real for both 'ensure' and 'recompute' jobs (see _run_ensure/
    # _run_recompute) — each sets total once, up front, to however many
    # rows it's about to visit, then advances processed via
    # compute_matches()'s on_progress callback as it actually finishes real
    # chunks of matching work (one row at a time for exact matches, in
    # whatever real batch size grp_calculator.build_unmatched_suggestions()
    # scores together for the fuzzy-suggestion phase -- see matches.py's
    # compute_matches docstring). Earlier version advanced processed in a
    # separate loop *after* compute_matches() had already returned its full,
    # already-computed result list -- which made processed jump straight
    # from 0 to total in one tick once the (possibly slow) real computation
    # finished, instead of climbing during it.
    total: int = 0
    processed: int = 0
    # Monotonic, not wall-clock -- immune to the system clock ever being
    # adjusted. Only used by _evict_stale_jobs() below; never serialized.
    created_at: float = field(default_factory=time.monotonic)


_jobs: dict[str, MatchJob] = {}
_jobs_lock = threading.Lock()
_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix='match-job')


def _evict_stale_jobs() -> None:
    cutoff = time.monotonic() - _JOB_RETENTION_SECONDS
    with _jobs_lock:
        stale_ids = [job_id for job_id, job in _jobs.items() if job.created_at < cutoff]
        for job_id in stale_ids:
            del _jobs[job_id]


def _set_status(job_id: str, status: str, error: Optional[str] = None) -> None:
    with _jobs_lock:
        job = _jobs.get(job_id)
        if job:
            job.status = status
            job.error = error


def _set_total(job_id: str, total: int) -> None:
    with _jobs_lock:
        job = _jobs.get(job_id)
        if job:
            job.total = total


def _advance_processed(job_id: str, by: int = 1) -> None:
    with _jobs_lock:
        job = _jobs.get(job_id)
        if job:
            job.processed += by


def _run_ensure(job_id, project_id, matches_repo, uploads_repo, ratings_repo):
    _set_status(job_id, 'running')
    try:
        media_activity = uploads_repo.list_media_activity(project_id)
        # Same "rows with no match record yet" set ensure_matches_computed()
        # computes internally (list_matches() already scopes to this
        # project, same as its own existing_ids query/filter) -- hoisted up
        # here, before any matching work, so total is known as early as
        # possible instead of staying 0 for this job's whole lifetime.
        existing_ids = {match.media_activity_id for match in matches_repo.list_matches(project_id)}
        pending = [activity for activity in media_activity if activity.id not in existing_ids]
        _set_total(job_id, len(pending))
        if pending:
            rating_rows = ratings_repo.list_project_rating_rows(project_id)
            # processed advances from inside compute_matches() itself, as
            # real chunks of matching work actually finish -- not in a
            # separate loop over its already-complete return value (see
            # MatchJob.total's comment for why that used to make the bar
            # jump straight from 0 to total). Writing is still a separate
            # bulk insert_matches() call after every row has a result.
            computed = compute_matches(pending, rating_rows, on_progress=lambda n: _advance_processed(job_id, n))
            matches_repo.insert_matches(project_id, computed)
        _set_status(job_id, 'completed')
    except Exception as exc:
        _set_status(job_id, 'failed', str(exc))


def _run_recompute(job_id, project_id, matches_repo, uploads_repo, ratings_repo, *, include_suggestions: bool):
    _set_status(job_id, 'running')
    try:
        existing = matches_repo.list_matches(project_id)
        unmatched_by_activity_id = {m.media_activity_id: m for m in existing if m.match_status == 'unmatched'}
        _set_total(job_id, len(unmatched_by_activity_id))
        if unmatched_by_activity_id:
            media_activity = uploads_repo.list_media_activity(project_id)
            unmatched_activity = [a for a in media_activity if a.id in unmatched_by_activity_id]
            rating_rows = ratings_repo.list_project_rating_rows(project_id)
            # Collected and written in one batch at the end via
            # update_matches_bulk() rather than one matches_repo.update_match()
            # call per resolved row -- found live as the real reason "Full
            # scan" barely ever completed on a large project: each
            # update_match() call opens its own fresh Postgres connection
            # (db.py's get_connection() is one connection per call), so
            # resolving thousands of previously-unmatched rows meant
            # thousands of sequential connection round trips in this loop
            # alone. processed advances from inside compute_matches() itself
            # (see _run_ensure above / MatchJob.total's comment) so the
            # progress bar climbs during the real matching work, even though
            # the actual writes still happen afterward, once every row has a
            # result, in one bulk call.
            results = compute_matches(
                unmatched_activity, rating_rows, include_suggestions=include_suggestions,
                on_progress=lambda n: _advance_processed(job_id, n),
            )
            updates = []
            for result in results:
                if result.match_status != 'unmatched':
                    existing_match = unmatched_by_activity_id[result.media_activity_id]
                    updates.append((
                        existing_match.id, result.matched_rating_id, result.match_status, result.match_confidence
                    ))
            matches_repo.update_matches_bulk(updates)
        _set_status(job_id, 'completed')
    except Exception as exc:
        _set_status(job_id, 'failed', str(exc))


def start_match_job(project_id, mode, matches_repo, uploads_repo, ratings_repo) -> MatchJob:
    _evict_stale_jobs()
    job = MatchJob(id=str(uuid.uuid4()), project_id=project_id)
    with _jobs_lock:
        _jobs[job.id] = job
    if mode == 'recompute':
        _executor.submit(
            _run_recompute, job.id, project_id, matches_repo, uploads_repo, ratings_repo, include_suggestions=True
        )
    elif mode == 'recompute_exact':
        _executor.submit(
            _run_recompute, job.id, project_id, matches_repo, uploads_repo, ratings_repo, include_suggestions=False
        )
    else:
        _executor.submit(_run_ensure, job.id, project_id, matches_repo, uploads_repo, ratings_repo)
    return job


def get_match_job(job_id: str) -> Optional[MatchJob]:
    with _jobs_lock:
        return _jobs.get(job_id)
