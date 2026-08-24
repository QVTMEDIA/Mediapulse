# Mediapulse API Contract

This contract defines the backend surface required by the Vite/React frontend, per `PRODUCT_ROADMAP.md`. Field names use camelCase for JSON. The existing Python layer (`grp_calculator.py`, `project_store.py`) can continue using snake_case internally; this is the wrapper surface described as Phase 2's "Python API service" in the roadmap.

Implementation has started in `services/api` (`app.py` still talks to `grp_calculator.py`/`project_store.py` in-process and is unaffected by this service so far — though `services/api` now imports `grp_calculator.py` directly for upload parsing, match suggestions, and the brand-rollup calculation, see `services/api/README.md`). Current status: `/api/projects`, the Ratings Library (`/api/ratings-datasets` — both JSON rows and real file upload, project attach/list/detach), `/api/projects/{projectId}/brands` (list/create/delete), `/api/projects/{projectId}/uploads` (both `brand_report` and `composite_report` kinds, list/create/delete) + `/media-activity`, `/api/mapping-templates` (list, create, suggest), `/api/projects/{projectId}/matches` + `/correct` + `/recompute` + `/export`, `/api/projects/{projectId}/calculate` + `/runs` + `/runs/latest` + `/runs/{runId}/brand-shares` + `/runs/{runId}/calculations` + `/runs/{runId}/stations` + `/runs/{runId}/programmes` + `/runs/{runId}/trend`, `/api/projects/{projectId}/versions` + `/{versionId}/restore`, `/api/projects/{projectId}/exports` + `/{exportId}` + `/{exportId}/download`, `/api/projects/{projectId}/validation-issues`, and `/api/auth/*` + `/api/users` (Phase 3's real multi-user auth) are fully implemented against Postgres — that's the full Phase 1 and Phase 2 pipeline (`PRODUCT_ROADMAP.md`), upload through calculate through station/programme/trend analysis, plus data-quality visibility, real accounts, version history, the full-workbook Export Centre, and per-project data management. Every route below except `/api/auth/register` and `/api/auth/login` now requires a bearer token (`Authorization: Bearer <token>`, issued by register/login), returning `401` without one; archiving/deleting a project, restoring a version, deleting an upload or brand, and changing another user's role additionally require the caller's role to be `owner` or `admin`, returning `403` otherwise — see `services/api/README.md`'s auth section. Deleting an upload or brand additionally 409s if any of its rows were ever part of a calculated run, to protect that run's audit trail (detaching a ratings dataset carries no such restriction — see the `UploadBatch`/`Brand` notes below). The upload preview/map routes (`GET`/`POST /uploads/{uploadId}/preview` + `/map`) remain `501` stubs by design — mapping is applied automatically (auto-detect, or a saved template) rather than through a separate preview/confirm step. `xlsx_summary`/`pdf`/`csv` export formats, project version *descriptions* beyond the auto-generated one, and everything else still listed under Phase 3 in `PRODUCT_ROADMAP.md` remain unbuilt. See `services/api/README.md` for the up-to-date table.

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
- `issues` — optional, up to 100 entries: `{ rowNumber, reason, medium, station, day, programme, rating }` for rows dropped during file-upload parsing and never stored. Not in this contract's original field list. Only ever present on the response to `POST /ratings-datasets/upload`; every other route that returns a `RatingsDataset` leaves it unset, since a dropped row is never persisted anywhere to look up again — `invalidRows` above is the only trace of it elsewhere.
- `mappingWarnings` — array (`[]` when there's nothing to report) of `MappingWarning`: `{ field, templateColumn, detectedColumn }`. Not in this contract's original field list. Populated only on the response to `POST /ratings-datasets/upload` (same rule as `issues`), whenever a saved mapping template (`source_label`) pinned a field to a column that disagrees with what fresh auto-detection would have picked for this specific file — a real, previously-silent failure mode: a template saved from an older/coarser file gets reused against a newer file that has a genuinely better-matching column sitting right next to the stale one, the stale template still wins (parsing succeeds, nothing errors), and the only symptom is every row later coming back unmatched. `[]` both when no template was used and when the template's column agrees with detection — never populated when the template's column is simply missing from this file (that's the pre-existing, correct fallback-to-auto-detect path, not a disagreement).

**`POST /ratings-datasets/upload`'s `ignore_saved_template` form field** (bool, default `false`) — the actionable follow-up to `mappingWarnings`: skips *applying* a saved `source_label` template to this one upload, forcing fresh auto-detection instead, without touching what's stored. `save_as_template` (unchanged) is still the only thing that overwrites an existing template — checking both together on one upload is the one-shot "fix a stale template in place" workflow. Not in this contract's original field list; identical field on `POST /projects/{projectId}/uploads` — see below.

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
- `mappingWarnings` — same shape and same "stale mapping template" meaning as `RatingsDataset.mappingWarnings` above. Populated only on the response to `POST /uploads` (this upload's own parse); `GET /uploads` (listing past uploads) always returns `[]`, since it isn't persisted anywhere to look up again.

**`POST /uploads`'s `ignore_saved_template` form field** — same meaning as `POST /ratings-datasets/upload`'s above.

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
- `timeBand` (the vendor's own daypart/time-band label, captured as-is and separate from `programme` — `''` when the file had no such column; never used for rating matching, only informational/aggregation, see `DaypartShare`)
- `spots`
- `duration`
- `adType`
- `startTime`
- `endTime`
- `campaign`
- `product`
- `cost` (media spend for this row — resolved at upload time from either a direct `Cost`/`Value` column or `Spots x Rate`, whichever the file has; `null`, not `0`, when neither was ever mapped, since "no spend column" and "confirmed zero spend" are different things. Not in this contract's original field list — added alongside `BrandShare.totalSpend`/`soe`, see that section)
- `sourceFile`
- `sourceRowNumber`

Implemented so far (`services/api`'s `brand_report` upload path): `mediaActivityId`, `projectId`, `brandId`, `uploadId`, `medium`, `station`, `activityDate`, `day`, `programme`, `spots`, `cost`, `timeBand`, `sourceFile`. `duration`, `adType`, `startTime`, `endTime`, `campaign`, `product`, `sourceRowNumber` aren't populated yet — `grp_calculator.build_brand_report()` doesn't extract them from a spot-level report, and `build_brand_report` drops the row-number column it briefly computes internally before returning, so there's currently no cheap way to recover `sourceRowNumber` either. Revisit once a report format that actually carries that detail shows up.

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

**`POST /matches/jobs` + `GET /matches/jobs/{jobId}` (`MatchJobOut`) gained `total`/`processed` integer fields** — not in this contract's original schema. Real progress for recompute jobs only: `total` is set once, up front, to the number of currently-`unmatched` rows being retried; `processed` advances by one per row visited (whether or not it ends up matched), so a polling client can render `processed / total` as a real percentage instead of an indeterminate spinner — the actual bottleneck on a slow/cold-started backend is the per-row persistence loop this now instruments. `mode=ensure` jobs (a single atomic repository call with no per-row loop up in `app/match_jobs.py` to report from) always report `0`/`0`.

`mode=recompute_exact` is a faster job variant for retrying currently-`unmatched` rows against exact station/day/time-band keys only. It deliberately skips fuzzy suggestions; use `mode=recompute` when a slower fuzzy review pass is needed.

**`POST /matches/{ratingMatchId}/correct` validates `matchedRatingId`** when one is given: it must be a real rating row attached to the project, or the call fails with `422`. (An earlier version accepted anything and let a bad id fail silently into "unmatched" at calculate time — closed once the frontend gained a manual rating picker, where a bad selection needs to be rejected at the moment it's made, not discovered later.)

**`GET /api/projects/{projectId}/matches/export`** — not in this contract's original route list, added so the Matches screen can offer a "Download match report" button. Returns a `text/csv` attachment, one row per `media_activity` row with the media spend fields (Brand/Medium/Station/Day/Programme/Time Band/Spots/Cost) and the matched rating's own fields (Station/Day/Programme/Time Band/Rating) side by side, plus Match Status/Confidence/Corrected At. Programme and Time Band are separate columns on both sides (matching `MediaActivityRowOut`/`RatingRowOut`'s own field split — Time Band is the vendor's own daypart/time-band label, blank on a file that never had one). Computes lazily first (same `ensure_matches_computed` call `GET /matches` makes), so it never needs a prior `GET /matches` call to have "warmed" the match state. Deliberately plain CSV, not part of the Export Centre's run-scoped `.xlsx` workbook (`/exports`) — matching is project-wide live state, not frozen per calculated run, so it needs no run (or any calculation at all) to exist.

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
- `totalSpend` (sum of resolved `MediaActivityRow.cost` across every activity row in this run, matched or not — see `BrandShare.totalSpend` below for why this differs from `totalGrps`, which only counts matched rows. Not in this contract's original field list.)
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
- `tvGrps` — terrestrial/generic TV, same meaning it always had
- `cableTvGrps` — a newer, additive bucket (DStv/GOtv/satellite/pay-TV) — see `grp_calculator.normalize_medium_type`. `totalGrps = tvGrps + cableTvGrps + radioGrps`. Not in this contract's original field list.
- `radioGrps`
- `sov`
- `spots`
- `avgRating`
- `totalSpend` — Share of Expenditure's numerator: this brand's resolved spend, summed across **every** `media_activity` row belonging to it regardless of match status. Not in this contract's original field list, added for the Media Spend/SOE feature.
- `soe` — `totalSpend / (sum of every brand's totalSpend in this run) * 100`. Deliberately computed from all rows, not just matched ones, unlike `sov`: money was spent on a spot whether or not a rating was ever found for it, so a project with zero matched rows can still show a fully populated SOE breakdown (it just also shows `sov: 0` for everyone, since GRP genuinely doesn't exist yet). `0` when no brand in the run has any resolved spend at all.
- `tvSpend`, `cableTvSpend`, `radioSpend` — spend broken out by medium, same shape and computation as `tvGrps`/`cableTvGrps`/`radioGrps` but for `totalSpend` instead of `totalGrps` — backs the Spend Intelligence screen's medium breakdown. Not in this contract's original field list. May not sum exactly to `totalSpend`: a row whose medium doesn't canonicalize to TV/Cable TV/Radio isn't counted in any of the three, same silent-drop behavior the GRP medium split already has.

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

### DaypartShare

Per-brand-per-daypart GRP rollup for a run, same shape and purpose as `StationShare`/`ProgrammeShare` but grouped by `timeBand` — the vendor's own daypart/time-band label from the source file, not a canonical bucket this app defines (`''` for rows with no such column mapped). Not in this contract's original field list.

- `runId`
- `brandId`
- `brand`
- `timeBand`
- `totalGrps`
- `spots`

### SpotEfficiency

Per-brand-per-station GRP-per-spot efficiency for a run, backing the Reports screen's Spot Efficiency panel (`GET /runs/{runId}/spot-efficiency`) — PRODUCT_ROADMAP.md's Overview "spot-volume-vs-GRP" view. Computed on every read from the same per-station aggregate `StationShare` uses, not stored: `isWeak` is `true` when `grpPerSpot` is under half the run's category-average GRP-per-spot, at 5 or more spots. Not in this contract's original field list.

- `runId`
- `brandId`
- `brand`
- `station`
- `spots`
- `totalGrps`
- `grpPerSpot`
- `isWeak`

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
POST   /api/projects/{projectId}/matches/jobs?mode=ensure|recompute|recompute_exact
GET    /api/projects/{projectId}/matches/jobs/{jobId}
POST   /api/projects/{projectId}/matches/{ratingMatchId}/correct
POST   /api/projects/{projectId}/matches/recompute
GET    /api/projects/{projectId}/matches/export

POST   /api/projects/{projectId}/calculate
GET    /api/projects/{projectId}/runs
GET    /api/projects/{projectId}/runs/latest
GET    /api/projects/{projectId}/runs/{runId}/brand-shares
GET    /api/projects/{projectId}/runs/{runId}/calculations
GET    /api/projects/{projectId}/runs/{runId}/stations
GET    /api/projects/{projectId}/runs/{runId}/programmes
GET    /api/projects/{projectId}/runs/{runId}/dayparts
GET    /api/projects/{projectId}/runs/{runId}/spot-efficiency
GET    /api/projects/{projectId}/runs/{runId}/trend

GET    /api/projects/{projectId}/validation-issues

GET    /api/projects/{projectId}/versions
POST   /api/projects/{projectId}/versions/{versionId}/restore

GET    /api/projects/{projectId}/exports
POST   /api/projects/{projectId}/exports
GET    /api/projects/{projectId}/exports/{exportId}
GET    /api/projects/{projectId}/exports/{exportId}/download
```
