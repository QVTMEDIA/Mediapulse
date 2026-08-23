import { Fragment, useCallback, useEffect, useMemo, useState, type FormEvent } from 'react';
import { AlertTriangle, Database } from 'lucide-react';
import {
  ApiError,
  attachRatingsDataset,
  listMappingTemplates,
  listProjectRatingsDatasets,
  listRatingRows,
  listRatingsLibrary,
  uploadRatingsFile,
} from '../api/client';
import type { Project, RatingRow, RatingsDataset, RatingsRowIssue } from '../api/contracts';

// Mirrors services/api/app/repositories/ratings.py's _row_is_invalid() and
// services/api/app/matching.py's make_match_key() (in turn grp_calculator.
// normalize_text/normalize_day) — client-side so a clicked row can explain
// itself immediately, without a round trip. This is display-only: the
// dataset summary's invalidRows/duplicateKeys counts (computed server-side
// at upload time) stay the source of truth for the badge numbers.
const DAY_MAP: Record<string, string> = {
  monday: 'MON', mon: 'MON',
  tuesday: 'TUE', tue: 'TUE', tues: 'TUE',
  wednesday: 'WED', wed: 'WED',
  thursday: 'THU', thu: 'THU', thur: 'THU', thurs: 'THU',
  friday: 'FRI', fri: 'FRI',
  saturday: 'SAT', sat: 'SAT',
  sunday: 'SUN', sun: 'SUN',
};

function normalizeText(value: string): string {
  return value.trim().replace(/\s+/g, ' ').toUpperCase();
}

function normalizeDay(value: string): string {
  const s = value.trim().toLowerCase();
  if (!s) return '';
  if (s in DAY_MAP) return DAY_MAP[s];
  const s3 = s.slice(0, 3);
  for (const [key, code] of Object.entries(DAY_MAP)) {
    if (key.slice(0, 3) === s3) return code;
  }
  return normalizeText(value).slice(0, 3);
}

function matchKey(row: RatingRow): string {
  const combinedProgramme = [row.programme, row.timeBand].map((part) => (part || '').trim()).filter(Boolean).join(' ');
  return [normalizeText(row.medium), normalizeText(row.station), normalizeDay(row.day), normalizeText(combinedProgramme)].join('|');
}

function rowIsInvalid(row: RatingRow): boolean {
  return !(row.medium.trim() && row.station.trim() && row.day.trim()) || row.rating === null;
}

interface RowIssue {
  label: string;
  detail: string;
}

function describeIssue(row: RatingRow, duplicateSiblings: RatingRow[]): RowIssue | null {
  const missingFields = [
    !row.medium.trim() && 'Medium',
    !row.station.trim() && 'Station',
    !row.day.trim() && 'Day',
  ].filter(Boolean) as string[];

  if (missingFields.length > 0 && row.rating === null) {
    return { label: 'Missing data', detail: `Missing ${missingFields.join(', ')} and Rating — this row can never be matched or calculated.` };
  }
  if (missingFields.length > 0) {
    return { label: 'Missing field', detail: `Missing ${missingFields.join(', ')} — the Matching Engine needs all three to build a match key.` };
  }
  if (row.rating === null) {
    return { label: 'No rating', detail: 'No Rating value for this row — it will never produce a GRP even if a spot matches it.' };
  }
  if (duplicateSiblings.length > 0) {
    const siblingDescriptions = duplicateSiblings
      .map((sibling) => `${sibling.station} · ${sibling.day} · ${sibling.programme || 'No programme'} (${sibling.rating ?? 'no rating'})`)
      .join('; ');
    return {
      label: 'Duplicate key',
      detail: `${duplicateSiblings.length + 1} rows share the same Medium/Station/Day/Programme key — whichever the app picks wins, the rest are ignored. Also matching: ${siblingDescriptions}.`,
    };
  }
  return null;
}

