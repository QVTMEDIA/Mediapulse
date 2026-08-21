# Mediapulse API Contract

This contract defines the backend surface required by the Vite/React frontend, per `PRODUCT_ROADMAP.md`. Field names use camelCase for JSON. The existing Python layer (`grp_calculator.py`, `project_store.py`) can continue using snake_case internally; this is the wrapper surface described as Phase 2's "Python API service" in the roadmap.

Implementation has started in `services/api` (`app.py` still talks to `grp_calculator.py`/`project_store.py` in-process and is unaffected by this service so far — though `services/api` now imports `grp_calculator.py` directly for upload parsing, match suggestions, and the brand-rollup calculation, see `services/api/README.md`). Current status: `/api/projects`, the Ratings Library (`/api/ratings-datasets` — both JSON rows and real file upload, project attach/list/detach), `/api/projects/{projectId}/brands` (list/create/delete), `/api/projects/{projectId}/uploads` (both `brand_report` and `composite_report` kinds, list/create/delete) + `/media-activity`, `/api/mapping-templates` (list, create, suggest), `/api/projects/{projectId}/matches` + `/correct` + `/recompute`, `/api/projects/{projectId}/calculate` + `/runs` + `/runs/latest` + `/runs/{runId}/brand-shares` + `/runs/{runId}/calculations` + `/runs/{runId}/stations` + `/runs/{runId}/programmes` + `/runs/{runId}/trend`, `/api/projects/{projectId}/versions` + `/{versionId}/restore`, `/api/projects/{projectId}/exports` + `/{exportId}` + `/{exportId}/download`, `/api/projects/{projectId}/validation-issues`, and `/api/auth/*` + `/api/users` (Phase 3's real multi-user auth) are fully implemented against Postgres — that's the full Phase 1 and Phase 2 pipeline (`PRODUCT_ROADMAP.md`), upload through calculate through station/programme/trend analysis, plus data-quality visibility, real accounts, version history, the full-workbook Export Centre, and per-project data management. Every route below except `/api/auth/register` and `/api/auth/login` now requires a bearer token (`Authorization: Bearer <token>`, issued by register/login), returning `401` without one; archiving/deleting a project, restoring a version, deleting an upload or brand, and changing another user's role additionally require the caller's role to be `owner` or `admin`, returning `403` otherwise — see `services/api/README.md`'s auth section. Deleting an upload or brand additionally 409s if any of its rows were ever part of a calculated run, to protect that run's audit trail (detaching a ratings dataset carries no such restriction — see the `UploadBatch`/`Brand` notes below). The upload preview/map routes (`GET`/`POST /uploads/{uploadId}/preview` + `/map`) remain `501` stubs by design — mapping is applied automatically (auto-detect, or a saved template) rather than through a separate preview/confirm step. `xlsx_summary`/`pdf`/`csv` export formats, project version *descriptions* beyond the auto-generated one, and everything else still listed under Phase 3 in `PRODUCT_ROADMAP.md` remain unbuilt. See `services/api/README.md` for the up-to-date table.

`GET /api/projects/{projectId}/ratings-datasets` (listing a project's attached datasets) was added beyond the original route list below, as the natural read-side companion to `attach`.

## Audit Rule

Every calculated GRP row must be traceable to:

- source upload
- source row number
- normalized match key
- rating dataset
- rating row used
- calculation timestamp
- export/run ID

## Core Entities

### User

Role is global, not per-project — see the comment on the `users` table in `db/schema.sql` for why (no tenancy/workspace concept exists yet). Never carries a password or hash over the wire.

- `userId`
- `email`
- `displayName`
- `role` (`owner` | `admin` | `member`)
- `createdAt`

### AuthSession

Returned by `POST /api/auth/register` and `POST /api/auth/login`. `accessToken` is a JWT, sent back as `Authorization: Bearer <accessToken>` on every subsequent request.

- `accessToken`
- `tokenType` (always `bearer`)
- `user` (a `User`)

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
- `notes`
- `createdAt`
- `updatedAt`

`notes` is free text, matching `PRODUCT_ROADMAP.md`'s "Data stored" list for the Projects screen.

### RatingsDataset

Shared across projects via the Ratings Library — not owned by a single project.

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
- `status` (`Ready` | `Needs Review`)

`DELETE /projects/{projectId}/ratings-datasets/{ratingsDatasetId}/attach` detaches the dataset from that one project — the shared dataset (and every other project's attachment to it) is untouched, and so is anything already matched or calculated against it, since `RatingMatch`/`GrpCalculationRow` reference the actual `RatingRow`s directly, not the attachment. Any authenticated user can detach, same as attach — no owner/admin requirement, unlike deleting an upload or brand.

### RatingRow

- `ratingRowId`
- `ratingsDatasetId`
- `medium`
- `station`
- `day`
- `programme`
- `timeBand`
- `rating`
- `startTime`
- `endTime`
- `week`
- `month`

### Brand

- `brandId`
- `projectId`
- `name`
- `createdAt`

`DELETE /brands/{brandId}` (owner/admin) removes the brand and its `MediaActivityRow`s — but only the rows for *this* brand, not the whole upload they came from (a `composite_report` upload can span several brands). Returns `409` if any of those rows were ever part of a calculated run — see the audit-rule note at the top of this document.

### UploadBatch

- `uploadId`
- `projectId`
- `fileName`
- `kind` (`ratings` | `brand_report` | `composite_report`)
- `brandId` — nullable: `composite_report` uploads span more than one brand, so attribution lives on each `MediaActivityRow` instead of the upload
- `mappedRows`
- `issueRows`
- `uploadedAt`

`DELETE /uploads/{uploadId}` (owner/admin) removes the upload and all its `MediaActivityRow`s. Returns `409` if any of those rows were ever part of a calculated run — an upload that's never been calculated can always be deleted.

### MappingTemplate

- `mappingTemplateId`
- `sourceLabel` (e.g. "Media Monitoring Agency A")
- `fieldMapping` (map of standard field name to the uploaded column name that mapped to it, e.g. `{"channel": "Media Channel"}`)
- `createdAt`
- `lastUsedAt`

### MediaActivityRow

The normalized, standard-structure row produced after mapping.

- `mediaActivityId`
- `projectId`
- `brandId`
- `uploadId`
- `medium`
- `station`
- `activityDate` (renamed from `date` — matches `db/schema.sql`'s `activity_date` column; `date` reads ambiguously once this is JSON on the wire)
- `day`
- `programme`
- `timeBand`
- `spots`
- `duration`
- `adType`
- `startTime`
- `endTime`
- `campaign`
- `product`
- `sourceFile`
- `sourceRowNumber`

Implemented so far (`services/api`'s `brand_report` upload path): `mediaActivityId`, `projectId`, `brandId`, `uploadId`, `medium`, `station`, `activityDate`, `day`, `programme`, `spots`, `sourceFile`. `timeBand`, `duration`, `adType`, `startTime`, `endTime`, `campaign`, `product`, `sourceRowNumber` aren't populated yet — `grp_calculator.build_brand_report()` doesn't extract them from a spot-level report, and `build_brand_report` drops the row-number column it briefly computes internally before returning, so there's currently no cheap way to recover `sourceRowNumber` either. Revisit once a report format that actually carries that detail shows up.

### RatingMatch

- `ratingMatchId`
- `mediaActivityId`
- `matchedRatingId` (renamed from `matchedRatingRowId` — matches `db/schema.sql`'s `matched_rating_id` column end-to-end)
- `matchStatus` (`exact` | `suggested` | `unmatched` | `manual`)
- `matchConfidence` (0–1, present for `suggested`; `null` for `exact`/`unmatched`/`manual` — manual corrections don't carry a similarity score)
- `matchKey` (normalized `MEDIUM | STATION | DAY | PROGRAMME/TIME BAND`)
- `correctedAt`

Implemented so far: everything above except `correctedBy`. Real accounts exist now (Phase 3's auth), but `rating_matches.corrected_by` (and the equivalent `uploaded_by`/`triggered_by`/`generated_by` columns elsewhere in `db/schema.sql`) still aren't written to or exposed on any `*Out` schema — every mutating route knows the caller via `Depends(get_current_user)` for authorization, but nothing yet threads that id into the record it's mutating. Real, not-yet-done follow-up work, not a design gap.

**`GET /api/projects/{projectId}/matches` computes lazily rather than only reading.** On each call the endpoint fills in a `rating_matches` row for any `media_activity` row that doesn't have one yet (exact match-key lookup first, then `grp_calculator.build_unmatched_suggestions()` for a fuzzy suggestion), then returns the project's full current list. This is idempotent and never touches a row that already has a match — including manual corrections — so calling it repeatedly is safe, but it also means matches don't retroactively improve on their own if ratings are attached *after* a row was already computed as `unmatched`.

**`POST /api/projects/{projectId}/matches/recompute`** — not in this contract's original route list, added to close that gap: re-attempts exact + fuzzy matching for rows currently `unmatched` only. `exact`, `suggested`, and `manual` rows are already-decided and are never touched. Returns the project's full current match list, same shape as `GET /matches`.

**`POST /matches/{ratingMatchId}/correct` validates `matchedRatingId`** when one is given: it must be a real rating row attached to the project, or the call fails with `422`. (An earlier version accepted anything and let a bad id fail silently into "unmatched" at calculate time — closed once the frontend gained a manual rating picker, where a bad selection needs to be rejected at the moment it's made, not discovered later.)

### GrpCalculationRow

- `grpCalculationId`
- `mediaActivityId`
- `runId`
- `spots`
- `rating`
- `grp`
- `calculatedAt`

Persisted by `POST /calculate` (one row per matched `media_activity` row — unmatched rows never get one, see `services/api/app/calculations.py`). Read back via `GET /runs/{runId}/calculations` — not in this contract's original route list, added alongside `brand-shares` since the spot-level GRP screen in `PRODUCT_ROADMAP.md` section 8 needs row-by-row data, not just the per-brand aggregate. That response enriches the bare entity above with `brand` (joined name), `station`, `programme`, `day`, and `medium` from the underlying `media_activity` row, since a GRP number with no station or programme attached isn't reviewable.

### GrpRunSummary

- `runId`
- `projectId`
- `totalBrands`
- `totalSpots`
- `totalGrps`
- `matchedRows`
- `unmatchedRows`
- `isCurrent` (the run `GET .../runs/latest` returns — the newest run unless a version-history restore pinned it back to an older one)
- `generatedAt`

### BrandShare

Per-brand rollup for a run, backing the SOV chart and brand comparison screen.

- `runId`
- `brandId`
- `brand`
- `totalGrps`
- `tvGrps`
- `radioGrps`
- `sov`
- `spots`
- `avgRating`

### StationShare

Per-brand-per-station GRP rollup for a run, backing the Reports screen's Station Contribution panel (ranked across stations by summing across brands client-side).

- `runId`
- `brandId`
- `brand`
- `station`
- `totalGrps`
- `spots`

### ProgrammeShare

Per-brand-per-programme GRP rollup for a run, same shape and purpose as `StationShare` but grouped by programme.

- `runId`
- `brandId`
- `brand`
- `programme`
- `totalGrps`
- `spots`

### TrendPoint

Per-brand-per-ISO-week GRP rollup for a run, backing the Reports screen's Weekly Trend panel. `weekStart` is the Monday of the week (`date_trunc('week', activityDate)`); rows with no `activityDate` are excluded rather than bucketed under a null week.

- `runId`
- `brandId`
- `brand`
- `weekStart`
- `totalGrps`
- `spots`

### ValidationIssue

- `issueId`
- `projectId`
- `runId` — always `null` in the current implementation; see below
- `severity` (`info` | `warning` | `error`) — always `warning` today
- `area`
- `message`
- `rows`

`GET /validation-issues` is implemented, but as a computed view rather than a read of `db/schema.sql`'s `validation_issues` table (which nothing writes to yet): it synthesizes one issue per attached ratings dataset with `invalidRows`/`duplicateKeys` > 0, and one per upload with `issueRows` > 0, deriving everything from counts already tracked elsewhere. `issueId` is a stable derived string (e.g. `ratings-{datasetId}-invalid`), not a database id. These issues aren't tied to a calculation run — they're properties of the ratings/uploads themselves — hence `runId` is always `null`.

### ProjectVersion

One entry per past `GrpRunSummary` for a project — "each recalculation ... becomes a version" (`PRODUCT_ROADMAP.md`). `GET /versions` computes this on read from `grp_runs`, the same pattern as `GET /validation-issues` above, rather than a separate write path. `versionId` is the run's own id (a version and the run it represents are 1:1, so a second id would just be an alias).

- `versionId`
- `projectId`
- `runId`
- `description` (a generated one-line summary, e.g. "4 brands, 202 spots, 113.7 GRPs (198 matched, 4 unmatched)")
- `isCurrent` (whether this is the run `GET .../runs/latest` currently returns)
- `createdAt`

`POST /versions/{versionId}/restore` (`owner`/`admin` only) sets this version's run as current and every other run for the project as not-current — it does not delete, recompute, or otherwise touch any run's `GrpCalculationRow`s, so restoring an older version and then restoring back to the newest one loses nothing.

### ExportJob

- `exportId`
- `projectId`
- `runId` — nullable: a project with no calculation yet can still export (a Project-Info-only workbook); otherwise frozen to whichever run was current when the export was created, not re-resolved later, so downloading it next week reproduces the same snapshot even if a newer run (or a version restore) has since changed what `GET .../runs/latest` returns
- `format` (`xlsx_full` | `xlsx_summary` | `pdf` | `csv`) — only `xlsx_full` is implemented; `POST /exports` with any other value returns `422` naming what's missing rather than silently downgrading
- `generatedAt`
- `downloadUrl` — `GET {downloadUrl}` (i.e. `GET /api/projects/{projectId}/exports/{exportId}/download`, not in this contract's original route list below) streams the actual `.xlsx` bytes, rebuilt fresh on every call from the frozen run rather than read from stored blob storage — no object store is configured in this environment, so `exports.storage_path` (`db/schema.sql`) always stays `null`

## Routes

```text
POST   /api/auth/register
POST   /api/auth/login
GET    /api/auth/me

GET    /api/users
PATCH  /api/users/{userId}/role

GET    /api/projects
POST   /api/projects
GET    /api/projects/{projectId}
PATCH  /api/projects/{projectId}
DELETE /api/projects/{projectId}
POST   /api/projects/{projectId}/duplicate

GET    /api/ratings-datasets
POST   /api/ratings-datasets
POST   /api/ratings-datasets/upload
GET    /api/ratings-datasets/{ratingsDatasetId}/rows

POST   /api/projects/{projectId}/ratings-datasets/{ratingsDatasetId}/attach
DELETE /api/projects/{projectId}/ratings-datasets/{ratingsDatasetId}/attach
GET    /api/projects/{projectId}/ratings-datasets

GET    /api/projects/{projectId}/brands
POST   /api/projects/{projectId}/brands
DELETE /api/projects/{projectId}/brands/{brandId}

GET    /api/mapping-templates
POST   /api/mapping-templates
GET    /api/mapping-templates/suggest?sourceLabel=

GET    /api/projects/{projectId}/uploads
POST   /api/projects/{projectId}/uploads
DELETE /api/projects/{projectId}/uploads/{uploadId}
GET    /api/projects/{projectId}/uploads/{uploadId}/preview
POST   /api/projects/{projectId}/uploads/{uploadId}/map

GET    /api/projects/{projectId}/media-activity

GET    /api/projects/{projectId}/matches
POST   /api/projects/{projectId}/matches/{ratingMatchId}/correct
POST   /api/projects/{projectId}/matches/recompute

POST   /api/projects/{projectId}/calculate
GET    /api/projects/{projectId}/runs
GET    /api/projects/{projectId}/runs/latest
GET    /api/projects/{projectId}/runs/{runId}/brand-shares
GET    /api/projects/{projectId}/runs/{runId}/calculations
GET    /api/projects/{projectId}/runs/{runId}/stations
GET    /api/projects/{projectId}/runs/{runId}/programmes
GET    /api/projects/{projectId}/runs/{runId}/trend

GET    /api/projects/{projectId}/validation-issues

GET    /api/projects/{projectId}/versions
POST   /api/projects/{projectId}/versions/{versionId}/restore

GET    /api/projects/{projectId}/exports
POST   /api/projects/{projectId}/exports
GET    /api/projects/{projectId}/exports/{exportId}
GET    /api/projects/{projectId}/exports/{exportId}/download
```
