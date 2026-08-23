import type {
  AuthSession,
  Brand,
  BrandShare,
  DaypartShare,
  ExportJob,
  GrpCalculationRow,
  GrpRunSummary,
  MappingTemplate,
  MatchJob,
  MediaActivityRow,
  ProgrammeShare,
  Project,
  ProjectVersion,
  RatingMatch,
  RatingRow,
  RatingsDataset,
  SpotEfficiency,
  StationShare,
  TrendPoint,
  UploadBatch,
  User,
  ValidationIssue,
} from './contracts';

// See services/api/README.md for how to run the API locally; defaults to the
// docker-compose/uvicorn default port.
const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL as string | undefined)?.replace(/\/$/, '') ?? 'http://127.0.0.1:8000';

const TOKEN_STORAGE_KEY = 'mediapulse.token';
let authToken: string | null = typeof localStorage !== 'undefined' ? localStorage.getItem(TOKEN_STORAGE_KEY) : null;
// Every route except /api/auth/register and /api/auth/login now requires a
// bearer token (services/api/app/auth.py) — this lets App.tsx react to a
// token going bad mid-session (expired, or the account's role changed
// server-side) without every screen having to check for a 401 itself.
let onUnauthorized: (() => void) | null = null;

export function getAuthToken(): string | null {
  return authToken;
}

export function setAuthToken(token: string | null): void {
  authToken = token;
  if (typeof localStorage === 'undefined') return;
  if (token) localStorage.setItem(TOKEN_STORAGE_KEY, token);
  else localStorage.removeItem(TOKEN_STORAGE_KEY);
}

export function onAuthTokenRejected(handler: (() => void) | null): void {
  onUnauthorized = handler;
}

