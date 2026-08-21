import { useCallback, useEffect, useMemo, useRef, useState, type FormEvent, type KeyboardEvent } from 'react';
import {
  Activity as ActivityIcon,
  AlertTriangle,
  Archive,
  BarChart3,
  Database,
  FileSpreadsheet,
  FolderOpen,
  Gauge,
  GitCompare,
  History,
  LogOut,
  Search,
  Settings,
  Upload,
  Wrench,
} from 'lucide-react';
import AuthScreen from './AuthScreen';
import {
  ApiError,
  archiveProject,
  calculateProject,
  createBrand,
  createProject,
  getAuthToken,
  getCurrentUser,
  getLatestRun,
  listBrandShares,
  listBrands,
  listMappingTemplates,
  listProjects,
  listVersions,
  onAuthTokenRejected,
  restoreVersion,
  setAuthToken,
  uploadMediaReport,
} from './api/client';
import type { AuthSession, Brand, BrandShare, GrpRunSummary, Project, ProjectVersion, UploadKind, User } from './api/contracts';
import ActivitySection from './sections/ActivitySection';
import ExportsSection from './sections/ExportsSection';
import MatchesSection from './sections/MatchesSection';
import ProjectManagePanel from './sections/ProjectManagePanel';
import QualitySection from './sections/QualitySection';
import RatingsSection from './sections/RatingsSection';
import ReportsSection from './sections/ReportsSection';
import SettingsSection from './sections/SettingsSection';

type SectionKey = 'projects' | 'ratings' | 'matches' | 'activity' | 'reports' | 'quality' | 'exports' | 'settings';

const SECTION_LABELS: Record<SectionKey, string> = {
  projects: 'Projects',
  ratings: 'Ratings',
  matches: 'Matches',
  activity: 'Activity',
  reports: 'Reports',
  quality: 'Quality',
  exports: 'Exports',
  settings: 'Settings',
};

const SECTION_DESCRIPTIONS: Partial<Record<SectionKey, string>> = {
  ratings: 'Upload ratings, or attach an existing dataset from the shared library.',
  matches: 'Review fuzzy-matched and unmatched spots before calculating.',
  activity: 'Every calculated row, traceable back to its spot — the audit trail behind the brand totals.',
  reports: 'Station and programme contribution, weekly trend, and brand-vs-brand comparison.',
  quality: 'Missing ratings, duplicate keys, and skipped upload rows for this project.',
  settings: 'Your account, and — for owners and admins — everyone else on this deployment.',
  exports: 'Generate and download the full Excel workbook for this project.',
};

const navItems: { key: SectionKey; icon: typeof FolderOpen }[] = [
  { key: 'projects', icon: FolderOpen },
  { key: 'ratings', icon: Database },
  { key: 'matches', icon: GitCompare },
  { key: 'activity', icon: ActivityIcon },
  { key: 'reports', icon: FileSpreadsheet },
  { key: 'quality', icon: AlertTriangle },
  { key: 'exports', icon: Upload },
  { key: 'settings', icon: Settings },
];

const statusClass = {
  Setup: 'status status-setup',
  'Data Review': 'status status-review',
  Complete: 'status status-complete',
};

function formatNumber(value: number) {
  return new Intl.NumberFormat('en-US', { maximumFractionDigits: 1 }).format(value);
}

function formatPeriod(project: Project) {
  if (project.startDate && project.endDate) return `${project.startDate} to ${project.endDate}`;
  return project.startDate || project.endDate || 'No dates set';
}

function ProjectRow({
  project,
  isActive,
  onSelect,
}: {
  project: Project;
  isActive: boolean;
  onSelect: () => void;
}) {
  function handleKeyDown(event: KeyboardEvent<HTMLElement>) {
    if (event.key === 'Enter' || event.key === ' ') {
      event.preventDefault();
      onSelect();
    }
  }

  return (
    <article
      className={isActive ? 'project-row active' : 'project-row'}
      role="button"
      tabIndex={0}
      aria-pressed={isActive}
      onClick={onSelect}
      onKeyDown={handleKeyDown}
    >
      <div className="project-main">
        <div>
          <h3>{project.projectName}</h3>
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
    </article>
  );
}

