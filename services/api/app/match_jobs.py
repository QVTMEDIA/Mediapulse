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


_jobs: dict[str, MatchJob] = {}
_jobs_lock = threading.Lock()
_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix='match-job')


def _set_status(job_id: str, status: str, error: Optional[str] = None) -> None:
    with _jobs_lock:
        job = _jobs.get(job_id)
        if job:
            job.status = status
            job.error = error


def _run_ensure(job_id, project_id, matches_repo, uploads_repo, ratings_repo):
    _set_status(job_id, 'running')
    try:
        media_activity = uploads_repo.list_media_activity(project_id)
        rating_rows = ratings_repo.list_project_rating_rows(project_id)
        matches_repo.ensure_matches_computed(project_id, media_activity, rating_rows)
        _set_status(job_id, 'completed')
    except Exception as exc:
        _set_status(job_id, 'failed', str(exc))


def _run_recompute(job_id, project_id, matches_repo, uploads_repo, ratings_repo):
    _set_status(job_id, 'running')
    try:
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
        _set_status(job_id, 'completed')
    except Exception as exc:
        _set_status(job_id, 'failed', str(exc))


def start_match_job(project_id, mode, matches_repo, uploads_repo, ratings_repo) -> MatchJob:
    job = MatchJob(id=str(uuid.uuid4()), project_id=project_id)
    with _jobs_lock:
        _jobs[job.id] = job
    runner = _run_recompute if mode == 'recompute' else _run_ensure
    _executor.submit(runner, job.id, project_id, matches_repo, uploads_repo, ratings_repo)
    return job


def get_match_job(job_id: str) -> Optional[MatchJob]:
    with _jobs_lock:
        return _jobs.get(job_id)