export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  // FormData bodies (file uploads) must NOT get a manual Content-Type — the
  // browser sets its own multipart boundary, and overriding it breaks parsing.
  const isFormData = typeof FormData !== 'undefined' && init?.body instanceof FormData;
  const headers: Record<string, string> = isFormData ? {} : { 'Content-Type': 'application/json' };
  if (authToken) headers.Authorization = `Bearer ${authToken}`;
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}${path}`, { ...init, headers: { ...headers, ...init?.headers } });
  } catch {
    throw new ApiError(0, `Could not reach the Mediapulse API at ${API_BASE_URL}.`);
  }

  if (!response.ok) {
    let detail = response.statusText || `Request failed (${response.status})`;
    try {
      const body = (await response.json()) as { detail?: string };
      detail = body.detail ?? detail;
    } catch {
      // Non-JSON error body — fall back to statusText above.
    }
    // 401 on the auth endpoints themselves means "wrong password" / "not
    // logged in yet" — expected, not a reason to blow away a token that was
    // never set. Everywhere else, a 401 means the token this session is
    // holding is no longer good (expired, or never valid).
    if (response.status === 401 && authToken && !path.startsWith('/api/auth/')) {
      setAuthToken(null);
      onUnauthorized?.();
    }
    throw new ApiError(response.status, detail);
  }

  if (response.status === 204) {
    return undefined as T;
  }
  return (await response.json()) as T;
}

export function register(input: { email: string; password: string; displayName?: string }): Promise<AuthSession> {
  return request<AuthSession>('/api/auth/register', { method: 'POST', body: JSON.stringify(input) });
}

export function login(input: { email: string; password: string }): Promise<AuthSession> {
  return request<AuthSession>('/api/auth/login', { method: 'POST', body: JSON.stringify(input) });
}

export function getCurrentUser(): Promise<User> {
  return request<User>('/api/auth/me');
}

export function listUsers(): Promise<User[]> {
  return request<User[]>('/api/users');
}

export function updateUserRole(userId: string, role: string): Promise<User> {
  return request<User>(`/api/users/${userId}/role`, { method: 'PATCH', body: JSON.stringify({ role }) });
}

export interface ListProjectsParams {
  search?: string;
  includeArchived?: boolean;
}

export function listProjects(params: ListProjectsParams = {}): Promise<Project[]> {
  const query = new URLSearchParams();
  if (params.search) query.set('search', params.search);
  if (params.includeArchived !== undefined) query.set('include_archived', String(params.includeArchived));
  const suffix = query.toString() ? `?${query.toString()}` : '';
  return request<Project[]>(`/api/projects${suffix}`);
}

export interface CreateProjectInput {
  projectName: string;
  client?: string;
  category?: string;
  market?: string;
}

export function createProject(input: CreateProjectInput): Promise<Project> {
  return request<Project>('/api/projects', { method: 'POST', body: JSON.stringify(input) });
}

export function archiveProject(projectId: string): Promise<Project> {
  return request<Project>(`/api/projects/${projectId}`, {
    method: 'PATCH',
    body: JSON.stringify({ archived: true }),
  });
}

export interface UpdateProjectInput {
  projectName?: string;
  projectOwner?: string;
  client?: string;
  category?: string;
  market?: string;
  startDate?: string | null;
  endDate?: string | null;
  targetAudience?: string;
  mediaTypes?: string[];
  ratingsProvider?: string;
  ratingsPeriod?: string;
  status?: string;
  notes?: string;
}

// Field-editing half of Project Settings (PRODUCT_ROADMAP.md) — archiving
// goes through the dedicated archiveProject() above instead, since it's
// role-gated separately on the backend (owner/admin only) from every other
// field on this same PATCH endpoint (any authenticated user).
export function updateProject(projectId: string, input: UpdateProjectInput): Promise<Project> {
  return request<Project>(`/api/projects/${projectId}`, { method: 'PATCH', body: JSON.stringify(input) });
}

// "No run yet" is a normal, expected state for a project that hasn't been
// calculated (or has no matched activity) — not an error the caller should
// have to catch a 404 for every time, so it's collapsed to null here.
export async function getLatestRun(projectId: string): Promise<GrpRunSummary | null> {
  try {
    return await request<GrpRunSummary>(`/api/projects/${projectId}/runs/latest`);
  } catch (error) {
    if (error instanceof ApiError && error.status === 404) {
      return null;
    }
    throw error;
  }
}

export function listBrandShares(projectId: string, runId: string): Promise<BrandShare[]> {
  return request<BrandShare[]>(`/api/projects/${projectId}/runs/${runId}/brand-shares`);
}

export function calculateProject(projectId: string): Promise<GrpRunSummary> {
  return request<GrpRunSummary>(`/api/projects/${projectId}/calculate`, { method: 'POST' });
}

export function listBrands(projectId: string): Promise<Brand[]> {
  return request<Brand[]>(`/api/projects/${projectId}/brands`);
}

export function createBrand(projectId: string, name: string): Promise<Brand> {
  return request<Brand>(`/api/projects/${projectId}/brands`, {
    method: 'POST',
    body: JSON.stringify({ name }),
  });
}

// Refused with a 409 (surfaced as ApiError) if this brand has ever been
// part of a calculated run, to protect that run's audit trail — see
// services/api/app/routers/brands.py.
export function deleteBrand(projectId: string, brandId: string): Promise<void> {
  return request<void>(`/api/projects/${projectId}/brands/${brandId}`, { method: 'DELETE' });
}

export function listUploads(projectId: string): Promise<UploadBatch[]> {
  return request<UploadBatch[]>(`/api/projects/${projectId}/uploads`);
}

// Same audit-trail protection as deleteBrand.
export function deleteUpload(projectId: string, uploadId: string): Promise<void> {
  return request<void>(`/api/projects/${projectId}/uploads/${uploadId}`, { method: 'DELETE' });
}

export interface UploadMediaReportInput {
  kind: 'brand_report' | 'composite_report';
  // Required for brand_report (one brand per file); omitted for
  // composite_report, which reads a Brand column from the file itself and
  // resolves/creates a brand per distinct name found.
  brandId?: string;
  defaultMedium: string;
  file: File;
  // Ties this upload to a saved mapping_template: an existing template for
  // this label is applied instead of auto-detection; a not-yet-seen label
  // (or saveAsTemplate=true) saves the mapping actually used, so later
  // uploads from the same source map automatically. See
  // services/api/README.md.
  sourceLabel?: string;
  saveAsTemplate?: boolean;
}

export function uploadMediaReport(projectId: string, input: UploadMediaReportInput): Promise<UploadBatch> {
  const formData = new FormData();
  formData.append('kind', input.kind);
  if (input.brandId) formData.append('brand_id', input.brandId);
  formData.append('default_medium', input.defaultMedium);
  if (input.sourceLabel) formData.append('source_label', input.sourceLabel);
  if (input.saveAsTemplate) formData.append('save_as_template', 'true');
  formData.append('file', input.file);
  return request<UploadBatch>(`/api/projects/${projectId}/uploads`, { method: 'POST', body: formData });
}

export function listMediaActivity(projectId: string): Promise<MediaActivityRow[]> {
  return request<MediaActivityRow[]>(`/api/projects/${projectId}/media-activity`);
}

export function listMatches(projectId: string): Promise<RatingMatch[]> {
  return request<RatingMatch[]>(`/api/projects/${projectId}/matches`);
}

export function startMatchJob(projectId: string, mode: 'ensure' | 'recompute' = 'ensure'): Promise<MatchJob> {
  return request<MatchJob>(`/api/projects/${projectId}/matches/jobs?mode=${mode}`, { method: 'POST' });
}

export function getMatchJob(projectId: string, jobId: string): Promise<MatchJob> {
  return request<MatchJob>(`/api/projects/${projectId}/matches/jobs/${jobId}`);
}

export function correctMatch(projectId: string, ratingMatchId: string, matchedRatingId: string | null): Promise<RatingMatch> {
  return request<RatingMatch>(`/api/projects/${projectId}/matches/${ratingMatchId}/correct`, {
    method: 'POST',
    body: JSON.stringify({ matchedRatingId }),
  });
}

// Retries 'unmatched' rows only (exact/suggested/manual are left alone) —
// useful after attaching ratings to a project that already had matches computed.
export function recomputeMatches(projectId: string): Promise<RatingMatch[]> {
  return request<RatingMatch[]>(`/api/projects/${projectId}/matches/recompute`, { method: 'POST' });
}

export function listCalculations(projectId: string, runId: string): Promise<GrpCalculationRow[]> {
  return request<GrpCalculationRow[]>(`/api/projects/${projectId}/runs/${runId}/calculations`);
}

export function listValidationIssues(projectId: string): Promise<ValidationIssue[]> {
  return request<ValidationIssue[]>(`/api/projects/${projectId}/validation-issues`);
}

// The full shared library, not scoped to a project — used by the "attach an
// existing dataset" flow.
export function listRatingsLibrary(): Promise<RatingsDataset[]> {
  return request<RatingsDataset[]>('/api/ratings-datasets');
}

export function listProjectRatingsDatasets(projectId: string): Promise<RatingsDataset[]> {
  return request<RatingsDataset[]>(`/api/projects/${projectId}/ratings-datasets`);
}

export function attachRatingsDataset(projectId: string, ratingsDatasetId: string): Promise<void> {
  return request<void>(`/api/projects/${projectId}/ratings-datasets/${ratingsDatasetId}/attach`, { method: 'POST' });
}

// Only unlinks the dataset from this project — the shared dataset itself,
// and anything already matched/calculated against it, are untouched.
export function detachRatingsDataset(projectId: string, ratingsDatasetId: string): Promise<void> {
  return request<void>(`/api/projects/${projectId}/ratings-datasets/${ratingsDatasetId}/attach`, { method: 'DELETE' });
}

export function listRatingRows(ratingsDatasetId: string): Promise<RatingRow[]> {
  return request<RatingRow[]>(`/api/ratings-datasets/${ratingsDatasetId}/rows`);
}

export interface UploadRatingsFileInput {
  provider?: string;
  period?: string;
  market?: string;
  audience?: string;
  defaultMedium?: string;
  file: File;
  sourceLabel?: string;
  saveAsTemplate?: boolean;
}

export function uploadRatingsFile(input: UploadRatingsFileInput): Promise<RatingsDataset> {
  const formData = new FormData();
  if (input.provider) formData.append('provider', input.provider);
  if (input.period) formData.append('period', input.period);
  if (input.market) formData.append('market', input.market);
  if (input.audience) formData.append('audience', input.audience);
  formData.append('default_medium', input.defaultMedium ?? 'TV');
  if (input.sourceLabel) formData.append('source_label', input.sourceLabel);
  if (input.saveAsTemplate) formData.append('save_as_template', 'true');
  formData.append('file', input.file);
  return request<RatingsDataset>('/api/ratings-datasets/upload', { method: 'POST', body: formData });
}

export function listStationShares(projectId: string, runId: string): Promise<StationShare[]> {
  return request<StationShare[]>(`/api/projects/${projectId}/runs/${runId}/stations`);
}

export function listProgrammeShares(projectId: string, runId: string): Promise<ProgrammeShare[]> {
  return request<ProgrammeShare[]>(`/api/projects/${projectId}/runs/${runId}/programmes`);
}

export function listDaypartShares(projectId: string, runId: string): Promise<DaypartShare[]> {
  return request<DaypartShare[]>(`/api/projects/${projectId}/runs/${runId}/dayparts`);
}

export function listSpotEfficiency(projectId: string, runId: string): Promise<SpotEfficiency[]> {
  return request<SpotEfficiency[]>(`/api/projects/${projectId}/runs/${runId}/spot-efficiency`);
}

export function listTrend(projectId: string, runId: string): Promise<TrendPoint[]> {
  return request<TrendPoint[]>(`/api/projects/${projectId}/runs/${runId}/trend`);
}

// Used to power a source-label autocomplete on the upload forms.
export function listMappingTemplates(): Promise<MappingTemplate[]> {
  return request<MappingTemplate[]>('/api/mapping-templates');
}

// One entry per past calculation run — "each recalculation becomes a
// version" (PRODUCT_ROADMAP.md). versionId doubles as runId.
export function listVersions(projectId: string): Promise<ProjectVersion[]> {
  return request<ProjectVersion[]>(`/api/projects/${projectId}/versions`);
}

// Pins GET .../runs/latest (and everything derived from it) back to an
// older run. Owner/admin only — services/api 403s otherwise.
export function restoreVersion(projectId: string, versionId: string): Promise<ProjectVersion> {
  return request<ProjectVersion>(`/api/projects/${projectId}/versions/${versionId}/restore`, { method: 'POST' });
}

export function listExports(projectId: string): Promise<ExportJob[]> {
  return request<ExportJob[]>(`/api/projects/${projectId}/exports`);
}

// Only 'xlsx_full' exists today — see PRODUCT_ROADMAP.md's Export Centre
// section for the still-planned xlsx_summary/pdf/csv formats.
export function createExport(projectId: string, runId?: string): Promise<ExportJob> {
  return request<ExportJob>(`/api/projects/${projectId}/exports`, {
    method: 'POST',
    body: JSON.stringify({ format: 'xlsx_full', runId: runId ?? null }),
  });
}

// The download route returns a raw .xlsx body, not JSON, and needs the
// same bearer token as every other request — a plain <a href> can't attach
// that header, so this fetches the bytes itself and hands the browser a
// blob: URL to save, the standard workaround for an authenticated download.
export async function downloadExport(job: ExportJob, suggestedFileName: string): Promise<void> {
  const token = getAuthToken();
  const response = await fetch(`${API_BASE_URL}${job.downloadUrl}`, {
    headers: token ? { Authorization: `Bearer ${token}` } : {},
  });
  if (!response.ok) {
    throw new ApiError(response.status, response.statusText || `Download failed (${response.status})`);
  }
  const blob = await response.blob();
  const blobUrl = URL.createObjectURL(blob);
  const link = document.createElement('a');
  link.href = blobUrl;
  link.download = suggestedFileName;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(blobUrl);
}
