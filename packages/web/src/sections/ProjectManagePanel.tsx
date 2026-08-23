import { useCallback, useEffect, useState, type FormEvent } from 'react';
import { Trash2 } from 'lucide-react';
import {
  ApiError,
  deleteBrand,
  deleteUpload,
  detachRatingsDataset,
  listBrands,
  listProjectRatingsDatasets,
  listUploads,
  updateProject,
  type UpdateProjectInput,
} from '../api/client';
import type { Brand, MediaType, Project, ProjectStatus, RatingsDataset, UploadBatch, User } from '../api/contracts';
import { LimitedRowsControls, useLimitedRows } from '../components/LimitedRows';

const STATUS_OPTIONS = ['Setup', 'Data Review', 'Complete'] as const;
const MEDIA_TYPE_OPTIONS: MediaType[] = ['TV', 'Radio', 'Cable TV'];

function toFormState(project: Project) {
  return {
    projectName: project.projectName,
    projectOwner: project.projectOwner,
    client: project.client,
    category: project.category,
    market: project.market,
    startDate: project.startDate ?? '',
    endDate: project.endDate ?? '',
    targetAudience: project.targetAudience,
    mediaTypes: project.mediaTypes,
    ratingsProvider: project.ratingsProvider,
    ratingsPeriod: project.ratingsPeriod,
    status: project.status,
    notes: project.notes,
  };
}

