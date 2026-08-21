from typing import Optional

from .common import CamelModel


class ValidationIssueOut(CamelModel):
    issue_id: str
    project_id: str
    run_id: Optional[str] = None  # these issues aren't run-scoped — see routers/validation.py
    severity: str  # 'info' | 'warning' | 'error'
    area: str
    message: str
    rows: int
