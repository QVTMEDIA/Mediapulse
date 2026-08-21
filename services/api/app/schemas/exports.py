from datetime import datetime
from typing import Optional

from .common import CamelModel


class ExportCreate(CamelModel):
    format: str = 'xlsx_full'
    # Defaults to the project's current run if omitted.
    run_id: Optional[str] = None


class ExportJobOut(CamelModel):
    export_id: str
    project_id: str
    run_id: Optional[str]
    format: str
    generated_at: datetime
    download_url: str
