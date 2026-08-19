import {
  AlertTriangle,
  Archive,
  BarChart3,
  Database,
  FileSpreadsheet,
  FolderOpen,
  Gauge,
  Search,
  Settings,
  Upload,
} from 'lucide-react';
import { sampleWorkspace, type BrandShare, type Project, type RatingsDataset } from './api/contracts';

const navItems = [
  { label: 'Projects', icon: FolderOpen, active: true },
  { label: 'Ratings', icon: Database, active: false },
  { label: 'Reports', icon: FileSpreadsheet, active: false },
  { label: 'Quality', icon: AlertTriangle, active: false },
  { label: 'Exports', icon: Upload, active: false },
  { label: 'Settings', icon: Settings, active: false },
];

const statusClass = {
  Setup: 'status status-setup',
  'Data Review': 'status status-review',
  Complete: 'status status-complete',
};

function formatNumber(value: number) {
  return new Intl.NumberFormat('en-US', { maximumFractionDigits: 1 }).format(value);
}

function ProjectRow({ project }: { project: Project }) {
  return (
    <article className="project-row">
      <div className="project-main">
        <div>
          <h3>{project.projectName}</h3>
          <p>
            {project.client} | {project.category} | {project.market}
          </p>
        </div>
        <span className={statusClass[project.status]}>{project.status}</span>
      </div>
      <dl className="project-meta">
        <div>
          <dt>Owner</dt>
          <dd>{project.projectOwner}</dd>
        </div>
        <div>
          <dt>Period</dt>
          <dd>
            {project.startDate} to {project.endDate}
          </dd>
        </div>
        <div>
          <dt>Audience</dt>
          <dd>{project.targetAudience}</dd>
        </div>
        <div>
          <dt>Media</dt>
          <dd>{project.mediaTypes.join(', ')}</dd>
        </div>
      </dl>
    </article>
  );
}

function RatingsDatasetRow({ dataset }: { dataset: RatingsDataset }) {
  return (
    <div className="dataset-row">
      <div>
        <strong>{dataset.provider}</strong>
        <span>
          {dataset.period} | {dataset.audience}
        </span>
      </div>
      <div className="dataset-stat">
        <strong>{dataset.rows}</strong>
        <span>rows</span>
      </div>
      <div className="dataset-stat">
        <strong>{dataset.invalidRows + dataset.duplicateKeys}</strong>
        <span>issues</span>
      </div>
      <span className={dataset.status === 'Ready' ? 'status status-complete' : 'status status-review'}>
        {dataset.status}
      </span>
    </div>
  );
}

function BrandShareRow({ share, maxGrp }: { share: BrandShare; maxGrp: number }) {
  const width = maxGrp ? `${Math.max((share.totalGrps / maxGrp) * 100, 3)}%` : '3%';
  return (
    <div className="brand-row">
      <div className="brand-line">
        <span>{share.brand}</span>
        <strong>{share.sov.toFixed(1)}%</strong>
      </div>
      <div className="bar-track" aria-label={`${share.brand} GRP contribution`}>
        <div className="bar-fill" style={{ width }} />
      </div>
      <small>
        {share.spots} spots | {share.totalGrps.toFixed(1)} GRPs
      </small>
    </div>
  );
}

function App() {
  const workspace = sampleWorkspace;
  const activeProject = workspace.projects[0];
  const maxGrp = Math.max(...workspace.brandShares.map((share) => share.totalGrps));
  const reviewCount = workspace.validationIssues.filter((issue) => issue.severity !== 'info').length;

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
            return (
              <button className={item.active ? 'nav-item active' : 'nav-item'} key={item.label}>
                <Icon size={18} aria-hidden />
                <span>{item.label}</span>
              </button>
            );
          })}
        </nav>

        <div className="sidebar-note">
          <span>Active project</span>
          <strong>{activeProject.projectName}</strong>
          <small>{activeProject.updatedAt}</small>
        </div>
      </aside>

      <main className="workspace">
        <header className="topbar">
          <div>
            <h1>Project Workspace</h1>
            <p>{activeProject.category} performance, ratings coverage, and GRP quality.</p>
          </div>
          <div className="toolbar">
            <label className="search-box">
              <Search size={17} aria-hidden />
              <input type="search" placeholder="Search projects, brands, stations" />
            </label>
            <button className="icon-button" aria-label="Archive project">
              <Archive size={18} aria-hidden />
            </button>
            <button className="primary-button">
              <Upload size={18} aria-hidden />
              Upload
            </button>
          </div>
        </header>

        <section className="metric-grid" aria-label="Workspace metrics">
          <div className="metric-panel">
            <span>Total GRPs</span>
            <strong>{activeProject ? formatNumber(workspace.latestRun.totalGrps) : '0'}</strong>
            <small>{workspace.latestRun.generatedAt}</small>
          </div>
          <div className="metric-panel">
            <span>Matched Rows</span>
            <strong>{workspace.latestRun.matchedRows}</strong>
            <small>{workspace.latestRun.unmatchedRows} unmatched</small>
          </div>
          <div className="metric-panel">
            <span>Brands</span>
            <strong>{workspace.latestRun.totalBrands}</strong>
            <small>{workspace.latestRun.totalSpots} total spots</small>
          </div>
          <div className="metric-panel warning-panel">
            <span>Review Items</span>
            <strong>{reviewCount}</strong>
            <small>validation warnings</small>
          </div>
        </section>

        <section className="content-grid">
          <div className="panel project-panel">
            <div className="panel-header">
              <div>
                <h2>Projects</h2>
                <p>{workspace.projects.length} workspaces</p>
              </div>
              <button className="secondary-button">
                <FolderOpen size={17} aria-hidden />
                New
              </button>
            </div>
            <div className="project-list">
              {workspace.projects.map((project) => (
                <ProjectRow project={project} key={project.projectId} />
              ))}
            </div>
          </div>

          <div className="panel">
            <div className="panel-header">
              <div>
                <h2>Brand SOV</h2>
                <p>Latest run</p>
              </div>
              <BarChart3 size={20} aria-hidden />
            </div>
            <div className="brand-list">
              {workspace.brandShares.map((share) => (
                <BrandShareRow share={share} maxGrp={maxGrp} key={share.brand} />
              ))}
            </div>
          </div>
        </section>

        <section className="content-grid bottom-grid">
          <div className="panel">
            <div className="panel-header">
              <div>
                <h2>Ratings Library</h2>
                <p>Reusable datasets</p>
              </div>
              <Database size={20} aria-hidden />
            </div>
            <div className="dataset-list">
              {workspace.ratingsDatasets.map((dataset) => (
                <RatingsDatasetRow dataset={dataset} key={dataset.ratingsDatasetId} />
              ))}
            </div>
          </div>

          <div className="panel">
            <div className="panel-header">
              <div>
                <h2>Data Quality</h2>
                <p>Open validation signals</p>
              </div>
              <AlertTriangle size={20} aria-hidden />
            </div>
            <div className="issue-list">
              {workspace.validationIssues.map((issue) => (
                <div className="issue-row" key={issue.issueId}>
                  <span className="issue-dot" />
                  <div>
                    <strong>{issue.area}</strong>
                    <p>{issue.message}</p>
                  </div>
                  <small>{issue.rows} rows</small>
                </div>
              ))}
            </div>
          </div>
        </section>
      </main>
    </div>
  );
}

export default App;
