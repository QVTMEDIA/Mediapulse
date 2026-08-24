export type ProjectStatus = 'Setup' | 'Data Review' | 'Complete';
export type MediaType = 'TV' | 'Radio' | 'Cable TV';
export type UploadKind = 'ratings' | 'brand_report' | 'composite_report';
export type ValidationSeverity = 'info' | 'warning' | 'error';
export type UserRole = 'owner' | 'admin' | 'member';

export interface User {
  userId: string;
  email: string;
  displayName: string;
  role: UserRole;
  createdAt: string;
}

export interface AuthSession {
  accessToken: string;
  tokenType: string;
  user: User;
}

export interface Project {
  projectId: string;
  projectName: string;
  projectOwner: string;
  client: string;
  category: string;
  market: string;
  // Nullable because services/api's ProjectOut leaves these unset until the
  // user fills in Project Setup — the sample data below always has them.
  startDate: string | null;
  endDate: string | null;
  targetAudience: string;
  mediaTypes: MediaType[];
  ratingsProvider: string;
  ratingsPeriod: string;
  status: ProjectStatus;
  archived: boolean;
  notes: string;
  createdAt: string;
  updatedAt: string;
}

export interface RatingsDataset {
  ratingsDatasetId: string;
  provider: string;
  period: string;
  market: string;
  audience: string;
  mediaTypes: MediaType[];
  rows: number;
  invalidRows: number;
  duplicateKeys: number;
  uploadedAt: string;
  status: 'Ready' | 'Needs Review';
  // Why up to 100 rows were dropped during file-upload parsing and never
  // stored — only ever present on the response to POST
  // /ratings-datasets/upload; every other route leaves it undefined, since
  // dropped rows aren't persisted anywhere to look up again later.
  issues?: RatingsRowIssue[];
  // A saved mapping template disagreed with fresh auto-detection for a
  // field on this upload — only ever populated on the response to POST
  // /ratings-datasets/upload, same as issues above. See MappingWarning.
  mappingWarnings: MappingWarning[];
}

export interface RatingsRowIssue {
  rowNumber: number;
  reason: string;
  medium: string;
  station: string;
  day: string;
  programme: string;
  rating: number | null;
}

// A saved mapping template pinned `field` to `templateColumn`, but this
// file's own columns would have auto-detected `detectedColumn` instead —
// a real, previously-silent trap: a template saved from an older file's
// shape gets reused against a newer file that actually has a better match
// sitting right next to it, and the stale template wins with no
// indication anything was overridden. Every row still parses
// "successfully" — the failure only shows up much later as spot after
// spot coming back unmatched.
export interface MappingWarning {
  field: string;
  templateColumn: string;
  detectedColumn: string;
}

export interface Brand {
  brandId: string;
  projectId: string;
  name: string;
  createdAt: string;
}

export interface UploadBatch {
  uploadId: string;
  projectId: string;
  // Null for composite_report uploads (they span more than one brand —
  // attribution lives on each media_activity row instead).
  brandId: string | null;
  fileName: string;
  kind: UploadKind;
  mappedRows: number;
  issueRows: number;
  uploadedAt: string;
  // Only ever populated on the response to POST .../uploads (this
  // upload's own parse) — GET .../uploads (listing past uploads) always
  // leaves this empty. See MappingWarning.
  mappingWarnings: MappingWarning[];
}

export interface GrpRunSummary {
  runId: string;
  projectId: string;
  totalBrands: number;
  totalSpots: number;
  totalGrps: number;
  // Sum of resolved media spend across every activity row in this run,
  // matched or not — see BrandShare.totalSpend for why this differs from
  // totalGrps, which only counts matched rows.
  totalSpend: number;
  matchedRows: number;
  unmatchedRows: number;
  // True for the run currently shown everywhere as "latest" — the newest
  // run unless a version-history restore pinned it back to an older one.
  isCurrent: boolean;
  generatedAt: string;
}

export interface BrandShare {
  runId: string;
  brandId: string;
  brand: string;
  totalGrps: number;
  // tvGrps means terrestrial/generic TV, same as it always has; cableTvGrps
  // is a newer, additive bucket (DStv/GOtv/satellite/pay-TV) that only gets
  // populated when a source explicitly says so — see the Medium synonym
  // list this session added in grp_calculator.normalize_medium_type.
  tvGrps: number;
  cableTvGrps: number;
  radioGrps: number;
  sov: number;
  spots: number;
  avgRating: number | null;
  // Share of Expenditure — brand spend / category spend, summed across
  // every one of the brand's media_activity rows regardless of match
  // status (unlike totalGrps/sov, which only count matched rows).
  totalSpend: number;
  soe: number;
  // Spend broken out by medium, same shape as tvGrps/cableTvGrps/radioGrps
  // — backs the Spend Intelligence screen's medium breakdown. May not sum
  // exactly to totalSpend (a row whose medium doesn't canonicalize to TV/
  // Cable TV/Radio isn't counted in any of the three).
  tvSpend: number;
  cableTvSpend: number;
  radioSpend: number;
}

