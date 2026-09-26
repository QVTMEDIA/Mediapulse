import { useCallback, useEffect, useRef, useState, type FormEvent, type ReactNode } from 'react';
import { SlidersHorizontal, Upload } from 'lucide-react';
import { ApiError, deleteSoeUpload, getSoe, getSoeFilterOptions, listSoeUploads, uploadSoeFile } from '../api/client';
import type { SoeFilterOptions, SoeReport, SoeUpload } from '../api/contracts';
import { formatNumber } from './SpendIntelligenceSection';

const EMPTY_FILTER_OPTIONS: SoeFilterOptions = { mediums: [], stations: [], regions: [], states: [], days: [] };
const EMPTY_REPORT: SoeReport = { totalSpend: 0, brands: [] };

// This section's own file/filter picks used to live only in React state, so
// switching to any other tab and back unmounted the component and reset
// everything -- reported directly ("everything seem to refresh once user
// leaves the page"). sessionStorage survives that unmount/remount (and a
// page reload) while still clearing itself when the tab actually closes, so
// a stale pick from days ago doesn't resurface in an unrelated session.
const SOE_EXPLORER_STATE_KEY = 'mediapulse.soeExplorer.state';

type PersistedSoeExplorerState = {
  selectedUploadId: string;
  mediums: string[];
  stations: string[];
  regions: string[];
  states: string[];
  days: string[];
  dateFrom: string;
  dateTo: string;
};

function loadPersistedSoeExplorerState(): PersistedSoeExplorerState | null {
  try {
    const raw = sessionStorage.getItem(SOE_EXPLORER_STATE_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw);
    if (typeof parsed !== 'object' || parsed === null) return null;
    const asStringArray = (value: unknown) => (Array.isArray(value) ? value.filter((entry) => typeof entry === 'string') : []);
    return {
      selectedUploadId: typeof parsed.selectedUploadId === 'string' ? parsed.selectedUploadId : '',
      mediums: asStringArray(parsed.mediums),
      stations: asStringArray(parsed.stations),
      regions: asStringArray(parsed.regions),
      states: asStringArray(parsed.states),
      days: asStringArray(parsed.days),
      dateFrom: typeof parsed.dateFrom === 'string' ? parsed.dateFrom : '',
      dateTo: typeof parsed.dateTo === 'string' ? parsed.dateTo : '',
    };
  } catch {
    // Corrupt JSON, or sessionStorage unavailable (private-browsing/storage
    // restrictions) -- fall back to the ordinary empty-state behavior.
    return null;
  }
}

function toggleValue(list: string[], value: string): string[] {
  return list.includes(value) ? list.filter((entry) => entry !== value) : [...list, value];
}

// A fixed regional preset requested directly ("Dairy Location"), not
// derived from any uploaded file -- so matching against whatever State
// values a file actually has has to be case-insensitive and tolerate the
// two real-world spelling variants for these particular states ("Cross
// River" vs "Cross Rivers", and "Abuja" vs "FCT"/"FCT Abuja") rather than
// requiring an exact string match.
const DAIRY_LOCATION_STATES = [
  'Lagos', 'Abia', 'Bauchi', 'Enugu', 'Kwara', 'Cross Rivers', 'Ekiti', 'Borno',
  'Sokoto', 'Rivers', 'Plateau', 'Oyo', 'Kano', 'Kaduna', 'Edo', 'Anambra',
  'Abuja', 'Niger',
];

const DAIRY_LOCATION_ALIASES: Record<string, string[]> = {
  'cross rivers': ['cross river', 'cross rivers'],
  abuja: ['abuja', 'fct', 'fct abuja'],
};

function normalizeStateName(value: string): string {
  return value.trim().toLowerCase().replace(/\s+/g, ' ');
}

function isDairyLocationState(option: string): boolean {
  const normalizedOption = normalizeStateName(option);
  return DAIRY_LOCATION_STATES.some((target) => {
    const normalizedTarget = normalizeStateName(target);
    const aliases = DAIRY_LOCATION_ALIASES[normalizedTarget] ?? [normalizedTarget];
    return aliases.includes(normalizedOption);
  });
}

