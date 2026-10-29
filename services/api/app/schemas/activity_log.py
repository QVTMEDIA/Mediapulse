from datetime import datetime
from typing import List, Optional

from .common import CamelModel


class ActivityLogEntryOut(CamelModel):
    entry_id: str
    actor_id: Optional[str]
    actor_name: str
    action: str
    summary: str
    project_id: Optional[str]
    project_name: Optional[str]
    created_at: datetime


class ActivityLogPageOut(CamelModel):
    """GET /api/activity-log's response shape -- paginated rather than the
    whole account's history in one response, same reasoning as
    RatingsRowsPageOut."""

    entries: List[ActivityLogEntryOut]
    # Total entries across the whole account, not just len(entries) -- for
    # pagination UI.
    total: int
