import { useCallback, useEffect, useState } from 'react';
import { ApiError, listValidationIssues } from '../api/client';
import type { Project, ValidationIssue } from '../api/contracts';
import { LimitedRows } from '../components/LimitedRows';

export default function QualitySection({ project }: { project: Project | null }) {
  const [issues, setIssues] = useState<ValidationIssue[]>([]);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);

  const refresh = useCallback(async (projectId: string) => {
    setLoading(true);
    setLoadError(null);
    try {
      setIssues(await listValidationIssues(projectId));
    } catch (error) {
      setLoadError(error instanceof ApiError ? error.message : 'Could not load data quality issues.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (project) {
      void refresh(project.projectId);
    } else {
      setIssues([]);
    }
  }, [project, refresh]);

  if (!project) {
    return (
      <div className="panel placeholder-panel">
        <h2>No project selected</h2>
        <p>Open or create a project to see its data quality issues.</p>
      </div>
    );
  }

  const totalRows = issues.reduce((sum, issue) => sum + issue.rows, 0);

  return (
    <>
      <section className="metric-grid" aria-label="Data quality summary">
        <div className="metric-panel">
          <span>Open Issues</span>
          <strong>{issues.length}</strong>
          <small>{loading ? 'Loading…' : ' '}</small>
        </div>
        <div className="metric-panel warning-panel">
          <span>Rows Affected</span>
          <strong>{totalRows}</strong>
          <small>across ratings and uploads</small>
        </div>
      </section>

      {loadError && <p className="inline-error">{loadError}</p>}

      <div className="panel">
        <div className="panel-header">
          <div>
            <h2>Data Quality</h2>
            <p>Missing ratings, duplicate keys, and skipped upload rows for {project.projectName}</p>
          </div>
        </div>
        <div className="issue-list">
          {!loading && issues.length === 0 && !loadError && (
            <p className="empty-state">No issues found — ratings and uploads for this project look clean.</p>
          )}
          <LimitedRows rows={issues} render={(issue) => (
            <div className="issue-row" key={issue.issueId}>
              <span className="issue-dot" />
              <div>
                <strong>{issue.area}</strong>
                <p>{issue.message}</p>
              </div>
              <small>{issue.rows} row{issue.rows === 1 ? '' : 's'}</small>
            </div>
          )} />
        </div>
      </div>
    </>
  );
}
