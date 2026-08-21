import { useCallback, useEffect, useState, type FormEvent } from 'react';
import { Database } from 'lucide-react';
import {
  ApiError,
  attachRatingsDataset,
  listMappingTemplates,
  listProjectRatingsDatasets,
  listRatingsLibrary,
  uploadRatingsFile,
} from '../api/client';
import type { Project, RatingsDataset } from '../api/contracts';

function RatingsDatasetRow({ dataset }: { dataset: RatingsDataset }) {
  return (
    <div className="dataset-row">
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

  const [attachSelection, setAttachSelection] = useState('');
  const [isAttaching, setIsAttaching] = useState(false);
  const [attachError, setAttachError] = useState<string | null>(null);

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
    }
  }, [project, refresh]);

  async function handleUpload(event: FormEvent) {
    event.preventDefault();
    if (!project || !file) return;
    setIsUploading(true);
    setUploadError(null);
    setUploadSuccess(null);
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
      setFile(null);
      setFileInputKey((key) => key + 1);
      if (sourceLabel.trim()) {
        setKnownSourceLabels((current) => (current.includes(sourceLabel.trim()) ? current : [...current, sourceLabel.trim()]));
      }
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
      setAttachSelection('');
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
            <RatingsDatasetRow dataset={dataset} key={dataset.ratingsDatasetId} />
          ))}
        </div>
      </div>
    </>
  );
}