function BrandShareRow({ share, maxGrp }: { share: BrandShare; maxGrp: number }) {
  const width = maxGrp ? `${Math.max((share.totalGrps / maxGrp) * 100, 3)}%` : '3%';
  // Split the bar itself by TV/Radio GRP share, not just report the numbers
  // in the caption — tvGrps/radioGrps summed to totalGrps back on Phase 1,
  // this is the first place either value gets rendered anywhere.
  const isMixedMedia = share.tvGrps > 0 && share.radioGrps > 0;
  const tvShare = share.totalGrps > 0 ? (share.tvGrps / share.totalGrps) * 100 : 100;
  return (
    <div className="brand-row">
      <div className="brand-line">
        <span>{share.brand}</span>
        <span className="brand-share-metrics">
          <strong>{share.sov.toFixed(1)}% SOV</strong>
          {/* SOE tracks spend, not GRPs — a brand can lead SOV while trailing
              SOE (or vice versa) since spend counts every uploaded row,
              matched or not. Only shown once spend data exists for this
              category, so an all-null-cost project doesn't render a
              meaningless "0.0% SOE" on every brand. */}
          {share.totalSpend > 0 ? <strong className="soe-value">{share.soe.toFixed(1)}% SOE</strong> : null}
        </span>
      </div>
      <div className="bar-track" aria-label={`${share.brand} GRP contribution`}>
        {isMixedMedia ? (
          <div className="bar-fill split" style={{ width }}>
            <div className="bar-fill-tv" style={{ width: `${tvShare}%` }} />
            <div className="bar-fill-radio" style={{ width: `${100 - tvShare}%` }} />
          </div>
        ) : (
          <div className="bar-fill" style={{ width, background: share.radioGrps > 0 ? 'var(--blue)' : undefined }} />
        )}
      </div>
      <small>
        {share.spots} spots | {share.totalGrps.toFixed(1)} GRPs
        {isMixedMedia ? ` (TV ${share.tvGrps.toFixed(1)} · Radio ${share.radioGrps.toFixed(1)})` : ''}
        {share.avgRating !== null ? ` | avg rating ${share.avgRating.toFixed(2)}` : ''}
        {share.totalSpend > 0 ? ` | spend ${formatNumber(share.totalSpend)}` : ''}
      </small>
    </div>
  );
}

function ComingSoonPanel({ section }: { section: SectionKey }) {
  return (
    <div className="panel placeholder-panel">
      <h2>{SECTION_LABELS[section]} isn't built yet</h2>
      <p>This screen is on the roadmap but not implemented — see PRODUCT_ROADMAP.md for what's planned here.</p>
    </div>
  );
}

