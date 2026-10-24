from datetime import datetime, time
from typing import List, Optional

from pydantic import Field, field_validator

from .common import CamelModel, MappingWarningOut

MEDIA_TYPE_OPTIONS = ('TV', 'Radio', 'Cable TV')


class RatingRowIn(CamelModel):
    """Deliberately loose (no required fields) rather than the tighter
    ProjectCreate-style validation: this is the shape file-upload parsing
    will eventually produce too, and blank/malformed cells from a real
    ratings file need to be storable and flagged, not rejected outright."""

    medium: str = ''
    station: str = ''
    day: str = ''
    programme: str = ''
    time_band: str = ''
    rating: Optional[float] = None
    start_time: Optional[time] = None
    end_time: Optional[time] = None
    week: Optional[int] = None
    month: Optional[int] = None
    # Geography breakdown from the uploaded file, same as media_activity/
    # soe_activity's Region/State -- purely informational, never feeds
    # match_key. Independent columns, not one falling back to the other.
    region: str = ''
    state: str = ''


class DuplicateSiblingOut(CamelModel):
    """One other row sharing a RatingRowOut's match key -- enough fields to
    describe it in the "click a flagged row for details" UI without a
    further fetch. See repositories/ratings.py's DuplicateSibling/
    _build_rows_page."""

    rating_row_id: str
    station: str
    day: str
    programme: str
    rating: Optional[float] = None


class RatingRowOut(RatingRowIn):
    rating_row_id: str
    ratings_dataset_id: str
    # Computed server-side from the WHOLE dataset, not just this row's page
    # -- see RatingsRowsPageOut. Empty when this row isn't part of a
    # duplicate-key group.
    duplicate_siblings: List[DuplicateSiblingOut] = Field(default_factory=list)


class RatingsRowsPageOut(CamelModel):
    """GET /ratings-datasets/{id}/rows's response shape -- paginated rather
    than the whole dataset in one response. See repositories/ratings.py's
    RatingsRowsPage/_build_rows_page for why (a live incident: an unbounded
    full-dataset response helped OOM-kill the backend on a 17k-row file)."""

    rows: List[RatingRowOut]
    # Total rows in the dataset, not just len(rows) -- for pagination UI.
    total: int
    # Count of stored rows (already past upload-time validation) that still
    # look invalid (missing a match field, or no rating) -- computed over
    # the whole dataset, same as `total`.
    stored_invalid_rows: int


class RatingsDatasetCreate(CamelModel):
    provider: str = ''
    period: str = ''
    market: str = ''
    audience: str = ''
    media_types: List[str] = Field(default_factory=list)
    rows: List[RatingRowIn] = Field(default_factory=list)

    @field_validator('media_types')
    @classmethod
    def _check_media_types(cls, value):
        unknown = [media for media in value if media not in MEDIA_TYPE_OPTIONS]
        if unknown:
            raise ValueError(f'unsupported media types: {unknown}. Allowed: {MEDIA_TYPE_OPTIONS}')
        return value


class RatingsRowIssueOut(CamelModel):
    """Why one specific row got dropped during file-upload parsing and
    never stored — see parsing.py's RatingsRowIssue. Only ever populated on
    the response to POST /ratings-datasets/upload; every other route that
    returns RatingsDatasetOut leaves this unset, since dropped rows are
    never persisted anywhere to look up again later."""

    row_number: int
    reason: str
    medium: str
    station: str
    day: str
    programme: str
    rating: Optional[float] = None


class RatingsDatasetOut(CamelModel):
    ratings_dataset_id: str
    provider: str
    period: str
    market: str
    audience: str
    media_types: List[str]
    rows: int
    invalid_rows: int
    duplicate_keys: int
    status: str
    uploaded_at: datetime
    # Capped (see routers/ratings.py) so a file that rejects thousands of
    # rows doesn't balloon the upload response — invalidRows above still
    # carries the true total either way.
    issues: Optional[List[RatingsRowIssueOut]] = None
    # Only ever populated on the response to POST /ratings-datasets/upload,
    # same as issues above — a saved mapping template disagreeing with
    # fresh auto-detection for a field on this upload. See
    # schemas/common.py's MappingWarningOut and parsing.py's MappingWarning.
    mapping_warnings: List[MappingWarningOut] = Field(default_factory=list)
    # Only set on GET/PUT .../projects/{projectId}/ratings-datasets* routes
    # (a dataset's priority is per-project-attachment, not a property of the
    # dataset itself) -- null on every other route, including the global
    # library listing. Lower wins when two attached datasets share an exact
    # match key; see project_ratings_datasets.priority in db/schema.sql.
    priority: Optional[int] = None


class RatingsUploadJobOut(CamelModel):
    job_id: str
    status: str  # 'queued' | 'running' | 'completed' | 'failed'
    error: Optional[str] = None
    # Real progress -- see schemas/uploads.py's UploadJobOut (the project-
    # upload equivalent) for what total/processed mean.
    total: int = 0
    processed: int = 0
    dataset: Optional[RatingsDatasetOut] = None


class RatingsDatasetPriorityUpdate(CamelModel):
    # Every currently-attached dataset id, in the new priority order
    # (index 0 = highest precedence). Must be exactly the attached set --
    # see routers/ratings.py's reorder_project_ratings_datasets.
    ordered_ratings_dataset_ids: List[str]
