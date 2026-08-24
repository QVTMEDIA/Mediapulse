from datetime import datetime
from typing import Optional

from .common import CamelModel


class RatingMatchOut(CamelModel):
    rating_match_id: str
    media_activity_id: str
    matched_rating_id: Optional[str] = None
    match_status: str  # 'exact' | 'suggested' | 'unmatched' | 'manual'
    match_confidence: Optional[float] = None
    match_key: str
    corrected_at: Optional[datetime] = None


class MatchCorrection(CamelModel):
    # None means "manually confirmed as unmatched" — distinct from the
    # algorithm having found nothing (match_status stays 'manual' either way,
    # so a human decision is never indistinguishable from an unreviewed row).
    matched_rating_id: Optional[str] = None


class MatchJobOut(CamelModel):
    job_id: str
    project_id: str
    status: str  # 'queued' | 'running' | 'completed' | 'failed'
    error: Optional[str] = None
    # Real progress for recompute jobs only — 'ensure' jobs (a single atomic
    # repository call, no per-row loop to report from) always report 0/0. A
    # polling client can render processed/total as a real percentage instead
    # of an indeterminate spinner. See match_jobs.py's MatchJob.
    total: int = 0
    processed: int = 0
