import { useCallback, useEffect, useMemo, useState, type FormEvent, type KeyboardEvent } from 'react';
import {
  Activity as ActivityIcon,
  AlertTriangle,
  Archive,
  ArrowLeft,
  BarChart3,
  Database,
  DollarSign,
  FileSpreadsheet,
  FolderOpen,
  Gauge,
  GitCompare,
  LayoutDashboard,
  LogOut,
  Search,
  Settings,
  Upload,
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
  listBrands,
  listMappingTemplates,
  listProjects,
  onAuthTokenRejected,
  setAuthToken,
  uploadMediaReport,
} from './api/client';
import type { AuthSession, Brand, Project, UploadKind, User } from './api/contracts';
import ActivitySection from './sections/ActivitySection';
import ExportsSection from './sections/ExportsSection';
import MatchesSection from './sections/MatchesSection';
import OverviewSection from './sections/OverviewSection';
import ProjectDetailSection from './sections/ProjectDetailSection';
import ProjectManagePanel from './sections/ProjectManagePanel';
import QualitySection from './sections/QualitySection';
import RatingsSection from './sections/RatingsSection';
import ReportsSection from './sections/ReportsSection';
import SettingsSection from './sections/SettingsSection';
import SpendIntelligenceSection from './sections/SpendIntelligenceSection';

type SectionKey =
  | 'overview'
  | 'projects'
  | 'projectDetail'
  | 'ratings'
  | 'matches'
  | 'activity'
  | 'reports'
  | 'spendIntelligence'
  | 'quality'
  | 'exports'
  | 'settings';

const SECTION_LABELS: Record<SectionKey, string> = {
  overview: 'Overview',
  projects: 'Projects',
  // Overridden per-render to the actual project name — see the topbar <h1>
  // below — this is just the fallback if somehow no project is active.
  projectDetail: 'Project',
  ratings: 'Ratings',
  matches: 'Matches',
  activity: 'Activity',
  reports: 'Reports',
  spendIntelligence: 'Spend Intelligence',
  quality: 'Quality',
  exports: 'Exports',
  settings: 'Settings',
};

const SECTION_DESCRIPTIONS: Partial<Record<SectionKey, string>> = {
  overview: 'Executive GRP/SOV dashboard for this project — KPI cards, brand ranking, and weak-inventory flags.',
  ratings: 'Upload ratings, or attach an existing dataset from the shared library.',
  matches: 'Review fuzzy-matched and unmatched spots before calculating.',
  activity: 'Every calculated row, traceable back to its spot — the audit trail behind the brand totals.',
  reports: 'Station and programme contribution, weekly trend, and brand-vs-brand comparison.',
  spendIntelligence: 'Media spend, Share of Expenditure, and cost-per-GRP efficiency by brand.',
  quality: 'Missing ratings, duplicate keys, and skipped upload rows for this project.',
  settings: 'Your account, and — for owners and admins — everyone else on this deployment.',
  exports: 'Generate and download the full Excel workbook for this project.',
};

const navItems: { key: SectionKey; icon: typeof FolderOpen }[] = [
  { key: 'overview', icon: LayoutDashboard },
  { key: 'projects', icon: FolderOpen },
  { key: 'ratings', icon: Database },
  { key: 'matches', icon: GitCompare },
  { key: 'activity', icon: ActivityIcon },
  { key: 'reports', icon: FileSpreadsheet },
  { key: 'spendIntelligence', icon: DollarSign },
  { key: 'quality', icon: AlertTriangle },
  { key: 'exports', icon: Upload },
  { key: 'settings', icon: Settings },
];

const statusClass = {
  Setup: 'status status-setup',
  'Data Review': 'status status-review',
  Complete: 'status status-complete',
};

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

function ComingSoonPanel({ section }: { section: SectionKey }) {
  return (
    <div className="panel placeholder-panel">
      <h2>{SECTION_LABELS[section]} isn't built yet</h2>
      <p>This screen is on the roadmap but not implemented — see PRODUCT_ROADMAP.md for what's planned here.</p>
    </div>
  );
}

