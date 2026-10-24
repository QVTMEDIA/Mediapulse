from __future__ import annotations

import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Optional

from .matches import compute_matches


@dataclass
class MatchJob:
    id: str
    project_id: str
    status: str = 'queued'
    error: Optional[str] = None
    # Real for both 'ensure' and 'recompute' jobs (see _run_ensure/
    # _run_recompute) — each sets total once, up front, to however many
    # rows it's about to visit, then advances processed by one per row
    # visited (whether or not it ends up matched), so a polling client can
    # render `processed / total` as a real percentage instead of an
    # indeterminate spinner — the real bottleneck on a slow/cold-started
    # backend is exactly this per-row persistence loop.
    total: int = 0
    processed: int = 0


_jobs: dict[str, MatchJob] = {}
_jobs_lock = threading.Lock()
_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix='match-job')


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


def _increment_processed(job_id: str) -> None:
    with _jobs_lock:
        job = _jobs.get(job_id)
        if job:
            job.processed += 1


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
            # Same reasoning as _run_recompute below: compute_matches() is
            # still one call (its own fuzzy-suggestion scoring is batched/
            # vectorized, not a per-row loop worth breaking up further),
            # but writing is now a separate bulk insert_matches() call
            # instead of happening inside that one call, so processed can
            # advance per row visited here before the write.
            computed = []
            for result in compute_matches(pending, rating_rows):
                computed.append(result)
                _increment_processed(job_id)
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
            # alone. processed still advances per row visited here (in
            # memory, no DB cost) so the progress bar stays accurate even
            # though the actual writes now happen after this loop finishes.
            updates = []
            for result in compute_matches(unmatched_activity, rating_rows, include_suggestions=include_suggestions):
                if result.match_status != 'unmatched':
                    existing_match = unmatched_by_activity_id[result.media_activity_id]
                    updates.append((
                        existing_match.id, result.matched_rating_id, result.match_status, result.match_confidence
                    ))
                _increment_processed(job_id)
            matches_repo.update_matches_bulk(updates)
        _set_status(job_id, 'completed')
    except Exception as exc:
        _set_status(job_id, 'failed', str(exc))


def start_match_job(project_id, mode, matches_repo, uploads_repo, ratings_repo) -> MatchJob:
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
