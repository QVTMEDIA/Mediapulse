from datetime import datetime

from .common import CamelModel


class ProjectVersionOut(CamelModel):
    """One entry per grp_runs row for a project — computed on read, same
    pattern as ValidationIssueOut, rather than a separate write path into
    the (otherwise real) project_versions table. versionId is the run's own
    id: there's a 1:1 relationship between a run and the version it
    represents, so a second id would just be an alias."""

    version_id: str
    project_id: str
    run_id: str
    description: str
    is_current: bool
    created_at: datetime
