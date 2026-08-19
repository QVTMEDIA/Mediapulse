export type ProjectStatus = 'Setup' | 'Data Review' | 'Complete';
export type MediaType = 'TV' | 'Radio';
export type UploadKind = 'ratings' | 'brand_report' | 'composite_report';
export type ValidationSeverity = 'info' | 'warning' | 'error';

export interface Project {
  projectId: string;
  projectName: string;
  projectOwner: string;
  client: string;
  category: string;
  market: string;
  startDate: string;
  endDate: string;
  targetAudience: string;
  mediaTypes: MediaType[];
  ratingsProvider: string;
  ratingsPeriod: string;
  status: ProjectStatus;
  archived: boolean;
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
}

export interface UploadBatch {
  uploadId: string;
  projectId: string;
  fileName: string;
  kind: UploadKind;
  mappedRows: number;
  issueRows: number;
  uploadedAt: string;
}

export interface GrpRunSummary {
  runId: string;
  projectId: string;
  totalBrands: number;
  totalSpots: number;
  totalGrps: number;
  matchedRows: number;
  unmatchedRows: number;
  generatedAt: string;
}

export interface BrandShare {
  brand: string;
  totalGrps: number;
  sov: number;
  spots: number;
}

export interface ValidationIssue {
  issueId: string;
  projectId: string;
  severity: ValidationSeverity;
  area: string;
  message: string;
  rows: number;
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
    },
  ],
  uploads: [
    {
      uploadId: 'UP-001',
      projectId: 'MP-2608-A',
      fileName: 'Composite 2026.xlsx',
      kind: 'composite_report',
      mappedRows: 202,
      issueRows: 1,
      uploadedAt: '2026-08-19 15:05:00',
    },
    {
      uploadId: 'UP-002',
      projectId: 'MP-2608-A',
      fileName: 'sample_brand_report.xlsx',
      kind: 'brand_report',
      mappedRows: 202,
      issueRows: 0,
      uploadedAt: '2026-08-19 15:18:00',
    },
  ],
  latestRun: {
    runId: 'RUN-001',
    projectId: 'MP-2608-A',
    totalBrands: 4,
    totalSpots: 202,
    totalGrps: 113.7,
    matchedRows: 202,
    unmatchedRows: 0,
    generatedAt: '2026-08-19 15:28:00',
  },
  brandShares: [
    { brand: 'Brand A', totalGrps: 42.3, sov: 37.2, spots: 64 },
    { brand: 'Brand B', totalGrps: 31.8, sov: 28.0, spots: 52 },
    { brand: 'Brand C', totalGrps: 23.5, sov: 20.7, spots: 45 },
    { brand: 'Brand D', totalGrps: 16.1, sov: 14.1, spots: 41 },
  ],
  validationIssues: [
    {
      issueId: 'VAL-001',
      projectId: 'MP-2608-A',
      severity: 'warning',
      area: 'Composite upload',
      message: 'One total row was excluded from calculation.',
      rows: 1,
    },
    {
      issueId: 'VAL-002',
      projectId: 'MP-2608-B',
      severity: 'warning',
      area: 'Ratings library',
      message: 'Two duplicate rating keys need review before reuse.',
      rows: 2,
    },
  ],
};