function Workspace({ currentUser, onSignOut }: { currentUser: User; onSignOut: () => void }) {
  const [activeSection, setActiveSection] = useState<SectionKey>('overview');
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
  const [isCalculating, setIsCalculating] = useState(false);
  const [calculateError, setCalculateError] = useState<string | null>(null);
  // Bumped after a successful calculate so ProjectDetailSection (which owns
  // its own SOV/version-history fetch, independent of this component) knows
  // to refetch — its own project.projectId dependency doesn't change just
  // because a new run was calculated for that same project.
  const [projectDataVersion, setProjectDataVersion] = useState(0);
  const [brands, setBrands] = useState<Brand[]>([]);
  const [brandsLoading, setBrandsLoading] = useState(false);
  const [isUploadOpen, setIsUploadOpen] = useState(false);
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
      setProjectDataVersion((current) => current + 1);
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
      setProjectDataVersion((current) => current + 1);
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
      // So ProjectManagePanel's always-visible Uploads table (it stays
      // mounted now, not toggled open fresh each time) picks up this file
      // without the user having to navigate away and back.
      setProjectDataVersion((current) => current + 1);
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
            <h1>{activeSection === 'projectDetail' && activeProject ? activeProject.projectName : SECTION_LABELS[activeSection]}</h1>
            <p>
              {activeSection === 'projects'
                ? 'Create a project to start tracking GRPs and Share of Voice, or click one to open it.'
                : activeSection === 'projectDetail'
                  ? `${activeProject?.client || 'No client'} — upload media reports and calculate, or switch to Overview for the executive dashboard.`
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
            </div>
          )}
          {activeSection === 'projectDetail' && activeProject && (
            <div className="toolbar">
              <button
                type="button"
                className="icon-button"
                aria-label="Back to Projects"
                title="Back to Projects"
                onClick={() => setActiveSection('projects')}
              >
                <ArrowLeft size={18} aria-hidden />
              </button>
              <button
                type="button"
                className="icon-button"
                aria-label="Archive active project"
                title={`Archive ${activeProject.projectName}`}
                onClick={handleArchiveActiveProject}
              >
                <Archive size={18} aria-hidden />
              </button>
              <button
                type="button"
                className="secondary-button"
                disabled={isCalculating}
                title={`Calculate GRPs for ${activeProject.projectName}`}
                onClick={handleCalculate}
              >
                <BarChart3 size={18} aria-hidden />
                {isCalculating ? 'Calculating…' : 'Calculate'}
              </button>
              <button
                type="button"
                className="primary-button"
                title="Upload a brand report"
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

        {activeSection === 'overview' ? (
          <OverviewSection project={activeProject} />
        ) : activeSection === 'ratings' ? (
          <RatingsSection project={activeProject} />
        ) : activeSection === 'matches' ? (
          <MatchesSection project={activeProject} />
        ) : activeSection === 'activity' ? (
          <ActivitySection project={activeProject} />
        ) : activeSection === 'reports' ? (
          <ReportsSection project={activeProject} />
        ) : activeSection === 'spendIntelligence' ? (
          <SpendIntelligenceSection project={activeProject} />
        ) : activeSection === 'quality' ? (
          <QualitySection project={activeProject} />
        ) : activeSection === 'settings' ? (
          <SettingsSection currentUser={currentUser} />
        ) : activeSection === 'exports' ? (
          <ExportsSection project={activeProject} />
        ) : activeSection === 'projectDetail' ? (
          <>
            {[actionError, calculateError].filter(Boolean).map((message, index) => (
              <p className="inline-error" key={index}>{message}</p>
            ))}

            {!activeProject && (
              <div className="panel placeholder-panel">
                <h2>No project selected</h2>
                <p>Go back to Projects and click one to open its details.</p>
              </div>
            )}

            {activeProject && (
              <>
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
                      <option value="Cable TV">Cable TV</option>
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

                <ProjectDetailSection project={activeProject} currentUser={currentUser} refreshSignal={projectDataVersion} />

                <ProjectManagePanel
                  project={activeProject}
                  currentUser={currentUser}
                  onProjectUpdated={handleProjectUpdated}
                  onClose={() => setActiveSection('projects')}
                  refreshSignal={projectDataVersion}
                />
              </>
            )}
          </>
        ) : activeSection !== 'projects' ? (
          <ComingSoonPanel section={activeSection} />
        ) : (
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
                    onSelect={() => {
                      setActiveProjectId(project.projectId);
                      setActiveSection('projectDetail');
                    }}
                  />
                ))}
              </div>
            </div>
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