export interface StationShare {
  runId: string;
  brandId: string;
  brand: string;
  station: string;
  totalGrps: number;
  spots: number;
}

export interface ProgrammeShare {
  runId: string;
  brandId: string;
  brand: string;
  programme: string;
  totalGrps: number;
  spots: number;
}

export interface DaypartShare {
  runId: string;
  brandId: string;
  brand: string;
  // The vendor's own daypart/time-band label (e.g. "AM", "Prime Time"),
  // not a canonical bucket the app defines — '' for rows with no daypart
  // column mapped in the source file.
  timeBand: string;
  totalGrps: number;
  spots: number;
}

export interface SpotEfficiency {
  runId: string;
  brandId: string;
  brand: string;
  station: string;
  spots: number;
  totalGrps: number;
  grpPerSpot: number;
  // Flagged when this brand/station's own GRP-per-spot sits well below the
  // category's average for the run, at high enough spot volume for it to
  // be a real pattern — see services/api's routers/runs.py for the exact
  // thresholds. A computed judgment call, not a stored fact.
  isWeak: boolean;
}

export interface TrendPoint {
  runId: string;
  brandId: string;
  brand: string;
  weekStart: string;
  totalGrps: number;
  spots: number;
}

export interface ExportJob {
  exportId: string;
  projectId: string;
  runId: string | null;
  format: string;
  generatedAt: string;
  downloadUrl: string;
}

export interface ProjectVersion {
  versionId: string;
  projectId: string;
  runId: string;
  description: string;
  isCurrent: boolean;
  createdAt: string;
}

export interface MappingTemplate {
  mappingTemplateId: string;
  sourceLabel: string;
  fieldMapping: Record<string, string>;
  createdAt: string;
  lastUsedAt: string | null;
}

export interface ValidationIssue {
  issueId: string;
  projectId: string;
  runId: string | null;
  severity: ValidationSeverity;
  area: string;
  message: string;
  rows: number;
}

export interface MediaActivityRow {
  mediaActivityId: string;
  projectId: string;
  brandId: string;
  uploadId: string;
  medium: string;
  station: string;
  activityDate: string | null;
  day: string;
  programme: string;
  spots: number;
  // Resolved media spend for this row (Share of Expenditure) — null means
  // no cost/rate column was ever mapped for this upload, not a confirmed
  // zero spend.
  cost: number | null;
  // The vendor's own daypart/time-band label, captured as-is — '' when the
  // file had no such column. Separate from `programme`; never used for
  // rating matching.
  timeBand: string;
  sourceFile: string;
}

export type MatchStatus = 'exact' | 'suggested' | 'unmatched' | 'manual';

export interface RatingMatch {
  ratingMatchId: string;
  mediaActivityId: string;
  matchedRatingId: string | null;
  matchStatus: MatchStatus;
  matchConfidence: number | null;
  matchKey: string;
  correctedAt: string | null;
}

export interface MatchJob {
  jobId: string;
  projectId: string;
  status: 'queued' | 'running' | 'completed' | 'failed';
  error: string | null;
  // Real progress for recompute jobs only; ensure jobs always report 0/0.
  total: number;
  processed: number;
}

export interface RatingRow {
  ratingRowId: string;
  ratingsDatasetId: string;
  medium: string;
  station: string;
  day: string;
  programme: string;
  timeBand: string;
  rating: number | null;
  startTime: string | null;
  endTime: string | null;
  week: number | null;
  month: number | null;
}

export interface GrpCalculationRow {
  grpCalculationId: string;
  runId: string;
  mediaActivityId: string;
  brandId: string;
  brand: string;
  station: string;
  programme: string;
  day: string;
  medium: string;
  spots: number;
  rating: number;
  grp: number;
  calculatedAt: string;
}

export interface MediapulseWorkspace {
  projects: Project[];
  ratingsDatasets: RatingsDataset[];
  uploads: UploadBatch[];
  latestRun: GrpRunSummary;
  brandShares: BrandShare[];
  validationIssues: ValidationIssue[];
}