export default function ProjectManagePanel({
  project,
  currentUser,
  onProjectUpdated,
  onClose,
  refreshSignal,
}: {
  project: Project;
  currentUser: User;
  onProjectUpdated: (project: Project) => void;
  onClose: () => void;
  // Bumped by the caller after an upload or brand creation happens
  // elsewhere on the page — this panel now stays mounted continuously
  // (ProjectDetailSection's page, not a toggled overlay), so without this
  // its Uploads/Brands tables would only ever reflect data as of first
  // mount. Optional since ProjectManagePanel has no other caller today.
  refreshSignal?: number;
}) {
  const canManageData = currentUser.role === 'owner' || currentUser.role === 'admin';

  const [form, setForm] = useState(toFormState(project));
  const [isSaving, setIsSaving] = useState(false);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saveSuccess, setSaveSuccess] = useState(false);

  // Editing a different project (or the same project refreshing after
  // save) should reset the form to match — otherwise switching the active
  // project while this panel is open would keep showing stale field values.
  useEffect(() => {
    setForm(toFormState(project));
    setSaveSuccess(false);
  }, [project]);

  const [uploads, setUploads] = useState<UploadBatch[]>([]);
  const [brands, setBrands] = useState<Brand[]>([]);
  const [datasets, setDatasets] = useState<RatingsDataset[]>([]);
  const [dataLoading, setDataLoading] = useState(false);
  const [dataError, setDataError] = useState<string | null>(null);
  const [pendingActionId, setPendingActionId] = useState<string | null>(null);
  const limitedUploads = useLimitedRows(uploads);
  const limitedBrands = useLimitedRows(brands);
  const limitedDatasets = useLimitedRows(datasets);

  const refreshData = useCallback(async (projectId: string) => {
    setDataLoading(true);
    setDataError(null);
    try {
      const [uploadResults, brandResults, datasetResults] = await Promise.all([
        listUploads(projectId),
        listBrands(projectId),
        listProjectRatingsDatasets(projectId),
      ]);
      setUploads(uploadResults);
      setBrands(brandResults);
      setDatasets(datasetResults);
    } catch (error) {
      setDataError(error instanceof ApiError ? error.message : 'Could not load project data.');
    } finally {
      setDataLoading(false);
    }
  }, []);

  useEffect(() => {
    void refreshData(project.projectId);
  }, [project.projectId, refreshSignal, refreshData]);

  function toggleMediaType(type: MediaType) {
    setForm((current) => ({
      ...current,
      mediaTypes: current.mediaTypes.includes(type)
        ? current.mediaTypes.filter((t) => t !== type)
        : [...current.mediaTypes, type],
    }));
  }

  async function handleSave(event: FormEvent) {
    event.preventDefault();
    setIsSaving(true);
    setSaveError(null);
    setSaveSuccess(false);
    try {
      const input: UpdateProjectInput = {
        ...form,
        startDate: form.startDate || null,
        endDate: form.endDate || null,
      };
      const updated = await updateProject(project.projectId, input);
      onProjectUpdated(updated);
      setSaveSuccess(true);
    } catch (error) {
      setSaveError(error instanceof ApiError ? error.message : 'Could not save these changes.');
    } finally {
      setIsSaving(false);
    }
  }

  async function handleDeleteUpload(upload: UploadBatch) {
    setPendingActionId(upload.uploadId);
    setDataError(null);
    try {
      await deleteUpload(project.projectId, upload.uploadId);
      await refreshData(project.projectId);
    } catch (error) {
      setDataError(error instanceof ApiError ? error.message : 'Could not delete that upload.');
    } finally {
      setPendingActionId(null);
    }
  }

  async function handleDeleteBrand(brand: Brand) {
    setPendingActionId(brand.brandId);
    setDataError(null);
    try {
      await deleteBrand(project.projectId, brand.brandId);
      await refreshData(project.projectId);
    } catch (error) {
      setDataError(error instanceof ApiError ? error.message : 'Could not delete that brand.');
    } finally {
      setPendingActionId(null);
    }
  }

  async function handleDetachDataset(dataset: RatingsDataset) {
    setPendingActionId(dataset.ratingsDatasetId);
    setDataError(null);
    try {
      await detachRatingsDataset(project.projectId, dataset.ratingsDatasetId);
      await refreshData(project.projectId);
    } catch (error) {
      setDataError(error instanceof ApiError ? error.message : 'Could not detach that dataset.');
    } finally {
      setPendingActionId(null);
    }
  }

  return (
    <div className="panel">
      <div className="panel-header">
        <div>
          <h2>Project Settings</h2>
          <p>{project.projectName} — assumptions, notes, and the data behind it</p>
        </div>
        <button type="button" className="secondary-button" onClick={onClose}>
          Close
        </button>
      </div>

      <form className="upload-form" onSubmit={handleSave}>
        <div className="upload-form-row">
          <label>
            Project name
            <input
              type="text"
              value={form.projectName}
              onChange={(event) => setForm({ ...form, projectName: event.target.value })}
            />
          </label>
          <label>
            Owner
            <input
              type="text"
              value={form.projectOwner}
              onChange={(event) => setForm({ ...form, projectOwner: event.target.value })}
            />
          </label>
          <label>
            Status
            <select
              value={form.status}
              onChange={(event) => setForm({ ...form, status: event.target.value as ProjectStatus })}
            >
              {STATUS_OPTIONS.map((status) => (
                <option value={status} key={status}>
                  {status}
                </option>
              ))}
            </select>
          </label>
        </div>

        <div className="upload-form-row">
          <label>
            Client
            <input type="text" value={form.client} onChange={(event) => setForm({ ...form, client: event.target.value })} />
          </label>
          <label>
            Category
            <input
              type="text"
              value={form.category}
              onChange={(event) => setForm({ ...form, category: event.target.value })}
            />
          </label>
          <label>
            Market
            <input type="text" value={form.market} onChange={(event) => setForm({ ...form, market: event.target.value })} />
          </label>
        </div>

        <div className="upload-form-row">
          <label>
            Start date
            <input
              type="date"
              value={form.startDate}
              onChange={(event) => setForm({ ...form, startDate: event.target.value })}
            />
          </label>
          <label>
            End date
            <input type="date" value={form.endDate} onChange={(event) => setForm({ ...form, endDate: event.target.value })} />
          </label>
          <label>
            Target audience
            <input
              type="text"
              value={form.targetAudience}
              onChange={(event) => setForm({ ...form, targetAudience: event.target.value })}
            />
          </label>
        </div>

        <div className="upload-form-row">
          <label>
            Ratings provider
            <input
              type="text"
              value={form.ratingsProvider}
              onChange={(event) => setForm({ ...form, ratingsProvider: event.target.value })}
            />
          </label>
          <label>
            Ratings period
            <input
              type="text"
              value={form.ratingsPeriod}
              onChange={(event) => setForm({ ...form, ratingsPeriod: event.target.value })}
            />
          </label>
          <div className="media-types-field">
            <span>Media types</span>
            <div className="media-types-options">
              {MEDIA_TYPE_OPTIONS.map((type) => (
                <label className="checkbox-field" key={type}>
                  <input
                    type="checkbox"
                    checked={form.mediaTypes.includes(type)}
                    onChange={() => toggleMediaType(type)}
                  />
                  {type}
                </label>
              ))}
            </div>
          </div>
        </div>

        <label>
          Notes
          <textarea
            rows={3}
            value={form.notes}
            onChange={(event) => setForm({ ...form, notes: event.target.value })}
          />
        </label>

        <div className="form-actions">
          <button type="submit" className="primary-button" disabled={isSaving}>
            {isSaving ? 'Saving…' : 'Save changes'}
          </button>
          {saveSuccess && <span className="empty-state">Saved.</span>}
        </div>
        {saveError && <p className="inline-error">{saveError}</p>}
      </form>

      <div className="panel-header">
        <div>
          <h2>Manage data</h2>
          <p>
            {canManageData
              ? "Delete an upload or brand before it's ever been included in a calculated run to remove it entirely; anything already calculated is protected from deletion to keep that run's audit trail intact."
              : 'Only an owner or admin can delete uploads or brands. Detaching a ratings dataset is open to anyone.'}
          </p>
        </div>
      </div>
      {dataError && <p className="inline-error">{dataError}</p>}

      <h3 className="subsection">Uploads {dataLoading ? '(loading…)' : `(${uploads.length})`}</h3>
      <div className="table-scroll">
        <table className="data-table">
          <thead>
            <tr>
              <th>File</th>
              <th>Kind</th>
              <th className="num">Mapped</th>
              <th>Uploaded</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {!dataLoading && uploads.length === 0 && (
              <tr>
                <td colSpan={5} className="empty-state">
                  No uploads yet.
                </td>
              </tr>
            )}
            {limitedUploads.visibleRows.map((upload) => (
              <tr key={upload.uploadId}>
                <td>{upload.fileName}</td>
                <td>{upload.kind}</td>
                <td className="num">{upload.mappedRows}</td>
                <td>{upload.uploadedAt}</td>
                <td>
                  {canManageData && (
                    <button
                      type="button"
                      className="icon-button"
                      title="Delete this upload (only if never calculated)"
                      disabled={pendingActionId === upload.uploadId}
                      onClick={() => handleDeleteUpload(upload)}
                    >
                      <Trash2 size={15} aria-hidden />
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <LimitedRowsControls shown={limitedUploads.visibleRows.length} total={uploads.length} hasMore={limitedUploads.hasMore} canShowLess={limitedUploads.canShowLess} onShowMore={limitedUploads.showMore} onShowLess={limitedUploads.showLess} />
      </div>

      <h3 className="subsection">Brands {dataLoading ? '(loading…)' : `(${brands.length})`}</h3>
      <div className="table-scroll">
        <table className="data-table">
          <thead>
            <tr>
              <th>Name</th>
              <th>Created</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {!dataLoading && brands.length === 0 && (
              <tr>
                <td colSpan={3} className="empty-state">
                  No brands yet.
                </td>
              </tr>
            )}
            {limitedBrands.visibleRows.map((brand) => (
              <tr key={brand.brandId}>
                <td>{brand.name}</td>
                <td>{brand.createdAt}</td>
                <td>
                  {canManageData && (
                    <button
                      type="button"
                      className="icon-button"
                      title="Delete this brand (only if never calculated)"
                      disabled={pendingActionId === brand.brandId}
                      onClick={() => handleDeleteBrand(brand)}
                    >
                      <Trash2 size={15} aria-hidden />
                    </button>
                  )}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <LimitedRowsControls shown={limitedBrands.visibleRows.length} total={brands.length} hasMore={limitedBrands.hasMore} canShowLess={limitedBrands.canShowLess} onShowMore={limitedBrands.showMore} onShowLess={limitedBrands.showLess} />
      </div>

      <h3 className="subsection">Attached ratings datasets {dataLoading ? '(loading…)' : `(${datasets.length})`}</h3>
      <div className="table-scroll">
        <table className="data-table">
          <thead>
            <tr>
              <th>Provider</th>
              <th>Period</th>
              <th className="num">Rows</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {!dataLoading && datasets.length === 0 && (
              <tr>
                <td colSpan={4} className="empty-state">
                  No ratings attached.
                </td>
              </tr>
            )}
            {limitedDatasets.visibleRows.map((dataset) => (
              <tr key={dataset.ratingsDatasetId}>
                <td>{dataset.provider || 'Untitled'}</td>
                <td>{dataset.period || '—'}</td>
                <td className="num">{dataset.rows}</td>
                <td>
                  <button
                    type="button"
                    className="icon-button"
                    title="Detach this dataset from the project"
                    disabled={pendingActionId === dataset.ratingsDatasetId}
                    onClick={() => handleDetachDataset(dataset)}
                  >
                    <Trash2 size={15} aria-hidden />
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <LimitedRowsControls shown={limitedDatasets.visibleRows.length} total={datasets.length} hasMore={limitedDatasets.hasMore} canShowLess={limitedDatasets.canShowLess} onShowMore={limitedDatasets.showMore} onShowLess={limitedDatasets.showLess} />
      </div>
    </div>
  );
}
