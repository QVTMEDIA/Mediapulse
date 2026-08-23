import { useCallback, useEffect, useState } from 'react';
import { ApiError, getLatestRun, listCalculations } from '../api/client';
import type { GrpCalculationRow, GrpRunSummary, Project } from '../api/contracts';
import { LimitedRowsControls, useLimitedRows } from '../components/LimitedRows';

export default function ActivitySection({ project }: { project: Project | null }) {
  const [run, setRun] = useState<GrpRunSummary | null>(null);
  const [rows, setRows] = useState<GrpCalculationRow[]>([]);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const limitedRows = useLimitedRows(rows);

  const refresh = useCallback(async (projectId: string) => {
    setLoading(true);
    setLoadError(null);
    try {
      const latestRun = await getLatestRun(projectId);
      setRun(latestRun);
      setRows(latestRun ? await listCalculations(projectId, latestRun.runId) : []);
    } catch (error) {
      setLoadError(error instanceof ApiError ? error.message : 'Could not load the calculation.');
      setRun(null);
      setRows([]);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (project) {
      void refresh(project.projectId);
    } else {
      setRun(null);
      setRows([]);
    }
  }, [project, refresh]);

  if (!project) {
    return (
      <div className="panel placeholder-panel">
        <h2>No project selected</h2>
        <p>Open or create a project to see its spot-level calculation.</p>
      </div>
    );
  }

  return (
    <div className="panel">
      <div className="panel-header">
        <div>
          <h2>Spot-level GRP</h2>
          <p>
            {loading
              ? 'Loading…'
              : run
                ? `Run generated ${run.generatedAt} — every calculated row traces back to its spot`
                : 'No calculation yet — go to Projects and click Calculate'}
          </p>
        </div>
      </div>
      {loadError && <p className="inline-error">{loadError}</p>}
      {!loading && run && rows.length === 0 && (
        <p className="empty-state">This run has no matched rows — nothing to calculate yet.</p>
      )}
      {rows.length > 0 && (
        <div className="table-scroll">
          <table className="data-table">
            <thead>
              <tr>
                <th>Brand</th>
                <th>Station</th>
                <th>Programme</th>
                <th>Day</th>
                <th>Medium</th>
                <th className="num">Spots</th>
                <th className="num">Rating</th>
                <th className="num">GRP</th>
              </tr>
            </thead>
            <tbody>
              {limitedRows.visibleRows.map((row) => (
                <tr key={row.grpCalculationId}>
                  <td>{row.brand}</td>
                  <td>{row.station}</td>
                  <td>{row.programme || '—'}</td>
                  <td>{row.day}</td>
                  <td>{row.medium}</td>
                  <td className="num">{row.spots}</td>
                  <td className="num">{row.rating.toFixed(2)}</td>
                  <td className="num">{row.grp.toFixed(2)}</td>
                </tr>
              ))}
            </tbody>
          </table>
          <LimitedRowsControls {...limitedRows} total={rows.length} />
        </div>
      )}
    </div>
  );
}