function Workspace({ currentUser, onSignOut }: { currentUser: User; onSignOut: () => void }) {
  const [activeSection, setActiveSection] = useState<SectionKey>('projects');
  const [projects, setProjects] = useState<Project[]>([]);
  const [projectsLoading, setProjectsLoading] = useState(true);
  const [projectsError, setProjectsError] = useState<string | null>(null);
  const [searchInput, setSearchInput] = useState('');
  const [activeProjectId, setActiveProjectId] = useState<string | null>(null);
  const [isCreating, setIsCreating] = useState(false);
  const [newProjectName, setNewProjectName] = useState('');
  const [formError, setFormError] = useState<string | null>(null);
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [actionError, setActionError] = useState<string | null>(null);
  const [latestRun, setLatestRun] = useState<GrpRunSummary | null>(null);
  const [brandShares, setBrandShares] = useState<BrandShare[]>([]);
  const [runLoading, setRunLoading] = useState(false);
  const [runError, setRunError] = useState<string | null>(null);
  const [isCalculating, setIsCalculating] = useState(false);
  const [calculateError, setCalculateError] = useState<string | null>(null);
  const [versions, setVersions] = useState<ProjectVersion[]>([]);
  const [versionsLoading, setVersionsLoading] = useState(false);
  const [versionsError, setVersionsError] = useState<string | null>(null);
  const [restoringVersionId, setRestoringVersionId] = useState<string | null>(null);
  const [brands, setBrands] = useState<Brand[]>([]);
  const [brandsLoading, setBrandsLoading] = useState(false);
  const [isUploadOpen, setIsUploadOpen] = useState(false);
  const [isManageOpen, setIsManageOpen] = useState(false);
  const [newBrandName, setNewBrandName] = useState('');
  const [isCreatingBrand, setIsCreatingBrand] = useState(false);
  const [brandFormError, setBrandFormError] = useState<string | null>(null);
  const [selectedBrandId, setSelectedBrandId] = useState('');
  const [uploadKind, setUploadKind] = useState<Extract<UploadKind, 'brand_report' | 'composite_report'>>('brand_report');
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [uploadDefaultMedium, setUploadDefaultMedium] = useState('TV');
  const [uploadSourceLabel, setUploadSourceLabel] = useState('');
  const [uploadSaveAsTemplate, setUploadSaveAsTemplate] = useState(false);
  const [knownSourceLabels, setKnownSourceLabels] = useState<string[]>([]);
  const [fileInputKey, setFileInputKey] = useState(0);
  const [isUploading, setIsUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [uploadSuccess, setUploadSuccess] = useState<string | null>(null);
  // Guards against a slow response for a project the user has since
  // navigated away from landing after a newer request already resolved.
  const runRequestId = useRef(0);

  const refreshProjects = useCallback(async (search: string) => {
    setProjectsLoading(true);
    setProjectsError(null);
    try {
      const results = await listProjects({ search });
      setProjects(results);
      setActiveProjectId((current) =>
        current && results.some((project) => project.projectId === current) ? current : results[0]?.projectId ?? null,
      );
    } catch (error) {
      setProjectsError(error instanceof ApiError ? error.message : 'Could not reach the Mediapulse API.');
    } finally {
      setProjectsLoading(false);
    }
  }, []);

  // Debounced so every keystroke in the search box doesn't fire a request.
  useEffect(() => {
    const handle = setTimeout(() => {
      void refreshProjects(searchInput.trim());
    }, 250);
    return () => clearTimeout(handle);
  }, [searchInput, refreshProjects]);

  const activeProject = useMemo(
    () => projects.find((project) => project.projectId === activeProjectId) ?? null,
    [projects, activeProjectId],
  );

  const refreshRun = useCallback(async (projectId: string) => {
    const requestId = ++runRequestId.current;
    setRunLoading(true);
    setRunError(null);
    try {
      const run = await getLatestRun(projectId);
      if (runRequestId.current !== requestId) return; // superseded by a newer request
      setLatestRun(run);
      setBrandShares(run ? await listBrandShares(projectId, run.runId) : []);
      if (runRequestId.current !== requestId) return;
    } catch (error) {
      if (runRequestId.current !== requestId) return;
      setLatestRun(null);
      setBrandShares([]);
      setRunError(error instanceof ApiError ? error.message : 'Could not load GRP results.');
    } finally {
      if (runRequestId.current === requestId) setRunLoading(false);
    }
  }, []);

  useEffect(() => {
    if (activeProjectId) {
      void refreshRun(activeProjectId);
    } else {
      runRequestId.current += 1; // invalidate any in-flight request from a project we've left
      setLatestRun(null);
      setBrandShares([]);
      setRunError(null);
    }
  }, [activeProjectId, refreshRun]);

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
    if (activeProjectId) {
      void refreshVersions(activeProjectId);
    } else {
      setVersions([]);
      setVersionsError(null);
    }
  }, [activeProjectId, refreshVersions]);

  async function handleRestoreVersion(versionId: string) {
    if (!activeProject) return;
    setRestoringVersionId(versionId);
    setVersionsError(null);
    try {
      await restoreVersion(activeProject.projectId, versionId);
      await Promise.all([refreshVersions(activeProject.projectId), refreshRun(activeProject.projectId)]);
    } catch (error) {
      setVersionsError(error instanceof ApiError ? error.message : 'Could not restore that version.');
    } finally {
      setRestoringVersionId(null);
    }
  }

  const refreshBrands = useCallback(async (projectId: string) => {
    setBrandsLoading(true);
    try {
      const results = await listBrands(projectId);
      setBrands(results);
      setSelectedBrandId((current) =>
        current && results.some((brand) => brand.brandId === current) ? current : results[0]?.brandId ?? '',
      );
    } catch {
      // Brand list failing to load only degrades the upload form (handled
      // inline there) — it isn't worth a page-level error banner.
      setBrands([]);
    } finally {
      setBrandsLoading(false);
    }
  }, []);

  useEffect(() => {
    if (activeProjectId) {
      void refreshBrands(activeProjectId);
    } else {
      setBrands([]);
      setSelectedBrandId('');
    }
  }, [activeProjectId, refreshBrands]);

  const maxGrp = Math.max(1, ...brandShares.map((share) => share.totalGrps));

  async function handleCreateProject(event: FormEvent) {
    event.preventDefault();
    const trimmed = newProjectName.trim();
    if (!trimmed) {
      setFormError('Project name is required.');
      return;
    }
    setIsSubmitting(true);
    setFormError(null);
    try {
      const created = await createProject({ projectName: trimmed });
      setNewProjectName('');
      setIsCreating(false);
      await refreshProjects(searchInput.trim());
      setActiveProjectId(created.projectId);
    } catch (error) {
      setFormError(error instanceof ApiError ? error.message : 'Could not create the project.');
    } finally {
      setIsSubmitting(false);
    }
  }

  async function handleArchiveActiveProject() {
    if (!activeProject) return;
    setActionError(null);
    try {
      await archiveProject(activeProject.projectId);
      await refreshProjects(searchInput.trim());
    } catch (error) {
      setActionError(error instanceof ApiError ? error.message : 'Could not archive the project.');
    }
  }

  function handleProjectUpdated(updated: Project) {
    setProjects((current) => current.map((project) => (project.projectId === updated.projectId ? updated : project)));
  }

  async function handleCalculate() {
    if (!activeProject) return;
    setIsCalculating(true);
    setCalculateError(null);
    try {
      await calculateProject(activeProject.projectId);
      await Promise.all([refreshRun(activeProject.projectId), refreshVersions(activeProject.projectId)]);
    } catch (error) {
      setCalculateError(error instanceof ApiError ? error.message : 'Could not calculate GRPs.');
    } finally {
      setIsCalculating(false);
    }
  }

  async function handleCreateBrand() {
    if (!activeProject) return;
    const trimmed = newBrandName.trim();
    if (!trimmed) {
      setBrandFormError('Brand name is required.');
      return;
    }
    setIsCreatingBrand(true);
    setBrandFormError(null);
    try {
      const created = await createBrand(activeProject.projectId, trimmed);
      setNewBrandName('');
      await refreshBrands(activeProject.projectId);
      setSelectedBrandId(created.brandId);
    } catch (error) {
      setBrandFormError(error instanceof ApiError ? error.message : 'Could not create the brand.');
    } finally {
      setIsCreatingBrand(false);
    }
  }

  async function handleUploadSubmit(event: FormEvent) {
    event.preventDefault();
    if (!activeProject || !uploadFile || (uploadKind === 'brand_report' && !selectedBrandId)) {
      setUploadError(
        uploadKind === 'brand_report' ? 'Choose a brand and a file first.' : 'Choose a file first.',
      );
      return;
    }
    setIsUploading(true);
    setUploadError(null);
    setUploadSuccess(null);
    try {
      const result = await uploadMediaReport(activeProject.projectId, {
        kind: uploadKind,
        brandId: uploadKind === 'brand_report' ? selectedBrandId : undefined,
        defaultMedium: uploadDefaultMedium,
        file: uploadFile,
        sourceLabel: uploadSourceLabel.trim() || undefined,
        saveAsTemplate: uploadSaveAsTemplate,
      });
      setUploadSuccess(
        `Uploaded ${result.fileName}: ${result.mappedRows} row${result.mappedRows === 1 ? '' : 's'} mapped` +
          (result.issueRows ? `, ${result.issueRows} skipped with issues.` : '.') +
          ' Click Calculate to include it in a run.',
      );
      setUploadFile(null);
      setFileInputKey((key) => key + 1);
      if (uploadSourceLabel.trim()) {
        setKnownSourceLabels((current) =>
          current.includes(uploadSourceLabel.trim()) ? current : [...current, uploadSourceLabel.trim()],
        );
      }
    } catch (error) {
      setUploadError(error instanceof ApiError ? error.message : 'Could not upload the file.');
    } finally {
      setIsUploading(false);
    }
  }

  return (
    <div className="app-shell">
      <aside className="sidebar">
        <div className="brand-mark">
          <div className="brand-icon">
            <Gauge size={22} aria-hidden />
          </div>
          <div>
            <strong>Mediapulse</strong>
            <span>Media intelligence</span>
          </div>
        </div>

        <nav className="nav-list" aria-label="Primary navigation">
          {navItems.map((item) => {
            const Icon = item.icon;
            const isActive = item.key === activeSection;
            return (
              <button
                type="button"
                className={isActive ? 'nav-item active' : 'nav-item'}
                key={item.key}
                aria-current={isActive ? 'page' : undefined}
                onClick={() => setActiveSection(item.key)}
              >
                <Icon size={18} aria-hidden />
                <span>{SECTION_LABELS[item.key]}</span>
              </button>
            );
          })}
        </nav>

        <div className="sidebar-note">
          <span>Active project</span>
          <strong>{activeProject ? activeProject.projectName : 'No project selected'}</strong>
          <small>{activeProject ? activeProject.updatedAt : projectsLoading ? 'Loading…' : 'Create a project to get started'}</small>
        </div>

        <div className="sidebar-user">
          <div>
            <strong>{currentUser.displayName || currentUser.email}</strong>
            <small>{currentUser.role}</small>
          </div>
          <button type="button" className="icon-button" title="Sign out" aria-label="Sign out" onClick={onSignOut}>
            <LogOut size={16} aria-hidden />
          </button>
        </div>
      </aside>

      <main className="workspace">
        <header className="topbar">
          <div>
            <h1>{SECTION_LABELS[activeSection]}</h1>
            <p>
              {activeSection === 'projects'
                ? activeProject
                  ? `${activeProject.category || 'Uncategorized'} performance, ratings coverage, and GRP quality.`
                  : 'Create a project to start tracking GRPs and Share of Voice.'
                : SECTION_DESCRIPTIONS[activeSection] ?? "This area isn't built yet."}
            </p>
          </div>
          {activeSection === 'projects' && (
            <div className="toolbar">
              <label className="search-box">
                <Search size={17} aria-hidden />
                <input
                  type="search"
                  placeholder="Search projects, brands, stations"
                  value={searchInput}
                  onChange={(event) => setSearchInput(event.target.value)}
                />
              </label>
              <button
                type="button"
                className="icon-button"
                aria-label="Project settings"
                title={activeProject ? `Edit ${activeProject.projectName} and manage its data` : 'Select a project first'}
                disabled={!activeProject}
                onClick={() => setIsManageOpen((open) => !open)}
              >
                <Wrench size={18} aria-hidden />
              </button>
              <button
                type="button"
                className="icon-button"
                aria-label="Archive active project"
                title={activeProject ? `Archive ${activeProject.projectName}` : 'Select a project to archive'}
                disabled={!activeProject}
                onClick={handleArchiveActiveProject}
              >
                <Archive size={18} aria-hidden />
              </button>
              <button
                type="button"
                className="secondary-button"
                disabled={!activeProject || isCalculating}
                title={activeProject ? `Calculate GRPs for ${activeProject.projectName}` : 'Select a project first'}
                onClick={handleCalculate}
              >
                <BarChart3 size={18} aria-hidden />
                {isCalculating ? 'Calculating…' : 'Calculate'}
              </button>
              <button
                type="button"
                className="primary-button"
                disabled={!activeProject}
                title={activeProject ? 'Upload a brand report' : 'Select a project first'}
                onClick={() => {
                  setIsUploadOpen((open) => !open);
                  setUploadError(null);
                  setUploadSuccess(null);
                  if (knownSourceLabels.length === 0) {
                    void listMappingTemplates()
                      .then((templates) => setKnownSourceLabels(templates.map((template) => template.sourceLabel)))
                      .catch(() => {
                        // Autocomplete is a nicety — a failed fetch just leaves the datalist empty.
                      });
                  }
                }}
              >
                <Upload size={18} aria-hidden />
                Upload
              </button>
            </div>
          )}
        </header>

        {activeSection === 'ratings' ? (
          <RatingsSection project={activeProject} />
        ) : activeSection === 'matches' ? (
          <MatchesSection project={activeProject} />
        ) : activeSection === 'activity' ? (
          <ActivitySection project={activeProject} />
        ) : activeSection === 'reports' ? (
          <ReportsSection project={activeProject} />
        ) : activeSection === 'quality' ? (
          <QualitySection project={activeProject} />
        ) : activeSection === 'settings' ? (
          <SettingsSection currentUser={currentUser} />
        ) : activeSection === 'exports' ? (
          <ExportsSection project={activeProject} />
        ) : activeSection !== 'projects' ? (
          <ComingSoonPanel section={activeSection} />
        ) : (
          <>
            {[actionError, calculateError, runError].filter(Boolean).map((message, index) => (
              <p className="inline-error" key={index}>{message}</p>
            ))}

            {isManageOpen && activeProject && (
              <ProjectManagePanel
                project={activeProject}
                currentUser={currentUser}
                onProjectUpdated={handleProjectUpdated}
                onClose={() => setIsManageOpen(false)}
              />
            )}

            {isUploadOpen && activeProject && (
              <form className="panel upload-form" onSubmit={handleUploadSubmit}>
                <div className="panel-header">
                  <div>
                    <h2>Upload media report</h2>
                    <p>
                      {activeProject.projectName} — .xlsx, .xls, or .csv
                      {uploadKind === 'brand_report' ? ', one brand per file' : ', multiple brands read from a Brand column'}
                    </p>
                  </div>
                </div>

                <div className="upload-form-row">
                  <label>
                    Report type
                    <select
                      value={uploadKind}
                      onChange={(event) => setUploadKind(event.target.value as typeof uploadKind)}
                    >
                      <option value="brand_report">Brand report (single brand)</option>
                      <option value="composite_report">Composite report (multi-brand)</option>
                    </select>
                  </label>
                  <label>
                    Default medium (used if the file has no Medium column)
                    <select value={uploadDefaultMedium} onChange={(event) => setUploadDefaultMedium(event.target.value)}>
                      <option value="TV">TV</option>
                      <option value="Radio">Radio</option>
                    </select>
                  </label>
                </div>

                {uploadKind === 'brand_report' && (
                  <>
                    <div className="upload-form-row">
                      <label>
                        Brand
                        <select
                          value={selectedBrandId}
                          onChange={(event) => setSelectedBrandId(event.target.value)}
                          disabled={brandsLoading || brands.length === 0}
                        >
                          {brands.length === 0 && <option value="">{brandsLoading ? 'Loading…' : 'No brands yet'}</option>}
                          {brands.map((brand) => (
                            <option value={brand.brandId} key={brand.brandId}>
                              {brand.name}
                            </option>
                          ))}
                        </select>
                      </label>
                      <label>
                        Or create a brand
                        <input
                          type="text"
                          placeholder="New brand name"
                          value={newBrandName}
                          onChange={(event) => setNewBrandName(event.target.value)}
                        />
                      </label>
                    </div>
                    <div className="upload-form-row">
                      <button
                        type="button"
                        className="secondary-button"
                        disabled={isCreatingBrand || !newBrandName.trim()}
                        onClick={handleCreateBrand}
                      >
                        {isCreatingBrand ? 'Adding…' : 'Add brand'}
                      </button>
                    </div>
                    {brandFormError && <p className="inline-error">{brandFormError}</p>}
                  </>
                )}

                <div className="upload-form-row">
                  <label>
                    Source label (optional)
                    <input
                      type="text"
                      list="known-source-labels"
                      placeholder="e.g. Nielsen weekly export"
                      value={uploadSourceLabel}
                      onChange={(event) => setUploadSourceLabel(event.target.value)}
                    />
                    <datalist id="known-source-labels">
                      {knownSourceLabels.map((label) => (
                        <option value={label} key={label} />
                      ))}
                    </datalist>
                  </label>
                  <label className="checkbox-field">
                    <input
                      type="checkbox"
                      checked={uploadSaveAsTemplate}
                      onChange={(event) => setUploadSaveAsTemplate(event.target.checked)}
                    />
                    Remember this column mapping for this source label
                  </label>
                </div>
                <p className="field-hint">
                  {knownSourceLabels.includes(uploadSourceLabel.trim())
                    ? 'A saved mapping exists for this label — it will be applied automatically.'
                    : 'A new label saves the mapping this file actually uses, so later uploads from the same source map automatically.'}
                </p>

                <label>
                  File
                  <input
                    type="file"
                    key={fileInputKey}
                    accept=".xlsx,.xls,.csv"
                    onChange={(event) => setUploadFile(event.target.files?.[0] ?? null)}
                  />
                </label>

                <div className="form-actions">
                  <button
                    type="submit"
                    className="primary-button"
                    disabled={isUploading || !uploadFile || (uploadKind === 'brand_report' && !selectedBrandId)}
                  >
                    {isUploading ? 'Uploading…' : 'Upload'}
                  </button>
                  <button type="button" className="secondary-button" onClick={() => setIsUploadOpen(false)}>
                    Close
                  </button>
                </div>
                {uploadError && <p className="inline-error">{uploadError}</p>}
                {uploadSuccess && <p className="empty-state">{uploadSuccess}</p>}
              </form>
            )}

            <section className="metric-grid" aria-label="Workspace metrics">
              <div className="metric-panel">
                <span>Total GRPs</span>
                <strong>{latestRun ? formatNumber(latestRun.totalGrps) : '—'}</strong>
                <small>
                  {runLoading
                    ? 'Loading…'
                    : latestRun
                      ? `Run generated ${latestRun.generatedAt}`
                      : activeProject
                        ? 'No calculation yet — click Calculate'
                        : 'Select a project'}
                </small>
              </div>
              <div className="metric-panel">
                <span>Matched Rows</span>
                <strong>{latestRun ? latestRun.matchedRows : '—'}</strong>
                <small>{latestRun ? `${latestRun.unmatchedRows} unmatched` : ' '}</small>
              </div>
              <div className="metric-panel">
                <span>Brands</span>
                <strong>{latestRun ? latestRun.totalBrands : '—'}</strong>
                <small>{latestRun ? `${latestRun.totalSpots} total spots` : ' '}</small>
              </div>
              <div className="metric-panel">
                <span>Total Spend</span>
                <strong>{latestRun ? formatNumber(latestRun.totalSpend) : '—'}</strong>
                <small>{latestRun && latestRun.totalSpend === 0 ? 'No cost/rate column mapped yet' : ' '}</small>
              </div>
            </section>

            <section className="content-grid">
              <div className="panel project-panel">
                <div className="panel-header">
                  <div>
                    <h2>Projects</h2>
                    <p>{projectsLoading ? 'Loading…' : `${projects.length} workspace${projects.length === 1 ? '' : 's'}`}</p>
                  </div>
                  <button
                    type="button"
                    className="secondary-button"
                    onClick={() => {
                      setIsCreating((open) => !open);
                      setFormError(null);
                    }}
                  >
                    <FolderOpen size={17} aria-hidden />
                    New
                  </button>
                </div>

                {isCreating && (
                  <form className="create-project-form" onSubmit={handleCreateProject}>
                    <input
                      type="text"
                      placeholder="Project name"
                      value={newProjectName}
                      onChange={(event) => setNewProjectName(event.target.value)}
                      autoFocus
                    />
                    <div className="form-actions">
                      <button type="submit" className="primary-button" disabled={isSubmitting}>
                        {isSubmitting ? 'Creating…' : 'Create'}
                      </button>
                      <button
                        type="button"
                        className="secondary-button"
                        onClick={() => {
                          setIsCreating(false);
                          setFormError(null);
                        }}
                      >
                        Cancel
                      </button>
                    </div>
                    {formError && <p className="inline-error">{formError}</p>}
                  </form>
                )}

                {projectsError && <p className="inline-error">{projectsError}</p>}

                <div className="project-list">
                  {!projectsLoading && projects.length === 0 && !projectsError && (
                    <p className="empty-state">No projects yet. Click "New" to create one.</p>
                  )}
                  {projects.map((project) => (
                    <ProjectRow
                      project={project}
                      key={project.projectId}
                      isActive={project.projectId === activeProjectId}
                      onSelect={() => setActiveProjectId(project.projectId)}
                    />
                  ))}
                </div>
              </div>

              <div className="panel">
                <div className="panel-header">
                  <div>
                    <h2>Brand SOV</h2>
                    <p>
                      {runLoading
                        ? 'Loading…'
                        : latestRun
                          ? `Run generated ${latestRun.generatedAt}`
                          : 'No calculation yet for this project'}
                    </p>
                  </div>
                  <BarChart3 size={20} aria-hidden />
                </div>
                {brandShares.some((share) => share.tvGrps > 0 && share.radioGrps > 0) && (
                  <div className="medium-split-legend">
                    <span><i className="tv" /> TV</span>
                    <span><i className="radio" /> Radio</span>
                  </div>
                )}
                <div className="brand-list">
                  {!runLoading && brandShares.length === 0 && (
                    <p className="empty-state">
                      {activeProject ? 'No GRP run yet — click Calculate in the toolbar.' : 'Select a project.'}
                    </p>
                  )}
                  {brandShares.map((share) => (
                    <BrandShareRow share={share} maxGrp={maxGrp} key={share.brandId} />
                  ))}
                </div>
              </div>
            </section>

            {activeProject && versions.length > 0 && (
              <div className="panel">
                <div className="panel-header">
                  <div>
                    <h2>Version History</h2>
                    <p>
                      {versionsLoading
                        ? 'Loading…'
                        : `Every calculation for ${activeProject.projectName}, oldest calculations kept even after a newer one lands`}
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
                          <td>
                            {version.isCurrent && <span className="status status-complete">Current</span>}
                          </td>
                          <td>
                            {!version.isCurrent && (currentUser.role === 'owner' || currentUser.role === 'admin') && (
                              <button
                                type="button"
                                className="secondary-button"
                                disabled={restoringVersionId === version.versionId}
                                onClick={() => handleRestoreVersion(version.versionId)}
                                title={`Make this the current version for ${activeProject.projectName}`}
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
        )}
      </main>
    </div>
  );
}

function App() {
  // 'checking' avoids a flash of the login screen while a stored token is
  // still being validated against GET /auth/me on first load.
  const [authState, setAuthState] = useState<{ status: 'checking' | 'signedOut' | 'signedIn'; user: User | null }>({
    status: 'checking',
    user: null,
  });

  useEffect(() => {
    onAuthTokenRejected(() => setAuthState({ status: 'signedOut', user: null }));
    return () => onAuthTokenRejected(null);
  }, []);

  useEffect(() => {
    const token = getAuthToken();
    if (!token) {
      setAuthState({ status: 'signedOut', user: null });
      return;
    }
    let cancelled = false;
    void getCurrentUser()
      .then((user) => {
        if (!cancelled) setAuthState({ status: 'signedIn', user });
      })
      .catch(() => {
        setAuthToken(null);
        if (!cancelled) setAuthState({ status: 'signedOut', user: null });
      });
    return () => {
      cancelled = true;
    };
  }, []);

  function handleAuthenticated(session: AuthSession) {
    setAuthState({ status: 'signedIn', user: session.user });
  }

  function handleSignOut() {
    setAuthToken(null);
    setAuthState({ status: 'signedOut', user: null });
  }

  if (authState.status === 'checking') {
    return <div className="auth-shell" aria-busy="true" />;
  }
  if (authState.status === 'signedOut' || !authState.user) {
    return <AuthScreen onAuthenticated={handleAuthenticated} />;
  }
  return <Workspace currentUser={authState.user} onSignOut={handleSignOut} />;
}

export default App;
