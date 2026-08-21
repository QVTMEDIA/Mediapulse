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
    source_file: str
