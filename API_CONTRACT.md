# Mediapulse API Contract

This contract defines the first backend surface required by the Vite/React frontend. Field names use camelCase for JSON. The existing Python layer can continue using snake_case internally.

## Core Entities

### Project

- `projectId`
- `projectName`
- `projectOwner`
- `client`
- `category`
- `market`
- `startDate`
- `endDate`
- `targetAudience`
- `mediaTypes`
- `ratingsProvider`
- `ratingsPeriod`
- `status`
- `archived`
- `createdAt`
- `updatedAt`

### RatingsDataset

- `ratingsDatasetId`
- `provider`
- `period`
- `market`
- `audience`
- `mediaTypes`
- `rows`
- `invalidRows`
- `duplicateKeys`
- `uploadedAt`
- `status`

### UploadBatch

- `uploadId`
- `projectId`
- `fileName`
- `kind`
- `mappedRows`
- `issueRows`
- `uploadedAt`

### GrpRunSummary

- `runId`
- `projectId`
- `totalBrands`
- `totalSpots`
- `totalGrps`
- `matchedRows`
- `unmatchedRows`
- `generatedAt`

### ValidationIssue

- `issueId`
- `projectId`
- `severity`
- `area`
- `message`
- `rows`

## First Routes

```text
GET    /api/projects
POST   /api/projects
GET    /api/projects/{projectId}
PATCH  /api/projects/{projectId}
DELETE /api/projects/{projectId}

GET    /api/ratings-datasets
POST   /api/ratings-datasets
GET    /api/projects/{projectId}/uploads
POST   /api/projects/{projectId}/uploads

POST   /api/projects/{projectId}/calculate
GET    /api/projects/{projectId}/runs/latest
GET    /api/projects/{projectId}/validation-issues
GET    /api/projects/{projectId}/exports/{runId}
```

## Audit Rule

Every calculated GRP row must be traceable to:

- source upload
- source row number
- normalized match key
- rating dataset
- rating row used
- calculation timestamp
- export/run ID
