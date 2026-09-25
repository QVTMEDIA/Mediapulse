import { useCallback, useEffect, useMemo, useState, type FormEvent } from 'react';
import { SlidersHorizontal, Upload } from 'lucide-react';
import { ApiError, getSoe, getSoeFilterOptions, listUploads, uploadMediaReport } from '../api/client';
import type { Project, SoeFilterOptions, SoeReport, UploadBatch } from '../api/contracts';
import { formatNumber } from './SpendIntelligenceSection';

const EMPTY_FILTER_OPTIONS: SoeFilterOptions = { mediums: [], stations: [], regions: [], days: [] };
const EMPTY_REPORT: SoeReport = { totalSpend: 0, brands: [] };

function toggleValue(list: string[], value: string): string[] {
  return list.includes(value) ? list.filter((entry) => entry !== value) : [...list, value];
}

function FilterGroup({
  label,
  options,
  selected,
  onToggle,
}: {
  label: string;
  options: string[];
  selected: string[];
  onToggle: (value: string) => void;
}) {
  if (options.length === 0) return null;
  return (
    <div className="soe-filter-group">
      <h3>
        {label}
        {selected.length > 0 && <span className="soe-filter-count">{selected.length}</span>}
      </h3>
      <div className="soe-filter-options">
        {options.map((option) => (
          <label className="checkbox-field" key={option}>
            <input type="checkbox" checked={selected.includes(option)} onChange={() => onToggle(option)} />
            {option}
          </label>
        ))}
      </div>
    </div>
  );
}

