import { useCallback, useEffect, useState } from 'react';
import { Download, FileSpreadsheet } from 'lucide-react';
import { ApiError, createExport, downloadExport, listExports } from '../api/client';
import type { ExportJob, Project } from '../api/contracts';
import { LimitedRowsControls, useLimitedRows } from '../components/LimitedRows';

function suggestedFileName(project: Project): string {
  const safe = project.projectName.replace(/[^a-zA-Z0-9 _-]/g, '').trim().replace(/\s+/g, '_');
  return `${safe || 'mediapulse'}_export.xlsx`;
}

export default function ExportsSection({ project }: { project: Project | null }) {
  const [exports, setExports] = useState<ExportJob[]>([]);
  const limitedExports = useLimitedRows(exports);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [isGenerating, setIsGenerating] = useState(false);
  const [generateError, setGenerateError] = useState<string | null>(null);
  const [downloadingId, setDownloadingId] = useState<string | null>(null);
  const [downloadError, setDownloadError] = useState<string | null>(null);

  const refresh = useCallback(async (projectId: string) => {
    setLoading(true);
    setLoadError(null);
    try {
      setExports(await listExports(projectId));
    } catch (error) {
      setLoadError(error instanceof ApiError ? error.message : 'Could not load export history.');
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (project) {
      void refresh(project.projectId);
    } else {
      setExports([]);
    }
  }, [project, refresh]);

  async function handleGenerate() {
    if (!project) return;
    setIsGenerating(true);
    setGenerateError(null);
    try {
      const job = await createExport(project.projectId);
      setExports((current) => [job, ...current]);
    } catch (error) {
      setGenerateError(error instanceof ApiError ? error.message : 'Could not generate an export.');
    } finally {
      setIsGenerating(false);
    }
  }

  async function handleDownload(job: ExportJob) {
    if (!project) return;
    setDownloadingId(job.exportId);
    setDownloadError(null);
    try {
      await downloadExport(job, suggestedFileName(project));
    } catch (error) {
      setDownloadError(error instanceof ApiError ? error.message : 'Could not download that export.');
    } finally {
      setDownloadingId(null);
    }
  }

  if (!project) {
    return (
      <div className="panel placeholder-panel">
        <h2>No project selected</h2>
        <p>Open or create a project to generate an export.</p>
      </div>
    );
  }

  return (
    <div className="panel">
      <div className="panel-header">
        <div>
          <h2>Export Centre</h2>
          <p>
            {loading
              ? 'Loading…'
              : `Full Excel workbook for ${project.projectName} — Project Info, GRP & SOV, Brand Comparison, Station and Programme Performance, Spot-Level Calculations, Unmatched Records, and Ratings Used, each on its own sheet.`}
          </p>
        </div>
        <button type="button" className="primary-button" disabled={isGenerating} onClick={handleGenerate}>
          <FileSpreadsheet size={17} aria-hidden />
          {isGenerating ? 'Generating…' : 'Generate export'}
        </button>
      </div>
      {generateError && <p className="inline-error">{generateError}</p>}
      {downloadError && <p className="inline-error">{downloadError}</p>}
      {loadError && <p className="inline-error">{loadError}</p>}

      <p className="field-hint">
        Every export is tied to the calculation run current when it was generated — downloading it later always
        reproduces that same snapshot, even after a newer calculation or a version restore changes what
        "current" means for the project. Only the full Excel workbook exists today; executive-summary, PDF, and
        CSV formats are still planned.
      </p>

      <div className="table-scroll">
        <table className="data-table">
          <thead>
            <tr>
              <th>Generated</th>
              <th>Format</th>
              <th></th>
            </tr>
          </thead>
          <tbody>
            {!loading && exports.length === 0 && (
              <tr>
                <td colSpan={3} className="empty-state">
                  No exports yet — click "Generate export" above.
                </td>
              </tr>
            )}
            {limitedExports.visibleRows.map((job) => (
              <tr key={job.exportId}>
                <td>{job.generatedAt}</td>
                <td>{job.format}</td>
                <td>
                  <button
                    type="button"
                    className="secondary-button"
                    disabled={downloadingId === job.exportId}
                    onClick={() => handleDownload(job)}
                  >
                    <Download size={15} aria-hidden />
                    {downloadingId === job.exportId ? 'Downloading…' : 'Download'}
                  </button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <LimitedRowsControls shown={limitedExports.visibleRows.length} total={exports.length} hasMore={limitedExports.hasMore} canShowLess={limitedExports.canShowLess} onShowMore={limitedExports.showMore} onShowLess={limitedExports.showLess} />
      </div>
    </div>
  );
}