function FilterGroup({
  label,
  options,
  selected,
  onToggle,
  headerExtra,
}: {
  label: string;
  options: string[];
  selected: string[];
  onToggle: (value: string) => void;
  headerExtra?: ReactNode;
}) {
  if (options.length === 0) return null;
  return (
    <div className="soe-filter-group">
      <h3>
        {label}
        {selected.length > 0 && <span className="soe-filter-count">{selected.length}</span>}
      </h3>
      {headerExtra}
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

// SOE Explorer's data is entirely its own -- never attached to any
// project, brand, or the Matching Engine. There's nothing to pick before
// uploading or browsing: the upload form and the file list are both
// visible immediately, and every file uploaded here (soe_uploads/
// soe_activity, see services/api/app/repositories/soe.py) stays that way
// permanently, not just excluded from matching while still attached to a
// project the way an earlier version of this feature worked.
export default function SoeExplorerSection() {
  const [initialPersisted] = useState(() => loadPersistedSoeExplorerState());

  const [uploads, setUploads] = useState<SoeUpload[]>([]);
  const [uploadsLoading, setUploadsLoading] = useState(false);
  const [uploadsError, setUploadsError] = useState<string | null>(null);
  const [selectedUploadId, setSelectedUploadId] = useState(initialPersisted?.selectedUploadId ?? '');

  const [filterOptions, setFilterOptions] = useState<SoeFilterOptions>(EMPTY_FILTER_OPTIONS);
  const [optionsLoading, setOptionsLoading] = useState(false);
  const [optionsError, setOptionsError] = useState<string | null>(null);

  const [mediums, setMediums] = useState<string[]>(initialPersisted?.mediums ?? []);
  const [stations, setStations] = useState<string[]>(initialPersisted?.stations ?? []);
  const [regions, setRegions] = useState<string[]>(initialPersisted?.regions ?? []);
  const [states, setStates] = useState<string[]>(initialPersisted?.states ?? []);
  const [days, setDays] = useState<string[]>(initialPersisted?.days ?? []);
  const [dateFrom, setDateFrom] = useState(initialPersisted?.dateFrom ?? '');
  const [dateTo, setDateTo] = useState(initialPersisted?.dateTo ?? '');

  const [report, setReport] = useState<SoeReport>(EMPTY_REPORT);
  const [reportLoading, setReportLoading] = useState(false);
  const [reportError, setReportError] = useState<string | null>(null);

  const [uploadFile, setUploadFile] = useState<File | null>(null);
  const [uploadDefaultMedium, setUploadDefaultMedium] = useState('TV');
  const [isUploading, setIsUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [uploadSuccess, setUploadSuccess] = useState<string | null>(null);
  const [fileInputKey, setFileInputKey] = useState(0);

  const [deletingUploadId, setDeletingUploadId] = useState<string | null>(null);
  const [deleteError, setDeleteError] = useState<string | null>(null);

  const loadUploads = useCallback(() => {
    setUploadsLoading(true);
    setUploadsError(null);
    return listSoeUploads()
      .then(setUploads)
      .catch((error) => setUploadsError(error instanceof ApiError ? error.message : 'Could not load uploads.'))
      .finally(() => setUploadsLoading(false));
  }, []);

  useEffect(() => {
    void loadUploads();
  }, [loadUploads]);

  const loadFilterOptions = useCallback((uploadId: string) => {
    setOptionsLoading(true);
    setOptionsError(null);
    return getSoeFilterOptions(uploadId)
      .then(setFilterOptions)
      .catch((error) => setOptionsError(error instanceof ApiError ? error.message : 'Could not load filters.'))
      .finally(() => setOptionsLoading(false));
  }, []);

  // Only an actual change of the uploaded file should clear the filters --
  // not this effect's unavoidable first run on mount, where selectedUploadId
  // may already be a file restored from sessionStorage (see
  // loadPersistedSoeExplorerState above) whose filters were restored right
  // alongside it. Comparing against the previous id (rather than a "have I
  // run yet" flag) makes this correct even under StrictMode's dev-only
  // double-invocation of effects, which would otherwise see a one-shot flag
  // already flipped on its second call and wipe the just-restored filters.
  const previousUploadIdRef = useRef(selectedUploadId);

  useEffect(() => {
    const uploadChanged = previousUploadIdRef.current !== selectedUploadId;
    previousUploadIdRef.current = selectedUploadId;
    if (uploadChanged) {
      setMediums([]);
      setStations([]);
      setRegions([]);
      setStates([]);
      setDays([]);
      setDateFrom('');
      setDateTo('');
    }
    if (!selectedUploadId) {
      setFilterOptions(EMPTY_FILTER_OPTIONS);
      setReport(EMPTY_REPORT);
      return;
    }
    void loadFilterOptions(selectedUploadId);
  }, [selectedUploadId, loadFilterOptions]);

  useEffect(() => {
    const toPersist: PersistedSoeExplorerState = { selectedUploadId, mediums, stations, regions, states, days, dateFrom, dateTo };
    try {
      sessionStorage.setItem(SOE_EXPLORER_STATE_KEY, JSON.stringify(toPersist));
    } catch {
      // sessionStorage can throw under storage restrictions (private
      // browsing, quota) -- losing persistence there is a harmless degrade.
    }
  }, [selectedUploadId, mediums, stations, regions, states, days, dateFrom, dateTo]);

  const refreshReport = useCallback(() => {
    if (!selectedUploadId) return;
    setReportLoading(true);
    setReportError(null);
    getSoe({
      uploadId: selectedUploadId,
      medium: mediums,
      station: stations,
      region: regions,
      state: states,
      day: days,
      dateFrom: dateFrom || null,
      dateTo: dateTo || null,
    })
      .then(setReport)
      .catch((error) => setReportError(error instanceof ApiError ? error.message : 'Could not load Share of Expenditure.'))
      .finally(() => setReportLoading(false));
  }, [selectedUploadId, mediums, stations, regions, states, days, dateFrom, dateTo]);

  useEffect(() => {
    void refreshReport();
  }, [refreshReport]);

  async function handleUpload(event: FormEvent) {
    event.preventDefault();
    if (!uploadFile) {
      setUploadError('Choose a file first.');
      return;
    }
    setIsUploading(true);
    setUploadError(null);
    setUploadSuccess(null);
    try {
      const result = await uploadSoeFile({ defaultMedium: uploadDefaultMedium, file: uploadFile });
      setUploadSuccess(
        `Uploaded ${result.fileName}: ${result.mappedRows} row${result.mappedRows === 1 ? '' : 's'} mapped` +
          (result.issueRows ? `, ${result.issueRows} skipped with issues.` : '.'),
      );
      setUploadFile(null);
      setFileInputKey((key) => key + 1);
      await loadUploads();
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

  async function handleDeleteUpload(uploadId: string) {
    setDeletingUploadId(uploadId);
    setDeleteError(null);
    try {
      await deleteSoeUpload(uploadId);
      if (selectedUploadId === uploadId) setSelectedUploadId('');
      await loadUploads();
    } catch (error) {
      setDeleteError(error instanceof ApiError ? error.message : 'Could not delete this upload.');
    } finally {
      setDeletingUploadId(null);
    }
  }

  const hasActiveFilters =
    mediums.length > 0 || stations.length > 0 || regions.length > 0 || states.length > 0 || days.length > 0 ||
    !!dateFrom || !!dateTo;

  function clearFilters() {
    setMediums([]);
    setStations([]);
    setRegions([]);
    setStates([]);
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
            <p>.xlsx, .xls, or .csv, multiple brands read from a Brand column — never attached to a project</p>
          </div>
          <Upload size={20} aria-hidden />
        </div>
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
          <button type="submit" className="secondary-button" disabled={isUploading || !uploadFile}>
            {isUploading ? 'Uploading…' : 'Upload'}
          </button>
        </div>
        {uploadError && <p className="inline-error">{uploadError}</p>}
        {uploadSuccess && <p className="inline-success">{uploadSuccess}</p>}
      </form>

      <div className="panel">
        <div className="panel-header">
          <div>
            <h2>Choose an uploaded file</h2>
            <p>{uploadsLoading ? 'Loading…' : `${uploads.length} file${uploads.length === 1 ? '' : 's'} uploaded`}</p>
          </div>
        </div>
        {uploadsError && <p className="inline-error">{uploadsError}</p>}
        {deleteError && <p className="inline-error">{deleteError}</p>}
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
                    {upload.fileName} — {upload.mappedRows} row{upload.mappedRows === 1 ? '' : 's'} — {upload.uploadedAt}
                  </option>
                ))}
              </select>
            </label>
            {selectedUploadId && (
              <button
                type="button"
                className="secondary-button"
                disabled={deletingUploadId === selectedUploadId}
                onClick={() => void handleDeleteUpload(selectedUploadId)}
              >
                {deletingUploadId === selectedUploadId ? 'Deleting…' : 'Delete this file'}
              </button>
            )}
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
                label="State"
                options={filterOptions.states}
                selected={states}
                onToggle={(value) => setStates((current) => toggleValue(current, value))}
                headerExtra={
                  <button
                    type="button"
                    className="soe-preset-button"
                    onClick={() => setStates(filterOptions.states.filter(isDairyLocationState))}
                  >
                    Dairy Location
                  </button>
                }
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
                  <div className="brand-row" key={brand.brand}>
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