// Analyzed one uploaded file at a time on purpose -- SOE Explorer is meant
// for "what does this specific file say", not pooling every upload a
// project has ever had. But there's no project-picking gate before you can
// upload or browse what's already there: the upload form and the file list
// both work across every project up front. A file's own project only
// matters once it's selected, to route the filter/report queries to the
// right /api/projects/{projectId}/soe endpoint underneath. The upload
// form's own Project field starts unselected and stays that way until the
// user actually picks one -- no default, not even the first project in the
// list, since silently attaching a file to the wrong project is worse than
// making someone pick. Every upload here also goes up with soeOnly: true,
// so it never reaches the Matching Engine or a calculated GRP run -- this
// tab is for live spend analysis of one file, not for feeding a project's
// real ratings-matched numbers.
export default function SoeExplorerSection({ projects }: { projects: Project[] }) {
  const [uploads, setUploads] = useState<UploadBatch[]>([]);
  const [uploadsLoading, setUploadsLoading] = useState(false);
  const [uploadsError, setUploadsError] = useState<string | null>(null);
  const [selectedUploadId, setSelectedUploadId] = useState('');

  const [filterOptions, setFilterOptions] = useState<SoeFilterOptions>(EMPTY_FILTER_OPTIONS);
  const [optionsLoading, setOptionsLoading] = useState(false);
  const [optionsError, setOptionsError] = useState<string | null>(null);

  const [mediums, setMediums] = useState<string[]>([]);
  const [stations, setStations] = useState<string[]>([]);
  const [regions, setRegions] = useState<string[]>([]);
  const [days, setDays] = useState<string[]>([]);
  const [dateFrom, setDateFrom] = useState('');
  const [dateTo, setDateTo] = useState('');

  const [report, setReport] = useState<SoeReport>(EMPTY_REPORT);
  const [reportLoading, setReportLoading] = useState(false);
  const [reportError, setReportError] = useState<string | null>(null);

  const [uploadTargetProjectId, setUploadTargetProjectId] = useState('');
  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [uploadDefaultMedium, setUploadDefaultMedium] = useState('TV');
  const [isUploading, setIsUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [uploadSuccess, setUploadSuccess] = useState<string | null>(null);
  const [fileInputKey, setFileInputKey] = useState(0);

  const loadAllUploads = useCallback((projectList: Project[]) => {
    if (projectList.length === 0) {
      setUploads([]);
      return Promise.resolve();
    }
    setUploadsLoading(true);
    setUploadsError(null);
    return Promise.all(projectList.map((project) => listUploads(project.projectId)))
      .then((byProject) => {
        const merged = byProject.flat().sort((a, b) => b.uploadedAt.localeCompare(a.uploadedAt));
        setUploads(merged);
      })
      .catch((error) => setUploadsError(error instanceof ApiError ? error.message : 'Could not load uploads.'))
      .finally(() => setUploadsLoading(false));
  }, []);

  // Every project's uploads are fetched up front so the file picker below
  // always reflects everything available across the whole account.
  useEffect(() => {
    void loadAllUploads(projects);
  }, [projects, loadAllUploads]);

  const selectedUpload = uploads.find((upload) => upload.uploadId === selectedUploadId) ?? null;
  const selectedProjectId = selectedUpload?.projectId ?? '';

  const projectNameById = useMemo(() => {
    const map = new Map<string, string>();
    projects.forEach((project) => map.set(project.projectId, project.projectName));
    return map;
  }, [projects]);

  const loadFilterOptions = useCallback((projectId: string, uploadId: string) => {
    setOptionsLoading(true);
    setOptionsError(null);
    return getSoeFilterOptions(projectId, uploadId)
      .then(setFilterOptions)
      .catch((error) => setOptionsError(error instanceof ApiError ? error.message : 'Could not load filters.'))
      .finally(() => setOptionsLoading(false));
  }, []);

  useEffect(() => {
    setMediums([]);
    setStations([]);
    setRegions([]);
    setDays([]);
    setDateFrom('');
    setDateTo('');
    if (!selectedProjectId || !selectedUploadId) {
      setFilterOptions(EMPTY_FILTER_OPTIONS);
      setReport(EMPTY_REPORT);
      return;
    }
    void loadFilterOptions(selectedProjectId, selectedUploadId);
  }, [selectedProjectId, selectedUploadId, loadFilterOptions]);

  const refreshReport = useCallback(() => {
    if (!selectedProjectId || !selectedUploadId) return;
    setReportLoading(true);
    setReportError(null);
    getSoe(selectedProjectId, {
      uploadId: selectedUploadId,
      medium: mediums,
      station: stations,
      region: regions,
      day: days,
      dateFrom: dateFrom || null,
      dateTo: dateTo || null,
    })
      .then(setReport)
      .catch((error) => setReportError(error instanceof ApiError ? error.message : 'Could not load Share of Expenditure.'))
      .finally(() => setReportLoading(false));
  }, [selectedProjectId, selectedUploadId, mediums, stations, regions, days, dateFrom, dateTo]);

  useEffect(() => {
    void refreshReport();
  }, [refreshReport]);

  async function handleUpload(event: FormEvent) {
    event.preventDefault();
    if (!uploadTargetProjectId) {
      setUploadError('Choose a project first.');
      return;
    }
    if (!uploadFile) {
      setUploadError('Choose a file first.');
      return;
    }
    setIsUploading(true);
    setUploadError(null);
    setUploadSuccess(null);
    try {
      const result = await uploadMediaReport(uploadTargetProjectId, {
        kind: 'composite_report',
        defaultMedium: uploadDefaultMedium,
        file: uploadFile,
        // Never feeds the Matching Engine or a calculated GRP run -- this
        // upload exists purely for this file's own live SOE analysis.
        soeOnly: true,
      });
      setUploadSuccess(
        `Uploaded ${result.fileName}: ${result.mappedRows} row${result.mappedRows === 1 ? '' : 's'} mapped` +
          (result.issueRows ? `, ${result.issueRows} skipped with issues.` : '.'),
      );
      setUploadFile(null);
      setFileInputKey((key) => key + 1);
      await loadAllUploads(projects);
      // The file just uploaded is almost always the one someone wants to
      // look at next -- select it automatically rather than leaving them to
      // find it in the dropdown themselves.
      setSelectedUploadId(result.uploadId);
    } catch (error) {
      setUploadError(error instanceof ApiError ? error.message : 'Could not upload the file.');
    } finally {
      setIsUploading(false);
    }
  }

  const hasActiveFilters =
    mediums.length > 0 || stations.length > 0 || regions.length > 0 || days.length > 0 || !!dateFrom || !!dateTo;

  function clearFilters() {
    setMediums([]);
    setStations([]);
    setRegions([]);
    setDays([]);
    setDateFrom('');
    setDateTo('');
  }

  const hasAnyFilterableData = filterOptions.mediums.length > 0 || filterOptions.stations.length > 0;
  const maxSpend = Math.max(1, ...report.brands.map((brand) => brand.spend));

  return (
    <>
      <form className="panel upload-form" onSubmit={handleUpload}>
        <div className="panel-header">
          <div>
            <h2>Upload spend data</h2>
            <p>.xlsx, .xls, or .csv, multiple brands read from a Brand column</p>
          </div>
          <Upload size={20} aria-hidden />
        </div>
        {projects.length === 0 ? (
          <p className="empty-state">Create a project first — uploads need somewhere to live.</p>
        ) : (
          <div className="upload-form-row">
            <label>
              File
              <input
                key={fileInputKey}
                type="file"
                accept=".xlsx,.xls,.csv"
                onChange={(event) => setUploadFile(event.target.files?.[0] ?? null)}
              />
            </label>
            <label>
              Default medium (used if the file has no Medium column)
              <select value={uploadDefaultMedium} onChange={(event) => setUploadDefaultMedium(event.target.value)}>
                <option value="TV">TV</option>
                <option value="Radio">Radio</option>
                <option value="Cable TV">Cable TV</option>
              </select>
            </label>
            <label>
              Project
              <select value={uploadTargetProjectId} onChange={(event) => setUploadTargetProjectId(event.target.value)}>
                <option value="">Select a project…</option>
                {projects.map((project) => (
                  <option value={project.projectId} key={project.projectId}>
                    {project.projectName}
                  </option>
                ))}
              </select>
            </label>
            <button
              type="submit"
              className="secondary-button"
              disabled={isUploading || !uploadFile || !uploadTargetProjectId}
              title={!uploadTargetProjectId ? 'Choose a project above first' : undefined}
            >
              {isUploading ? 'Uploading…' : 'Upload'}
            </button>
          </div>
        )}
        {!uploadTargetProjectId && uploadFile && (
          <p className="empty-state">Choose a project above to enable Upload.</p>
        )}
        {uploadError && <p className="inline-error">{uploadError}</p>}
        {uploadSuccess && <p className="inline-success">{uploadSuccess}</p>}
      </form>

      <div className="panel">
        <div className="panel-header">
          <div>
            <h2>Choose an uploaded file</h2>
            <p>
              {uploadsLoading
                ? 'Loading…'
                : `${uploads.length} file${uploads.length === 1 ? '' : 's'} uploaded across every project`}
            </p>
          </div>
        </div>
        {uploadsError && <p className="inline-error">{uploadsError}</p>}
        {!uploadsLoading && !uploadsError && uploads.length === 0 && (
          <p className="empty-state">No files uploaded yet — use the form above to add one.</p>
        )}
        {uploads.length > 0 && (
          <div className="upload-form-row">
            <label>
              Uploaded file
              <select value={selectedUploadId} onChange={(event) => setSelectedUploadId(event.target.value)}>
                <option value="">Select a file…</option>
                {uploads.map((upload) => (
                  <option value={upload.uploadId} key={upload.uploadId}>
                    {upload.fileName} — {projectNameById.get(upload.projectId) ?? 'Unknown project'} —{' '}
                    {upload.mappedRows} row{upload.mappedRows === 1 ? '' : 's'} — {upload.uploadedAt}
                  </option>
                ))}
              </select>
            </label>
          </div>
        )}
      </div>

      {optionsError && <p className="inline-error">{optionsError}</p>}

      {selectedUploadId && !optionsLoading && !hasAnyFilterableData && !optionsError && (
        <div className="panel placeholder-panel">
          <h2>No spend data in this file</h2>
          <p>This upload has no rows with a Cost or Rate column mapped.</p>
        </div>
      )}

      {selectedUploadId && hasAnyFilterableData && (
        <>
          <div className="panel">
            <div className="panel-header">
              <div>
                <h2>Filters</h2>
                <p>Narrow Share of Expenditure by whatever this file actually contains — every checkbox reflects real data, not a fixed list.</p>
              </div>
              <SlidersHorizontal size={20} aria-hidden />
            </div>
            <div className="soe-filters">
              <FilterGroup
                label="Medium"
                options={filterOptions.mediums}
                selected={mediums}
                onToggle={(value) => setMediums((current) => toggleValue(current, value))}
              />
              <FilterGroup
                label="Station"
                options={filterOptions.stations}
                selected={stations}
                onToggle={(value) => setStations((current) => toggleValue(current, value))}
              />
              <FilterGroup
                label="Region"
                options={filterOptions.regions}
                selected={regions}
                onToggle={(value) => setRegions((current) => toggleValue(current, value))}
              />
              <FilterGroup
                label="Day"
                options={filterOptions.days}
                selected={days}
                onToggle={(value) => setDays((current) => toggleValue(current, value))}
              />
              <div className="soe-filter-group">
                <h3>Date range</h3>
                <div className="soe-date-inputs">
                  <label>
                    From
                    <input type="date" value={dateFrom} onChange={(event) => setDateFrom(event.target.value)} />
                  </label>
                  <label>
                    To
                    <input type="date" value={dateTo} onChange={(event) => setDateTo(event.target.value)} />
                  </label>
                </div>
              </div>
            </div>
            {hasActiveFilters && (
              <button type="button" className="secondary-button soe-clear-button" onClick={clearFilters}>
                Clear filters
              </button>
            )}
          </div>

          <div className="panel">
            <div className="panel-header">
              <div>
                <h2>Share of Expenditure</h2>
                <p>
                  {reportLoading
                    ? 'Loading…'
                    : hasActiveFilters
                      ? `Filtered — ${formatNumber(report.totalSpend)} total spend`
                      : `${formatNumber(report.totalSpend)} total spend in this file`}
                </p>
              </div>
            </div>
            {reportError && <p className="inline-error">{reportError}</p>}
            {!reportLoading && !reportError && report.brands.length === 0 && (
              <p className="empty-state">No spend matches these filters.</p>
            )}
            {report.brands.length > 0 && (
              <div className="brand-list">
                {report.brands.map((brand) => (
                  <div className="brand-row" key={brand.brandId}>
                    <div className="brand-line">
                      <span>{brand.brand}</span>
                      <strong className="soe-value">{brand.soe.toFixed(1)}% SOE</strong>
                    </div>
                    <div className="bar-track" aria-label={`${brand.brand} spend contribution`}>
                      <div className="bar-fill" style={{ width: `${Math.max((brand.spend / maxSpend) * 100, 3)}%` }} />
                    </div>
                    <small>
                      {formatNumber(brand.spend)} spend · {brand.spots} spot{brand.spots === 1 ? '' : 's'}
                    </small>
                  </div>
                ))}
              </div>
            )}
          </div>
        </>
      )}
    </>
  );
}
