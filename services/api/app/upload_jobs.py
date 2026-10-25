from __future__ import annotations

import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Optional

# Shared background-job engine for the three upload kinds (project media
# report, ratings dataset, SOE Explorer) -- one job store/executor instead
# of three copies of the same dict-store/lock/ThreadPoolExecutor boilerplate
# calculation_jobs.py and match_jobs.py each already have their own of, for
# their own single domain. Each router defines its own job-runner function
# (parse the file, insert with real per-batch progress via
# db.insert_rows_batched's on_batch callback, persist) and its own typed
# *JobOut response wrapping this generic total/processed/result shape --
# this module only owns the generic "run a function in the background and
# let a poller watch its status/progress" machinery.

# How long a finished (or abandoned) job stays in _jobs before
# start_upload_job() reaps it -- see _evict_stale_jobs(). Nothing ever
# removed an entry before this: _jobs grew by one dict entry, forever, for
# every single upload (project report, ratings, or SOE Explorer) for as
# long as this process stayed up -- each one holding its full `result`
# (UploadBatchOut/RatingsDatasetOut/SoeUploadOut, which can carry up to 100
# dropped-row `issues` plus mapping warnings) long after any poller could
# still be looking at it. calculation_jobs.py/match_jobs.py have the same
# issue and the same fix. Long enough that a slow poller still finds its
# job; short enough that a long-running deploy's own job history can't
# grow without bound.
_JOB_RETENTION_SECONDS = 3600


@dataclass
class UploadJob:
    id: str
    # Opaque scoping value a router can check a poll request against (e.g.
    # project uploads set this to project_id, so GET .../uploads/jobs/{id}
    # can 404 a job id that exists but belongs to a different project --
    # the same check CalculationJob/MatchJob make via their own project_id
    # field). None for upload kinds with nothing narrower than "any
    # authenticated user" to scope to, e.g. ratings and SOE Explorer.
    scope: Optional[str] = None
    status: str = 'queued'
    error: Optional[str] = None
    # Real progress: total is set by the job function once it knows how many
    # rows it's about to insert (right after parsing), processed advances by
    # however many rows insert_rows_batched's on_batch callback reports
    # after each real batch actually lands -- not a simulated percentage.
    total: int = 0
    processed: int = 0
    # Whatever the job function returns on success -- each router casts
    # this into its own typed *Out schema (UploadBatchOut/RatingsDatasetOut/
    # SoeUploadOut) rather than this module knowing about any of them.
    result: Optional[Any] = None
    # Monotonic, not wall-clock -- immune to the system clock ever being
    # adjusted. Only used by _evict_stale_jobs() below; never serialized.
    created_at: float = field(default_factory=time.monotonic)


_jobs: dict[str, UploadJob] = {}
_jobs_lock = threading.Lock()
_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix='upload-job')


def _evict_stale_jobs() -> None:
    cutoff = time.monotonic() - _JOB_RETENTION_SECONDS
    with _jobs_lock:
        stale_ids = [job_id for job_id, job in _jobs.items() if job.created_at < cutoff]
        for job_id in stale_ids:
            del _jobs[job_id]


def _set_status(job_id: str, status: str, *, error: Optional[str] = None, result: Optional[Any] = None) -> None:
    with _jobs_lock:
        job = _jobs.get(job_id)
        if job:
            job.status = status
            job.error = error
            job.result = result


def set_total(job_id: str, total: int) -> None:
    with _jobs_lock:
        job = _jobs.get(job_id)
        if job:
            job.total = total


def advance(job_id: str, by: int = 1) -> None:
    with _jobs_lock:
        job = _jobs.get(job_id)
        if job:
            job.processed += by


def _run(job_id: str, fn, args: tuple, kwargs: dict) -> None:
    _set_status(job_id, 'running')
    try:
        result = fn(job_id, *args, **kwargs)
        _set_status(job_id, 'completed', result=result)
    except Exception as exc:
        _set_status(job_id, 'failed', error=str(exc))


def start_upload_job(fn, *args, scope: Optional[str] = None, **kwargs) -> UploadJob:
    """fn(job_id, *args, **kwargs) runs in a background thread and should
    call set_total()/advance() as it works, then return whatever success
    result the caller's *JobOut schema expects -- any exception it raises
    is caught and reported as the job's error instead of propagating.
    scope is this job's own UploadJob.scope (see its field comment), kept
    as a keyword-only argument so it's never mistaken for one of fn's own
    positional args."""
    _evict_stale_jobs()
    job = UploadJob(id=str(uuid.uuid4()), scope=scope)
    with _jobs_lock:
        _jobs[job.id] = job
    _executor.submit(_run, job.id, fn, args, kwargs)
    return job


def get_upload_job(job_id: str) -> Optional[UploadJob]:
    with _jobs_lock:
        return _jobs.get(job_id)
