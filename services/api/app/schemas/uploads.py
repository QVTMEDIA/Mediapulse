from datetime import date, datetime
from typing import Optional

from .common import CamelModel


class UploadBatchOut(CamelModel):
    upload_id: str
    project_id: str
    # Null for composite_report uploads, which span more than one brand;
    # always set for brand_report — see repositories/uploads.py.
    brand_id: Optional[str] = None
    file_name: str
    kind: str
    mapped_rows: int
    issue_rows: int
    uploaded_at: datetime


class MediaActivityRowOut(CamelModel):
    media_activity_id: str
    project_id: str
    brand_id: str
    upload_id: str
    medium: str
    station: str
    activity_date: Optional[date] = None
    day: str
    programme: str
    spots: int
    # Resolved media spend for this row (Share of Expenditure) — null means
    # no cost/rate column was ever mapped for this upload, not a confirmed
    # zero spend. See db/schema.sql's comment on media_activity.cost.
    cost: Optional[float] = None
    # Vendor's own daypart/time-band label, captured as-is (e.g. "AM",
    # "Prime Time"), separate from `programme` — see grp_calculator.py's
    # SYNONYMS['time_band'] comment. '' when the file had no such column,
    # not used for matching (only `programme`/`day`/`station`/`medium` are).
    time_band: str = ''
    source_file: str
