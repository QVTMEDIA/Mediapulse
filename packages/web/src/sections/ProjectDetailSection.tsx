import { useCallback, useEffect, useState } from 'react';
import { BarChart3, History } from 'lucide-react';
import { ApiError, getLatestRun, listBrandShares, listVersions, restoreVersion } from '../api/client';
import type { BrandShare, GrpRunSummary, Project, ProjectVersion, User } from '../api/contracts';
import { BrandShareRow } from './OverviewSection';

const statusClass = {
  Setup: 'status status-setup',
  'Data Review': 'status status-review',
  Complete: 'status status-complete',
};

function formatPeriod(project: Project) {
  if (project.startDate && project.endDate) return `${project.startDate} to ${project.endDate}`;
  return project.startDate || project.endDate || 'No dates set';
}

// The page a project row's onSelect navigates to — "detailed view of that
// project: the data, brands, SOV, version history" per what was actually
// asked for, distinct from Overview (the executive KPI dashboard, reached
// separately from the sidebar) and from the plain Projects list (search/
// create/select only, no per-project detail rendered inline anymore).
// Brands themselves (list, add, delete) live in ProjectManagePanel, which
// App.tsx renders directly below this component on the same page rather
// than duplicating that table here.
export default function ProjectDetailSection({
  project,
  currentUser,
  refreshSignal,
}: {
  project: Project;
  currentUser: User;
  // Bumped by App.tsx after a successful Calculate — project.projectId
  // alone doesn't change when a new run lands for the same project, so
  // this is what tells the effect below to refetch SOV/version history.
  refreshSignal: number;
}) {
  const [run, setRun] = useState<GrpRunSummary | null>(null);
  const [brandShares, setBrandShares] = useState<BrandShare[]>([]);
  const [sovLoading, setSovLoading] = useState(false);
  const [sovError, setSovError] = useState<string | null>(null);

  const [versions, setVersions] = useState<ProjectVersion[]>([]);
  const [versionsLoading, setVersionsLoading] = useState(false);
  const [versionsError, setVersionsError] = useState<string | null>(null);
  const [restoringVersionId, setRestoringVersionId] = useState<string | null>(null);

  const refreshSov = useCallback(async (projectId: string) => {
    setSovLoading(true);
    setSovError(null);
    try {
      const latestRun = await getLatestRun(projectId);
      setRun(latestRun);
      setBrandShares(latestRun ? await listBrandShares(projectId, latestRun.runId) : []);
    } catch (error) {
      setSovError(error instanceof ApiError ? error.message : 'Could not load Share of Voice.');
      setRun(null);
      setBrandShares([]);
    } finally {
      setSovLoading(false);
    }
  }, []);

  const refreshVersions = useCallback(async (projectId: string) => {
    setVersionsLoading(true);
    setVersionsError(null);
    try {
      setVersions(await listVersions(projectId));
    } catch (error) {
      setVersions([]);
      setVersionsError(error instanceof ApiError ? error.message : 'Could not load version history.');
    } finally {
      setVersionsLoading(false);
    }
  }, []);

  useEffect(() => {
    void refreshSov(project.projectId);
    void refreshVersions(project.projectId);
  }, [project.projectId, refreshSignal, refreshSov, refreshVersions]);

  async function handleRestoreVersion(versionId: string) {
    setRestoringVersionId(versionId);
    setVersionsError(null);
    try {
      await restoreVersion(project.projectId, versionId);
      await Promise.all([refreshVersions(project.projectId), refreshSov(project.projectId)]);
    } catch (error) {
      setVersionsError(error instanceof ApiError ? error.message : 'Could not restore that version.');
    } finally {
      setRestoringVersionId(null);
    }
  }

  const maxGrp = Math.max(1, ...brandShares.map((share) => share.totalGrps));

  return (
    <>
      <div className="panel">
        <div className="project-main">
          <div>
            <h2>{project.projectName}</h2>
            <p>
              {project.client || 'No client'} | {project.category || 'Uncategorized'} | {project.market || 'No market set'}
            </p>
          </div>
          <span className={statusClass[project.status]}>{project.status}</span>
        </div>
        <dl className="project-meta">
          <div>
            <dt>Owner</dt>
            <dd>{project.projectOwner || '—'}</dd>
          </div>
          <div>
            <dt>Period</dt>
            <dd>{formatPeriod(project)}</dd>
          </div>
          <div>
            <dt>Audience</dt>
            <dd>{project.targetAudience || '—'}</dd>
          </div>
          <div>
            <dt>Media</dt>
            <dd>{project.mediaTypes.length ? project.mediaTypes.join(', ') : '—'}</dd>
          </div>
        </dl>
        {project.notes && (
          <p className="field-hint" style={{ marginTop: 12 }}>
            {project.notes}
          </p>
        )}
      </div>

      <div className="panel">
        <div className="panel-header">
          <div>
            <h2>Share of Voice</h2>
            <p>
              {sovLoading
                ? 'Loading…'
                : run
                  ? `Run generated ${run.generatedAt}`
                  : 'No calculation yet — click Calculate above'}
            </p>
          </div>
          <BarChart3 size={20} aria-hidden />
        </div>
        {sovError && <p className="inline-error">{sovError}</p>}
        {brandShares.some(
          (share) => [share.tvGrps, share.cableTvGrps, share.radioGrps].filter((g) => g > 0).length >= 2,
        ) && (
          <div className="medium-split-legend">
            <span><i className="tv" /> TV</span>
            {brandShares.some((share) => share.cableTvGrps > 0) && (
              <span><i className="cable-tv" /> Cable TV</span>
            )}
            <span><i className="radio" /> Radio</span>
          </div>
        )}
        <div className="brand-list">
          {!sovLoading && brandShares.length === 0 && <p className="empty-state">No matched spots yet.</p>}
          {brandShares.map((share) => (
            <BrandShareRow share={share} maxGrp={maxGrp} key={share.brandId} />
          ))}
        </div>
      </div>

      {versions.length > 0 && (
        <div className="panel">
          <div className="panel-header">
            <div>
              <h2>Version History</h2>
              <p>
                {versionsLoading
                  ? 'Loading…'
                  : `Every calculation for ${project.projectName}, oldest calculations kept even after a newer one lands`}
              </p>
            </div>
            <History size={20} aria-hidden />
          </div>
          {versionsError && <p className="inline-error">{versionsError}</p>}
          <div className="table-scroll">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Generated</th>
                  <th>Summary</th>
                  <th>Status</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {versions.map((version) => (
                  <tr key={version.versionId}>
                    <td>{version.createdAt}</td>
                    <td>{version.description}</td>
                    <td>{version.isCurrent && <span className="status status-complete">Current</span>}</td>
                    <td>
                      {!version.isCurrent && (currentUser.role === 'owner' || currentUser.role === 'admin') && (
                        <button
                          type="button"
                          className="secondary-button"
                          disabled={restoringVersionId === version.versionId}
                          onClick={() => handleRestoreVersion(version.versionId)}
                          title={`Make this the current version for ${project.projectName}`}
                        >
                          {restoringVersionId === version.versionId ? 'Restoring…' : 'Restore'}
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </>
  );
}