export const sampleWorkspace: MediapulseWorkspace = {
  projects: [
    {
      projectId: 'MP-2608-A',
      projectName: 'Seasoning Category Q1 2026',
      projectOwner: 'Media Lead',
      client: 'Sample Client',
      category: 'Seasoning',
      market: 'Nigeria',
      startDate: '2026-01-01',
      endDate: '2026-03-31',
      targetAudience: 'Adults 18-45 ABC',
      mediaTypes: ['TV', 'Radio'],
      ratingsProvider: 'Sample Provider',
      ratingsPeriod: 'Q1 2026',
      status: 'Data Review',
      archived: false,
      notes: '',
      createdAt: '2026-08-19 10:00:00',
      updatedAt: '2026-08-19 17:00:00',
    },
    {
      projectId: 'MP-2608-B',
      projectName: 'Beverage Launch Monitor',
      projectOwner: 'Insights Desk',
      client: 'Sample Client',
      category: 'Beverage',
      market: 'Nigeria',
      startDate: '2026-04-01',
      endDate: '2026-04-30',
      targetAudience: 'Adults 18+',
      mediaTypes: ['TV'],
      ratingsProvider: 'Sample Provider',
      ratingsPeriod: 'April 2026',
      status: 'Setup',
      archived: false,
      notes: '',
      createdAt: '2026-08-18 11:15:00',
      updatedAt: '2026-08-18 11:15:00',
    },
  ],
  ratingsDatasets: [
    {
      ratingsDatasetId: 'RAT-Q1-2026',
      provider: 'Sample Provider',
      period: 'Q1 2026',
      market: 'Nigeria',
      audience: 'Adults 18-45 ABC',
      mediaTypes: ['TV', 'Radio'],
      rows: 202,
      invalidRows: 0,
      duplicateKeys: 0,
      uploadedAt: '2026-08-19 14:12:00',
      status: 'Ready',
      mappingWarnings: [],
    },
    {
      ratingsDatasetId: 'RAT-APR-2026',
      provider: 'Sample Provider',
      period: 'April 2026',
      market: 'Nigeria',
      audience: 'Adults 18+',
      mediaTypes: ['TV'],
      rows: 140,
      invalidRows: 3,
      duplicateKeys: 2,
      uploadedAt: '2026-08-18 11:45:00',
      status: 'Needs Review',
      mappingWarnings: [],
    },
  ],
  uploads: [
    {
      uploadId: 'UP-001',
      projectId: 'MP-2608-A',
      brandId: null,
      fileName: 'Composite 2026.xlsx',
      kind: 'composite_report',
      mappedRows: 202,
      issueRows: 1,
      uploadedAt: '2026-08-19 15:05:00',
      mappingWarnings: [],
    },
    {
      uploadId: 'UP-002',
      projectId: 'MP-2608-A',
      brandId: 'BRAND-A',
      fileName: 'sample_brand_report.xlsx',
      kind: 'brand_report',
      mappedRows: 202,
      issueRows: 0,
      uploadedAt: '2026-08-19 15:18:00',
      mappingWarnings: [],
    },
  ],
  latestRun: {
    runId: 'RUN-001',
    projectId: 'MP-2608-A',
    totalBrands: 4,
    totalSpots: 202,
    totalGrps: 113.7,
    totalSpend: 8_420_000,
    matchedRows: 202,
    unmatchedRows: 0,
    isCurrent: true,
    generatedAt: '2026-08-19 15:28:00',
  },
  brandShares: [
    { runId: 'RUN-001', brandId: 'BRAND-A', brand: 'Brand A', totalGrps: 42.3, tvGrps: 34.1, cableTvGrps: 8.2, radioGrps: 0, sov: 37.2, spots: 64, avgRating: 0.66, totalSpend: 3_120_000, soe: 37.1, tvSpend: 2_500_000, cableTvSpend: 620_000, radioSpend: 0 },
    { runId: 'RUN-001', brandId: 'BRAND-B', brand: 'Brand B', totalGrps: 31.8, tvGrps: 20.1, cableTvGrps: 0, radioGrps: 11.7, sov: 28.0, spots: 52, avgRating: 0.61, totalSpend: 2_360_000, soe: 28.0, tvSpend: 1_800_000, cableTvSpend: 0, radioSpend: 560_000 },
    { runId: 'RUN-001', brandId: 'BRAND-C', brand: 'Brand C', totalGrps: 23.5, tvGrps: 23.5, cableTvGrps: 0, radioGrps: 0, sov: 20.7, spots: 45, avgRating: 0.52, totalSpend: 1_740_000, soe: 20.7, tvSpend: 1_740_000, cableTvSpend: 0, radioSpend: 0 },
    { runId: 'RUN-001', brandId: 'BRAND-D', brand: 'Brand D', totalGrps: 16.1, tvGrps: 9.4, cableTvGrps: 0, radioGrps: 6.7, sov: 14.1, spots: 41, avgRating: 0.39, totalSpend: 1_200_000, soe: 14.2, tvSpend: 780_000, cableTvSpend: 0, radioSpend: 420_000 },
  ],
  validationIssues: [
    {
      issueId: 'VAL-001',
      projectId: 'MP-2608-A',
      runId: null,
      severity: 'warning',
      area: 'Composite upload',
      message: 'One total row was excluded from calculation.',
      rows: 1,
    },
    {
      issueId: 'VAL-002',
      projectId: 'MP-2608-B',
      runId: null,
      severity: 'warning',
      area: 'Ratings library',
      message: 'Two duplicate rating keys need review before reuse.',
      rows: 2,
    },
  ],
};