function RatingsDatasetRow({
  dataset,
  isActive,
  onSelect,
}: {
  dataset: RatingsDataset;
  isActive: boolean;
  onSelect: () => void;
}) {
  return (
    <div
      className={isActive ? 'dataset-row active' : 'dataset-row'}
      role="button"
      tabIndex={0}
      aria-pressed={isActive}
      onClick={onSelect}
      onKeyDown={(event) => {
        if (event.key === 'Enter' || event.key === ' ') {
          event.preventDefault();
          onSelect();
        }
      }}
    >
      <div>
        <strong>{dataset.provider || 'Untitled dataset'}</strong>
        <span>{[dataset.period, dataset.audience].filter(Boolean).join(' | ') || 'No period or audience set'}</span>
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

export default function RatingsSection({ project }: { project: Project | null }) {
  const [attached, setAttached] = useState<RatingsDataset[]>([]);
  const [library, setLibrary] = useState<RatingsDataset[]>([]);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);

  const [isUploadOpen, setIsUploadOpen] = useState(false);
  const [provider, setProvider] = useState('');
  const [period, setPeriod] = useState('');
  const [defaultMedium, setDefaultMedium] = useState('TV');
  const [sourceLabel, setSourceLabel] = useState('');
  const [saveAsTemplate, setSaveAsTemplate] = useState(false);
  const [knownSourceLabels, setKnownSourceLabels] = useState<string[]>([]);
  const [file, setFile] = useState<File | null>(null);
  const [fileInputKey, setFileInputKey] = useState(0);
  const [isUploading, setIsUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const [uploadSuccess, setUploadSuccess] = useState<string | null>(null);
  // Which specific rows this upload rejected, and why — never fetchable
  // again after this response, since a dropped row is never stored. Clears
  // on the next upload attempt so stale detail doesn't linger.
  const [uploadIssues, setUploadIssues] = useState<RatingsRowIssue[]>([]);
  const [uploadIssuesTotal, setUploadIssuesTotal] = useState(0);

  const [attachSelection, setAttachSelection] = useState('');
  const [isAttaching, setIsAttaching] = useState(false);
  const [attachError, setAttachError] = useState<string | null>(null);

  // The actual ratings data, not just the summary counts — selecting a
  // dataset loads and shows its rows in a table, defaulting to the first
  // attached dataset so the common one-dataset-per-project case shows real
  // data immediately, with no extra click needed.
  const [selectedDatasetId, setSelectedDatasetId] = useState('');
  const [datasetRows, setDatasetRows] = useState<RatingRow[]>([]);
  const [rowsLoading, setRowsLoading] = useState(false);
  const [rowsError, setRowsError] = useState<string | null>(null);
  const [expandedRowId, setExpandedRowId] = useState<string | null>(null);

  const refresh = useCallback(async (projectId: string) => {
    setLoading(true);
    setLoadError(null);
    try {
      const [attachedResult, libraryResult] = await Promise.all([
        listProjectRatingsDatasets(projectId),
        listRatingsLibrary(),
      ]);
      setAttached(attachedResult);
      setLibrary(libraryResult);
      setSelectedDatasetId((current) =>
        current && attachedResult.some((dataset) => dataset.ratingsDatasetId === current)
          ? current
          : (attachedResult[0]?.ratingsDatasetId ?? ''),
      );
    } catch (error) {
      setLoadError(error instanceof ApiError ? error.message : 'Could not load the Ratings Library.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (project) {
      void refresh(project.projectId);
    } else {
      setAttached([]);
      setLibrary([]);
      setSelectedDatasetId('');
    }
  }, [project, refresh]);

  useEffect(() => {
    if (!selectedDatasetId) {
      setDatasetRows([]);
      return;
    }
    setRowsLoading(true);
    setRowsError(null);
    setExpandedRowId(null);
    listRatingRows(selectedDatasetId)
      .then(setDatasetRows)
      .catch((error) => {
        setRowsError(error instanceof ApiError ? error.message : 'Could not load this dataset’s rows.');
        setDatasetRows([]);
      })
      .finally(() => setRowsLoading(false));
  }, [selectedDatasetId]);

  // Grouped by match key so each row can point to its duplicate siblings by
  // name, not just say "this is a duplicate" with no way to see the other
  // half of the collision.
  const duplicateGroups = useMemo(() => {
    const groups = new Map<string, RatingRow[]>();
    for (const row of datasetRows) {
      const key = matchKey(row);
      const group = groups.get(key) ?? [];
      group.push(row);
      groups.set(key, group);
    }
    return groups;
  }, [datasetRows]);

  const selectedDataset = attached.find((dataset) => dataset.ratingsDatasetId === selectedDatasetId) ?? null;
  const inspectableInvalidCount = datasetRows.filter(rowIsInvalid).length;
  // Some invalid rows never made it into datasetRows at all — grp_calculator's
  // own upload-time validation (missing match field, or a rating outside
  // 0-100) drops them before they're ever stored, so there's no row to click
  // into for those. The gap between the dataset's own invalidRows count and
  // what's actually inspectable here is exactly that dropped set.
  const droppedInvalidCount = selectedDataset ? Math.max(0, selectedDataset.invalidRows - inspectableInvalidCount) : 0;

  async function handleUpload(event: FormEvent) {
    event.preventDefault();
    if (!project || !file) return;
    setIsUploading(true);
    setUploadError(null);
    setUploadSuccess(null);
    setUploadIssues([]);
    setUploadIssuesTotal(0);
    try {
      const dataset = await uploadRatingsFile({
        provider,
        period,
        defaultMedium,
        file,
        sourceLabel: sourceLabel.trim() || undefined,
        saveAsTemplate,
      });
      await attachRatingsDataset(project.projectId, dataset.ratingsDatasetId);
      setUploadSuccess(
        `Uploaded ${dataset.provider || 'dataset'}: ${dataset.rows} row${dataset.rows === 1 ? '' : 's'}` +
          (dataset.invalidRows ? `, ${dataset.invalidRows} invalid.` : '.') +
          ' Attached to this project.',
      );
      setUploadIssues(dataset.issues ?? []);
      setUploadIssuesTotal(dataset.invalidRows);
      setFile(null);
      setFileInputKey((key) => key + 1);
      if (sourceLabel.trim()) {
        setKnownSourceLabels((current) => (current.includes(sourceLabel.trim()) ? current : [...current, sourceLabel.trim()]));
      }
      setSelectedDatasetId(dataset.ratingsDatasetId);
      await refresh(project.projectId);
    } catch (error) {
      setUploadError(error instanceof ApiError ? error.message : 'Could not upload the ratings file.');
    } finally {
      setIsUploading(false);
    }
  }

  async function handleAttachExisting() {
    if (!project || !attachSelection) return;
    setIsAttaching(true);
    setAttachError(null);
    try {
      await attachRatingsDataset(project.projectId, attachSelection);
      const attachedId = attachSelection;
      setAttachSelection('');
      setSelectedDatasetId(attachedId);
      await refresh(project.projectId);
    } catch (error) {
      setAttachError(error instanceof ApiError ? error.message : 'Could not attach that dataset.');
    } finally {
      setIsAttaching(false);
    }
  }

  const attachedIds = new Set(attached.map((dataset) => dataset.ratingsDatasetId));
  const attachableLibrary = library.filter((dataset) => !attachedIds.has(dataset.ratingsDatasetId));

  if (!project) {
    return (
      <div className="panel placeholder-panel">
        <h2>No project selected</h2>
        <p>Open or create a project to manage its ratings.</p>
      </div>
    );
  }

  return (
    <>
      <div className="panel">
        <div className="panel-header">
          <div>
            <h2>Ratings Library</h2>
            <p>{loading ? 'Loading…' : `${attached.length} dataset${attached.length === 1 ? '' : 's'} attached to ${project.projectName}`}</p>
          </div>
          <button
            type="button"
            className="secondary-button"
            onClick={() => {
              setIsUploadOpen((open) => !open);
              if (knownSourceLabels.length === 0) {
                void listMappingTemplates()
                  .then((templates) => setKnownSourceLabels(templates.map((template) => template.sourceLabel)))
                  .catch(() => {
                    // Autocomplete is a nicety — a failed fetch just leaves the datalist empty.
                  });
              }
            }}
          >
            <Database size={17} aria-hidden />
            Upload ratings
          </button>
        </div>

        {isUploadOpen && (
          <form className="upload-form" onSubmit={handleUpload}>
            <div className="upload-form-row">
              <label>
                Provider
                <input type="text" placeholder="e.g. Nielsen" value={provider} onChange={(event) => setProvider(event.target.value)} />
              </label>
              <label>
                Period
                <input type="text" placeholder="e.g. Q1 2026" value={period} onChange={(event) => setPeriod(event.target.value)} />
              </label>
              <label>
                Default medium (used if the file has no Medium column)
                <select value={defaultMedium} onChange={(event) => setDefaultMedium(event.target.value)}>
                  <option value="TV">TV</option>
                  <option value="Radio">Radio</option>
                  <option value="Cable TV">Cable TV</option>
                </select>
              </label>
            </div>
            <div className="upload-form-row">
              <label>
                Source label (optional)
                <input
                  type="text"
                  list="known-ratings-source-labels"
                  placeholder="e.g. Nielsen weekly export"
                  value={sourceLabel}
                  onChange={(event) => setSourceLabel(event.target.value)}
                />
                <datalist id="known-ratings-source-labels">
                  {knownSourceLabels.map((label) => (
                    <option value={label} key={label} />
                  ))}
                </datalist>
              </label>
              <label className="checkbox-field">
                <input
                  type="checkbox"
                  checked={saveAsTemplate}
                  onChange={(event) => setSaveAsTemplate(event.target.checked)}
                />
                Remember this column mapping for this source label
              </label>
            </div>
            <p className="field-hint">
              {knownSourceLabels.includes(sourceLabel.trim())
                ? 'A saved mapping exists for this label — it will be applied automatically.'
                : 'A new label saves the mapping this file actually uses, so later uploads from the same source map automatically.'}
            </p>
            <label>
              File (.xlsx, .xls, or .csv — Channel, Day, Programme, Rating columns)
              <input
                type="file"
                key={fileInputKey}
                accept=".xlsx,.xls,.csv"
                onChange={(event) => setFile(event.target.files?.[0] ?? null)}
              />
            </label>
            <div className="form-actions">
              <button type="submit" className="primary-button" disabled={isUploading || !file}>
                {isUploading ? 'Uploading…' : 'Upload & attach'}
              </button>
              <button type="button" className="secondary-button" onClick={() => setIsUploadOpen(false)}>
                Close
              </button>
            </div>
            {uploadError && <p className="inline-error">{uploadError}</p>}
            {uploadSuccess && <p className="empty-state">{uploadSuccess}</p>}
          </form>
        )}

        {uploadIssues.length > 0 && (
          <div className="panel warning-panel" style={{ marginTop: 12 }}>
            <div className="panel-header">
              <div>
                <h2>Rows rejected during upload</h2>
                <p>
                  These {uploadIssues.length === uploadIssuesTotal ? '' : `first ${uploadIssues.length} of `}
                  {uploadIssuesTotal} row{uploadIssuesTotal === 1 ? '' : 's'} never made it into the dataset — nothing to
                  click into later, so here's why each one failed.
                </p>
              </div>
              <AlertTriangle size={20} aria-hidden />
            </div>
            <div className="table-scroll">
              <table className="data-table">
                <thead>
                  <tr>
                    <th className="num">Row</th>
                    <th>Issue</th>
                    <th>Medium</th>
                    <th>Station</th>
                    <th>Day</th>
                    <th>Programme</th>
                    <th className="num">Rating</th>
                  </tr>
                </thead>
                <tbody>
                  {uploadIssues.map((issue) => (
                    <tr key={issue.rowNumber}>
                      <td className="num">{issue.rowNumber}</td>
                      <td>{issue.reason}</td>
                      <td>{issue.medium || '—'}</td>
                      <td>{issue.station || '—'}</td>
                      <td>{issue.day || '—'}</td>
                      <td>{issue.programme || '—'}</td>
                      <td className="num">{issue.rating !== null ? issue.rating : '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}

        {attachableLibrary.length > 0 && (
          <div className="upload-form-row attach-existing-row">
            <label>
              Or attach an existing dataset from the library
              <select value={attachSelection} onChange={(event) => setAttachSelection(event.target.value)}>
                <option value="">Select a dataset…</option>
                {attachableLibrary.map((dataset) => (
                  <option value={dataset.ratingsDatasetId} key={dataset.ratingsDatasetId}>
                    {dataset.provider || 'Untitled'} {dataset.period ? `— ${dataset.period}` : ''} ({dataset.rows} rows)
                  </option>
                ))}
              </select>
            </label>
            <button
              type="button"
              className="secondary-button"
              disabled={!attachSelection || isAttaching}
              onClick={handleAttachExisting}
            >
              {isAttaching ? 'Attaching…' : 'Attach'}
            </button>
          </div>
        )}
        {attachError && <p className="inline-error">{attachError}</p>}
        {loadError && <p className="inline-error">{loadError}</p>}

        <div className="dataset-list">
          {!loading && attached.length === 0 && !loadError && (
            <p className="empty-state">No ratings attached yet. Upload a file or attach one from the library above.</p>
          )}
          {attached.map((dataset) => (
            <RatingsDatasetRow
              dataset={dataset}
              key={dataset.ratingsDatasetId}
              isActive={dataset.ratingsDatasetId === selectedDatasetId}
              onSelect={() => setSelectedDatasetId(dataset.ratingsDatasetId)}
            />
          ))}
        </div>
      </div>

      {selectedDataset && (
        <div className="panel">
          <div className="panel-header">
            <div>
              <h2>{selectedDataset.provider || 'Untitled dataset'} — rows</h2>
              <p>
                {rowsLoading
                  ? 'Loading…'
                  : `${datasetRows.length} row${datasetRows.length === 1 ? '' : 's'}${
                      inspectableInvalidCount || selectedDataset.duplicateKeys
                        ? ` — click a flagged row for details`
                        : ''
                    }`}
              </p>
            </div>
            <AlertTriangle size={20} aria-hidden />
          </div>
          {rowsError && <p className="inline-error">{rowsError}</p>}
          {droppedInvalidCount > 0 && (
            <p className="field-hint">
              {droppedInvalidCount} more row{droppedInvalidCount === 1 ? '' : 's'} {droppedInvalidCount === 1 ? 'was' : 'were'} dropped
              during upload (missing a match field, or a rating outside 0–100) and never stored — not shown below.
            </p>
          )}
          {!rowsLoading && datasetRows.length === 0 && !rowsError && (
            <p className="empty-state">No rows in this dataset.</p>
          )}
          {datasetRows.length > 0 && (
            <div className="table-scroll">
              <table className="data-table">
                <thead>
                  <tr>
                    <th>Medium</th>
                    <th>Station</th>
                    <th>Day</th>
                    <th>Programme</th>
                    <th>Time Band</th>
                    <th className="num">Rating</th>
                    <th>Week</th>
                    <th>Month</th>
                    <th>Issue</th>
                  </tr>
                </thead>
                <tbody>
                  {datasetRows.map((row) => {
                    const siblings = (duplicateGroups.get(matchKey(row)) ?? []).filter(
                      (sibling) => sibling.ratingRowId !== row.ratingRowId,
                    );
                    const issue = describeIssue(row, siblings);
                    const isExpanded = expandedRowId === row.ratingRowId;
                    return (
                      <Fragment key={row.ratingRowId}>
                        <tr
                          className={issue ? 'clickable-row' : undefined}
                          onClick={issue ? () => setExpandedRowId(isExpanded ? null : row.ratingRowId) : undefined}
                        >
                          <td>{row.medium || '—'}</td>
                          <td>{row.station || '—'}</td>
                          <td>{row.day || '—'}</td>
                          <td>{row.programme || '—'}</td>
                          <td>{row.timeBand || '—'}</td>
                          <td className="num">{row.rating !== null ? row.rating : '—'}</td>
                          <td>{row.week ?? '—'}</td>
                          <td>{row.month ?? '—'}</td>
                          <td>
                            {issue ? (
                              <span className="status status-review">{issue.label}</span>
                            ) : (
                              '—'
                            )}
                          </td>
                        </tr>
                        {isExpanded && issue && (
                          <tr>
                            <td colSpan={9}>
                              <p className="field-hint" style={{ margin: 0 }}>
                                {issue.detail}
                              </p>
                            </td>
                          </tr>
                        )}
                      </Fragment>
                    );
                  })}
                </tbody>
              </table>
            </div>
          )}
        </div>
      )}
    </>
  );
}
