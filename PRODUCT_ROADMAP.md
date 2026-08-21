# Mediapulse Product Roadmap

Mediapulse should evolve from an upload-and-calculate utility into a project-based media intelligence platform.

Core principle:

One project equals one campaign or category analysis workspace.

Every final GRP must remain auditable back to the individual media placement and the exact rating used: source upload, source row number, normalized match key, rating dataset, rating row used, calculation timestamp, and export/run ID.

## Status legend

Used throughout this document to keep the roadmap honest against the current codebase (`app.py`, `grp_calculator.py`, `project_store.py`, `packages/web`):

- **Done** — implemented and covered by tests or in active use.
- **Partial** — implemented in-session (Streamlit `session_state`) but not yet persisted, or implemented for one workflow but not generalized.
- **Planned** — not started.

## Current Product Spine

- Project setup metadata — **Done** (`app.py` project form, `project_store.py`)
- Projects home: create, open, duplicate, archive, delete, export, import — **Done**
- Local SQLite project **metadata** store — **Done**; ratings, uploads, matches, and calculations are **not** persisted per project (see "Known Gap" below)
- Composite report workflow — **Done**
- Separate Ratings + Brand Reports workflow — **Done**
- Upload interpretation and column mapping review — **Done** (manual, per-upload; no saved templates yet)
- GRP and SOV calculations — **Done** (`grp_calculator.py`)
- Validation tables and unmatched row suggestions, including fuzzy match scoring — **Done** (`build_unmatched_suggestions`, `text_similarity`, `suggestion_confidence`)
- Excel export with project, run, validation, summary, audit, and issue sheets — **Done**
- Basic password protection for shared deployments — **Done**
- Postgres schema (`db/schema.sql`) implementing the data model below — **Done**
- Python API service (`services/api`) — **Partial**: every backend piece of Phase 1 and Phase 2 is done against Postgres (`/api/projects`, the Ratings Library — JSON rows or real file upload, `/api/projects/{id}/brands`, `brand_report` and `composite_report` upload ingestion, saved mapping templates, matching with fuzzy suggestions plus manual correction/recompute, GRP calculation + spot-level read-back, station/programme/trend aggregation, `/api/projects/{id}/validation-issues`), plus three Phase 3 pieces: real multi-user auth and role-based permissions (`/api/auth/*`, `/api/users`), project version history + restore (`/api/projects/{id}/versions`), and the full-Excel-workbook Export Centre (`/api/projects/{id}/exports`); only upload preview/re-map (a deliberate gap) and Phase 3's still-Planned deployment/scheduling/provider-connection items remain
- Media spend and Share of Expenditure (SOE) — **Done**: uploads resolve a per-row `cost` (direct `Cost` column, or `Spots x Rate`); `grp_runs`/`brand_shares` carry `total_spend`/`soe` alongside GRP/SOV, computed from every activity row regardless of match status (see section 6 of this document). Threaded through parsing, both repository backends, the calculation engine, the run/brand-share API schemas, the Export Centre workbook, and `packages/web`'s Overview/Reports screens.
- Vite/React frontend (`packages/web`) — **Partial**: the whole app now sits behind a real sign-in/create-account screen, with eight real screens wired to `services/api` — Projects (list/search/create/archive, Overview KPIs, Brand SOV, brand/composite upload form with mapping-template reuse, Calculate, Version History with restore, a Project Settings panel to edit every project field and delete/detach uploads/brands/ratings), Ratings (upload — with the same mapping-template reuse — or attach from the library), Matches (review and confirm/reject fuzzy matches, manual assignment, recompute), Activity (spot-level GRP audit trail), Reports (station contribution, programme contribution, weekly trend, brand-vs-brand comparison), Quality (validation issues), Settings (your account, plus team/role management for owner/admin), Exports (generate and download the full Excel workbook) — each with real loading/error/empty states, no sample data. A project can go from empty to a reviewed, calculated, analyzed, exported GRP entirely through the browser, as more than one real account.

### Former gap, now closed: no data persistence beyond project metadata

The Streamlit app (`app.py`) still keeps ratings, uploads, matches, and calculations only in `session_state` for one browser session — that hasn't changed, and isn't going to; it's the frozen reference product, not where new work lands. But the gap this note used to describe — a *product* with nowhere to persist any of that — is closed: `services/api` has real Postgres persistence for the entire pipeline (ratings datasets, brands, `media_activity`, `rating_matches`, `grp_runs`/`grp_calculations`/`brand_shares`), and the React frontend now reads and writes all of it through five real screens (Projects, Ratings, Matches, Activity, Quality — see Phase 1 below). A project made in the browser survives a refresh, because it was never only in the browser to begin with.

## Screen Map

### Global (outside a project)

| Screen | Purpose | Status |
| --- | --- | --- |
| Home / Projects | View, create, duplicate, archive, reopen, export/import analyses | Done |
| Project Setup | Define campaign/category, dates, market, medium, target audience | Done |

### Inside a project

Navigation stays flat and product-facing — nine sections, each may contain sub-views:

| Section | Contains | Status |
| --- | --- | --- |
| Overview | Executive GRP/SOV dashboard, KPI cards, GRP-by-brand chart, SOV chart, TV vs Radio split, spot-volume-vs-GRP view | Partial — the KPI cards and a GRP/SOV list (not yet a chart) are live in `packages/web`'s Projects panel against `GET /runs/latest` + `/brand-shares`, with a "Calculate" button. TV vs Radio split is now **Done**: each brand's bar splits into a TV segment and a Radio segment proportional to `tvGrps`/`radioGrps`, with a legend, for any project with mixed-media brands — a single-medium brand just shows one solid color. spot-volume-vs-GRP (flagging brands buying weak inventory at high volume) has no backing query or agreed threshold yet and remains **Planned**; this also isn't a dedicated Overview screen yet, just the existing panel |
| Brands | Brand detail (GRP/SOV/spots by station, programme, day, week, daypart), brand-vs-brand comparison | Partial — brand-vs-brand comparison (GRP, SOV, spots, avg rating, TV/Radio split) is live in `packages/web`'s Reports screen against `GET /runs/{runId}/brand-shares`. Per-brand drill-down is now **Partial** too: a "Brand detail" selector on the Reports screen scopes Station Contribution, Programme Contribution, and Weekly Trend to one brand's own numbers (reusing the same station/programme/trend data already fetched, filtered client-side — no new endpoint needed). Spots by day and by daypart specifically remain **Planned** — day isn't aggregated anywhere yet (only visible per-row on the Activity screen), and daypart is blocked on upload data that isn't captured (see the Programmes row below) |
| Stations | Station contribution by brand, station GRP ranking | Done — live in `packages/web`'s Reports screen (`GET /runs/{runId}/stations`): GRP ranked across all stations, aggregated from the per-brand rows the API returns |
| Programmes | Programme and daypart contribution, top placements | Partial — programme contribution is live in `packages/web`'s Reports screen (`GET /runs/{runId}/programmes`), GRP ranked across all programmes. Daypart contribution and a distinct "top placements" view are **Planned** |
| Activity | Spot-level media report (normalized), GRP Calculation screen (spots × rating, transparent per row) | Partial — live in `packages/web` (`GET /runs/{runId}/calculations`): every matched row, with brand/station/programme/day/medium/spots/rating/GRP. `GET /media-activity` (all activity, not just matched) exists but the screen only shows the calculated view so far |
| Data Quality | Missing ratings, unknown stations/programmes, duplicates, zero spots, invalid dates, unmatched time bands | Partial — live in `packages/web` (`GET /validation-issues`): missing-rating and duplicate-key counts. "Unknown stations/programmes", "zero spots", "invalid dates", "unmatched time bands" as distinct categories, and any fix-in-place action, are **Planned** |
| Ratings | Ratings Database for this project, plus access to the shared Ratings Library | Done — live in `packages/web`: upload a spreadsheet (parsed the same way brand reports are) or attach an existing dataset from the shared library, without leaving the project |
| Exports | Export Centre: full workbook, executive summary, PDF/presentation, CSV | Partial — full Excel workbook is **Done** and live in `packages/web` (`GET`/`POST /api/projects/{projectId}/exports` + `/{exportId}/download`), covering all 8 sheets in the "Export workbook structure" below. Executive-summary Excel, PDF/presentation, and CSV formats remain **Planned** — `POST /exports` already rejects any `format` other than `xlsx_full` with a 422 naming what's missing, rather than silently ignoring the field |
| Project Settings | Edit project assumptions, manage data, notes | Done — a "Project Settings" panel (the wrench icon in the Projects toolbar) edits every `Project` field (name, owner, client, category, market, dates, audience, media types, ratings provider/period, status, notes via `PATCH /api/projects/{projectId}`) and lists uploads/brands/attached ratings datasets with delete/detach actions. Not to be confused with the sidebar's global **Settings** nav item, which is account/team management (Phase 3) |

Two workflow screens sit between Ratings/Activity and Overview and are visited once per data refresh rather than being permanent nav items:

| Screen | Purpose | Status |
| --- | --- | --- |
| Data Mapping | Map uploaded columns to standard fields; auto-suggest; save as reusable template per source | Done — auto-suggest (`detect_column`) plus saved mapping templates (`POST`/`GET /api/mapping-templates`): a "Source label" field and "Remember this mapping" checkbox on both the media-report and ratings upload forms in `packages/web`; a known label auto-applies its saved column mapping (falling back to auto-detect per field if a saved column no longer exists in a given file), and an unrecognized label with the checkbox on saves the mapping actually used |
| Match & Validation | Review exact/suggested/unmatched rows before calculating; manually correct and remember corrections | Done — live in `packages/web`: exact/suggested/unmatched/manual rows grouped and counted; Confirm/Reject on suggested matches; a rating picker to manually assign an `unmatched` row to any of the project's attached ratings; a Recompute action that retries `unmatched` rows after new ratings are attached. All persisted as `match_status='manual'` (or re-evaluated in place for recompute), never silently re-suggested |

## 1. Home / Projects

Project cards show status, brand count, TV/Radio/Total GRPs (once calculated), unmatched-spot count, and last-updated date.

Actions: create, open, duplicate, rename, archive, delete, export, search.

Stored per project: project ID, name, client, category, market, start/end date, target audience, media included, owner, created/updated timestamps, status, notes.

## 2. Project Setup

Required: project name, category, market, analysis period (start/end date), target audience, media types (TV, Radio; Digital/OOH/Print planned).

Optional assumptions: client, target universe, geography, ratings provider, ratings period, currency, campaign benchmark.

Audience definition matters because ratings should ideally correspond to the same audience the campaign is planned against.

## 3. Ratings Database and Ratings Library

**Per-project ratings table** (standard structure): Medium, Station, Day, Programme/Time Band, Rating. Optional: Market, Audience, Programme name, Start time, End time, Week, Month, Rating period, Source.

**Ratings Library:** ratings should not be locked to one project. A shared library (e.g. "Nigeria TV Ratings — Q1 2026") lets a new project either reuse an existing dataset or upload a new one, instead of re-uploading the same ratings for every brand/category analysis run against the same wave. The backing API (`/api/ratings-datasets` — JSON rows or a real spreadsheet upload, project attach/list) is **Done**, and the Ratings screen in `packages/web` is **Done**: upload a file (attached to the active project automatically) or attach an existing dataset from the library.

## 4. Media Reports and Standard Structure

Users upload one or more brand/competitor files per project, each tagged with brand name, medium, and (optionally) report period.

All uploads are normalized to one internal structure — Brand, Medium, Station, Date, Day, Programme/Time Band, Spots — with optional Duration, Ad type, Start/End time, Campaign, Product, Source filename, and (new) Cost.

**Media spend:** an uploaded row's cost resolves from either a direct `Cost`/`Value` column (a real vendor file, per a sample the user shared, commonly reports a flat per-spot `Rate` this way already totaled — see below) or `Spots x Rate` when only a per-spot rate is present; direct `Cost` wins when both exist. `null`, not `0`, when neither is ever mapped — same "no data" vs "confirmed zero" convention as unmatched GRP rows. This feeds Share of Expenditure (SOE) — see section 6.

**API status:** `POST /api/projects/{projectId}/uploads` is **Done** for both `kind=brand_report` and `kind=composite_report` — real multipart parsing via `grp_calculator.py` (header inference, column-synonym detection, `.xlsm`/size/row-limit guards). `brand_report` writes straight into `media_activity` under the one brand the upload is tagged to; `composite_report` reads a Brand column from the file itself, resolves or creates a brand per distinct name found (`get_or_create_brand`, an atomic Postgres upsert), and attributes each row to its own brand — the upload record's `brandId` is `null` for this kind since it spans more than one brand. Ratings-file upload (`POST /api/ratings-datasets/upload`) was already **Done** in Phase 1. The frontend upload form (`packages/web`, in the Projects panel toolbar) now has a report-type selector that switches between the two: `brand_report` shows the brand picker, `composite_report` hides it and uploads without one.

## 5. Column Mapping

Different sources use different column names for the same field (e.g. "Station" / "Channel" / "Media House"). The app already auto-suggests a mapping per upload (`detect_column`). **Done:** a confirmed mapping can be saved as a named template per source (`mapping_templates` table, `{logical_field: uploaded_column_name}`) via `POST /api/mapping-templates`, `GET /api/mapping-templates`, and `GET /api/mapping-templates/suggest?sourceLabel=`; both the media-report and ratings upload endpoints accept a `source_label` and `save_as_template` flag and auto-apply a matching saved template on future uploads, falling back to auto-detection field-by-field if a saved column name no longer exists in a given file. The upload forms in `packages/web` expose this as a "Source label" text field (with autocomplete against previously-seen labels) and a "Remember this mapping" checkbox.

## 6. Matching Engine

Primary key: **Medium + Station + Day + Programme/Time Band**, normalized (trimmed, uppercased, day names to 3-letter codes) — implemented in `grp_calculator.canon`/`make_key`.

Row GRP = Spots × Matched Rating. Brand GRP = sum of row GRPs. Category GRP = sum of brand GRPs. SOV = Brand GRP ÷ Category GRP.

**Share of Expenditure (SOE):** Brand Spend = sum of resolved `Cost` (section 4) across every one of the brand's `media_activity` rows — deliberately **all** rows, matched or not, unlike GRP. Category Spend = sum of every brand's spend. SOE = Brand Spend ÷ Category Spend. This means SOE and SOV can diverge sharply, or even show a fully populated SOE breakdown for a project with zero matched rows (SOV all 0%, SOE not) — money was spent whether or not a rating was ever found for the spot. **Done**, computed in `services/api/app/calculations.py`'s `compute_run()` and persisted on `grp_runs.total_spend` and `brand_shares.total_spend`/`soe`.

### Match confidence tiers

| Tier | Meaning | Status |
| --- | --- | --- |
| Exact | Normalized key matches a rating row exactly — 100% confidence | Done, persisted (`rating_matches` via `GET /api/projects/{projectId}/matches`) |
| Suggested | Close text match (e.g. "AIT Lagos" vs "AIT") surfaced with a confidence score | Done, persisted — same `build_unmatched_suggestions()` logic, now called from `services/api` against real `media_activity`/`ratings` rows instead of only in-session DataFrames |
| Unmatched | No reliable rating found; row is flagged, never silently assigned a rating | Done, persisted |

Manually corrected matches are remembered: `POST /api/projects/{projectId}/matches/{ratingMatchId}/correct` sets `match_status='manual'` on that row permanently, so it's never silently recomputed — and now validates that the given rating actually belongs to the project (`422` otherwise; a real gap when this was first shipped, since a bad id used to fail silently at calculate time instead). The Matches screen in `packages/web` is **Done**: confirm/reject a `suggested` row, manually assign a specific rating to an `unmatched` row via a picker, or `POST /matches/recompute` to retry all `unmatched` rows after new ratings are attached (never touches `exact`/`suggested`/`manual` rows).

## 7. Match & Validation Screen

Headline: total spots, matched count, unmatched count, match rate %. Review table lists brand, station, day, programme, match status, and rating, with inline correction for suggested/unmatched rows.

## 8. GRP Calculation Screen

Transparent per-row table: Brand, Station, Programme, Spots, Rating, GRP — so every calculated number traces back to its inputs, per the audit rule at the top of this document.

**API status:** `POST /api/projects/{projectId}/calculate` is **Done** — Row GRP = Spots × Rating, persisted per matched row in `grp_calculations` (unmatched rows are excluded from that table on purpose, not zeroed — see `services/api/README.md`). `GET /runs/{runId}/calculations` (**Done**) reads it back out row-by-row, enriched with brand/station/programme/day/medium — and the Activity screen in `packages/web` (**Done**) renders exactly that table.

## 9. Dashboards

- **Overview:** KPI cards (Total Category GRPs, Total Spots, Brands, Matched Activity %, Leading Brand, Leading Brand SOV, Total Spend), GRP-by-brand ranking chart, SOV chart (donut or horizontal bar), TV vs Radio stacked view for mixed-media projects, spot-volume-vs-GRP view (flags brands buying weak inventory at high volume).
- **Brands:** per-brand detail (GRP, SOV, spend, SOE, spots, TV/Radio split, GRPs by station/programme/day/week/daypart, top placements) and a brand-vs-brand comparison table (GRPs, SOV, spend, SOE, spots, average rating, TV/Radio GRPs side by side).
- **Stations:** GRP contribution by station, per brand and overall.
- **Programmes:** GRP contribution by programme and daypart (prime time, morning, afternoon, evening, late night; or by programme genre).
- **Timeline/Trend:** weekly or monthly GRPs by brand where dates are available, to reveal launch bursts, sustained campaigns, and competitor silence.

The Overview KPIs and a GRP/SOV list are live (see the Screen Map row above), now with the TV/Radio split rendered as a two-color segmented bar rather than just numbers in the caption — still a plain list, not a chart, and not a dedicated screen. Stations, Programmes, Timeline/Trend, and brand-vs-brand comparison are **Done**, live in a new **Reports** screen in `packages/web`: `GET /runs/{runId}/stations` and `/programmes` (both querying the `grp_by_station`/`grp_by_programme` Postgres views, or an equivalent grouped aggregation for the in-memory test backend) rank GRP contribution across all stations/programmes; `GET /runs/{runId}/trend` buckets matched activity by ISO week (`date_trunc('week', activity_date)`) per brand; brand-vs-brand comparison reuses the existing `brand-shares` data already fetched for Overview, letting the user pick any two brands for a side-by-side GRP/SOV/spots/avg-rating/TV-Radio-split table. A "Brand detail" selector on the same screen now scopes Station/Programme/Trend to one brand — the per-brand drill-down piece of the Brands screen row above, built entirely client-side over data these panels already fetch. A single brand's GRPs by day/week specifically, and daypart bucketing for Programmes, remain **Planned** — day/daypart aren't aggregated by any endpoint yet, only visible per-row on Activity.

## 10. Data Quality Screen

Dedicated triage view for: missing ratings, unknown stations, unknown programmes, duplicate rows, zero spots, invalid dates, unmatched time bands — with counts and direct fix actions, not just a validation summary.

**API status:** `GET /api/projects/{projectId}/validation-issues` is **Done** — computed on read from `ratings-datasets`' invalid/duplicate counts and `uploads`' issue-row counts, not a persisted issue log (`db/schema.sql`'s `validation_issues` table is unused). Covers "missing ratings" and "duplicate rows" today; "unknown stations/programmes", "zero spots", "invalid dates", and "unmatched time bands" as distinct categories, plus any fix-in-place action, are **Planned**. The Quality screen in `packages/web` is **Done** for what the API currently covers.

## 11. Saved Project Structure and Version History

Each project should retain six datasets: project metadata, ratings dataset(s) used, uploaded reports (originals), normalized media data, match table, calculation results. **Planned**, gated on the persistence layer.

Version history (**Planned**): each recalculation (new brand added, ratings updated, mapping corrected) becomes a version with a timestamp; users can see "last recalculated" and restore a prior version.

## 12. Export Centre

Outputs: full Excel workbook, executive-summary Excel, PDF/presentation report, CSV. Currently only the full Excel workbook exists — now via `services/api` (`app/exports.py`), not only the Streamlit app's version.

### Export workbook structure

1. Project Info / Executive Summary (now includes Total Spend)
2. GRP & SOV (now includes Spend, SOE %)
3. Brand Comparison (now includes Spend, SOE %)
4. Station Performance
5. Programme Performance
6. Spot-Level Calculations
7. Unmatched Records
8. Ratings Used

**API status:** `POST /api/projects/{projectId}/exports` (**Done**) records which run an export is for — frozen at creation time, not re-resolved later, so a project's export is a point-in-time artifact even if a newer calculation or a version-history restore later changes what `GET .../runs/latest` returns. The workbook itself isn't built until `GET /exports/{exportId}/download` (**Done**, not in `API_CONTRACT.md`'s original route list, which only specified a `downloadUrl` field) is actually called, and is rebuilt fresh on every download rather than read from stored blob storage — `exports.storage_path` (`db/schema.sql`) stays `null` because no object store is configured in this environment; the rebuild is safe because `grp_calculations`/`brand_shares`/the station+programme views are immutable per run. All 8 sheets above are populated. Only `xlsx_full` is accepted; `xlsx_summary`/`pdf`/`csv` return a `422` naming what's not built rather than silently downgrading to Excel. `packages/web`'s Export Centre screen generates and downloads through this pipeline — the download itself is fetched with the caller's bearer token and handed to the browser as a `blob:` URL, since a plain link can't carry an `Authorization` header.

## 13. Complete User Flow

Login → Projects → Create Project → enter project/category details → select or upload ratings → app validates ratings → upload competitor media reports → assign brands → app detects columns → user confirms mapping → app standardizes data → app matches spots with ratings → review unmatched records → user accepts/fixes suggested matches → calculate GRPs → app generates brand GRPs, category GRPs, SOV → dashboard opens → user explores brand/station/programme insights → export → project is saved for future updates.

## Recommended Data Model

Future persistent storage (Postgres/Supabase, per `FRONTEND_MIGRATION.md`) should separate the tables below. The executable version of this schema, with indexes, generated match-key columns, and station/programme rollup views, lives in `db/schema.sql` (see `db/README.md` for the table-by-table rationale and the migration path off SQLite).

| Table | Key fields |
| --- | --- |
| `users` | id, email, role |
| `projects` | id, name, client, category, market, dates, audience, media_types, owner, status, notes |
| `ratings_datasets` | id, provider, period, market, audience, media_types, uploaded_at, status (shared across projects via the Ratings Library) |
| `ratings` | id, ratings_dataset_id, medium, station, day, programme, time_band, rating, start_time, end_time, week, month |
| `brands` | id, project_id, name |
| `uploads` | id, project_id, file_name, kind, uploaded_at, mapped_rows, issue_rows |
| `mapping_templates` | id, source_label, field_mapping_json, last_used_at |
| `media_activity` | id, project_id, brand_id, upload_id, medium, station, date, day, programme, time_band, spots, duration, ad_type, start_time, end_time, campaign, product, source_file |
| `rating_matches` | id, media_activity_id, matched_rating_id, match_status (exact/suggested/unmatched/manual), match_confidence |
| `grp_calculations` | id, media_activity_id, spots, rating, grp, run_id |
| `project_versions` | id, project_id, created_at, description, run_id |
| `exports` | id, project_id, run_id, format, generated_at |

## Phased Delivery

The build should not attempt everything at once. Phase boundaries below account for what already exists, to avoid re-scoping already-built logic as "future work." This section is kept current as work lands — see `CHANGELOG.md` for the session-by-session detail behind each status change.

### Phase 1 — Core pipeline: foundation, API, and first UI — **Complete**

- Postgres schema (`db/schema.sql`) for the full data model
- Python API service (`services/api`), Docker/CI-wired, covering the entire pipeline: `/api/projects` (full CRUD), `/api/projects/{id}/brands`, the Ratings Library (`/api/ratings-datasets` + project attach/list — JSON rows or a real spreadsheet upload), `brand_report` upload ingestion (real multipart parsing via `grp_calculator.py`), matching (`/api/projects/{id}/matches` + manual correct — exact key lookup plus `grp_calculator`'s fuzzy suggestion engine), GRP calculation (`/api/projects/{id}/calculate` + `/runs` + `/runs/latest` + `/runs/{runId}/brand-shares` + `/runs/{runId}/calculations`), and `/api/projects/{id}/validation-issues`
- The full upload → match → calculate pipeline is provably correct end to end (97 automated tests across both services), reusing `grp_calculator.py` throughout rather than reimplementing its parsing/matching/aggregation logic
- Vite/React frontend (`packages/web`), one screen per stage of the pipeline: **Projects** (list/search/create/archive, Overview KPIs, Brand SOV, brand + upload form, Calculate), **Ratings** (upload a spreadsheet or attach an existing dataset from the library), **Matches** (review fuzzy-matched spots, confirm or reject), **Activity** (every calculated row, spot-level, with brand/station/programme/rating/GRP), **Quality** (missing ratings, duplicate keys, skipped upload rows). A project can go from **empty to a reviewed, calculated GRP entirely through the browser** — upload activity, upload or attach ratings, review matches, calculate, and audit the result, with no API client needed anywhere in that path.
- Streamlit app (`app.py`) remains the deployed, feature-complete reference product, untouched by any of the above: project setup/list/manifest import-export, ratings + brand-report upload, column mapping, exact + fuzzy matching, GRP/SOV calculation, Excel export, password-gated access

### Phase 2 — Intelligence & breadth — **Complete**

- Manual mismatch correction with memory — **Done** (shipped as a Phase 1 gap-fix): a rating picker for `unmatched` rows, `POST /matches/recompute` to retry after new ratings are attached, persisted as `match_status='manual'` so it's never re-suggested.
- `composite_report` upload kind — **Done**: multi-brand-per-file, auto-detecting a Brand column, resolving/creating a brand per distinct name (`get_or_create_brand`), nullable upload-level `brandId` since attribution lives on each `media_activity` row instead. `packages/web`'s upload form has a report-type selector that switches between `brand_report` and `composite_report`.
- Saved mapping templates by report source, applied automatically on future uploads — **Done**: `mapping_templates` table + `POST`/`GET /api/mapping-templates` + `GET /api/mapping-templates/suggest`, wired into both the media-report and ratings upload endpoints, with a "Source label" field and "Remember this mapping" checkbox on both upload forms in `packages/web` (autocompleting against previously-seen labels).
- Station analysis, Programme analysis, weekly trend view — **Done**: `GET /runs/{runId}/stations`, `/programmes`, and `/trend`, each new aggregation routes over `grp_calculations`/`media_activity` (not just a UI on top of what existed), rendered in a new Reports screen in `packages/web`.
- Brand-vs-brand comparison screen — **Done**: live in the same Reports screen, reusing the existing brand-shares data to compare any two brands' GRP, SOV, spots, average rating, and TV/Radio split side by side.
- A real correctness bug found and fixed while building this phase: `grp_calculator.derive_day()` (and the API's own `_clean_date()`) silently mis-parsed ISO-formatted dates (`YYYY-MM-DD`) whenever pandas' `dayfirst=True` swapped an unambiguous day/month pair — e.g. "2026-01-05" read as May 1st instead of January 5th, which would have produced a wrong derived weekday, a wrong match key, and a wrong/missing rating match for any upload whose Date column was ISO-formatted with no separate Day column. Fixed by trying strict ISO parsing first in both places, with a regression test added to `tests/test_grp_calculator.py`.

### Phase 3 — Enterprise — In progress

- **Real multi-user authentication and role-based permissions** — **Done**: `POST /api/auth/register` (the first account on a fresh deployment becomes `owner`; everyone after starts as `member`), `POST /api/auth/login`, `GET /api/auth/me` — password hashing is PBKDF2-HMAC-SHA256 (`services/api/app/security.py`, stdlib only, no compiled dependency), tokens are real JWTs (`PyJWT`) so a future Supabase Auth migration can reuse the same shape. Every route except register/login now requires a valid bearer token (`Depends(get_current_user)`, applied at the router level so a new route can't ship unauthenticated by accident); archiving/unarchiving and deleting a project, and changing another user's role, additionally require `owner`/`admin` (`require_role(...)`). `GET`/`PATCH /api/users/{userId}/role` manage the team. `packages/web` gates the whole app behind a sign-in/create-account screen (`src/AuthScreen.tsx`), attaches the token to every request, and reacts to a token going bad mid-session (expired, or an admin changed the role) by returning to sign-in; a new Settings screen shows the signed-in account and, for owner/admin, the full team with a role-change control. Roles are **global, not per-project** — every authenticated user can see every project; per-project membership, teams/workspaces, and client accounts (a materially bigger, still-unstarted feature — there's no tenancy concept anywhere in the schema) remain **Planned**. 18 new backend tests, plus a live Node `fetch` smoke test covering the full register → login → role-gated 403 → promote → retry flow against a running `API_REPOSITORY=memory` instance.
- **Project version history and restore** — **Done**: `GET /api/projects/{projectId}/versions` lists one version per past calculation run — "each recalculation ... becomes a version with a timestamp" is already exactly what `grp_runs` did from Phase 1 onward, so this is computed on read (same pattern as `GET /validation-issues`) rather than a second write path. `grp_runs` gained `is_current`; `POST /versions/{versionId}/restore` (owner/admin only, like archiving/deleting) pins `GET /runs/latest` — and therefore Overview/Reports/Activity — back to an older run's numbers without deleting the newer run or anything it calculated, since every run's `grp_calculations` rows stay in the table regardless of which one is current. `packages/web`'s Projects panel gained a Version History table (generated time, a plain-English summary, a Current badge, and a Restore button gated the same way the backend gates it). 7 new backend tests, plus a live smoke test covering calculate twice → list versions → restore the older one → confirm `runs/latest` flips → confirm the newer run's calculations are still readable → confirm a `member` gets 403.
- **Export Centre (full Excel workbook)** — **Done**: `POST /api/projects/{projectId}/exports` records which run an export is for (frozen at creation, not re-resolved later — an export is a point-in-time artifact); `GET /exports/{exportId}/download` (new — the original contract only specified a `downloadUrl` field, not a route) builds the actual `.xlsx` on demand from that frozen run, since no object storage is configured here to keep a generated file in (`exports.storage_path` stays `null`). All 8 sheets from "Export workbook structure" below are populated: Project Info, GRP & SOV, Brand Comparison (every brand side by side, not just two), Station Performance, Programme Performance, Spot-Level Calculations, Unmatched Records, Ratings Used. Only `xlsx_full` is accepted today — `xlsx_summary`/`pdf`/`csv` 422 by name rather than silently downgrading. `packages/web`'s new Exports screen generates and downloads through this pipeline, fetching the file with the caller's bearer token and handing the browser a `blob:` URL (a plain link can't carry an `Authorization` header). 11 new backend tests (verifying the actual workbook — sheet names, header rows, and that a deliberately-unmatched row shows up on the right sheet — not just that the endpoint returns 200), plus a live smoke test that downloads a real file and checks it starts with the `.xlsx` zip magic bytes.
- **Project Settings (edit + data management)** — **Done**: `PATCH /api/projects/{projectId}` already covered field edits (name, client, category, market, dates, audience, media types, ratings provider/period, status, notes); `packages/web` never exposed a form for it until now — the Project Settings panel (wrench icon in the Projects toolbar) does. New data-management actions: `DELETE .../uploads/{uploadId}`, `DELETE .../brands/{brandId}`, and `DELETE .../ratings-datasets/{ratingsDatasetId}/attach` (detach, not delete — the shared dataset lives on for other projects). Deleting an upload or brand is refused with a `409` if any of its rows were ever included in a calculated run (`calculations_repo.has_calculations_for_media_activity`) — protecting that run's `grp_calculations` audit trail from silently losing rows out from under it, per the audit rule at the top of this document; an upload/brand never calculated can always be removed. Detaching a ratings dataset carries no such risk (it only unlinks the project from the shared dataset — nothing already matched or calculated is touched) and needs no special role. Delete/detach are owner/admin-only, matching archive/delete's gating. 15 new backend tests plus a live smoke test covering delete-before-calculate (succeeds), delete-after-calculate (409), and detach-after-calculate (succeeds, audit trail intact).
- **Production deployment** — **Done**: `db/schema.sql` applied to a real Supabase Postgres instance (via the Session pooler connection — Supabase's Direct Connection host doesn't resolve on most IPv4-only networks, a real snag hit and fixed during this deployment), `services/api` running on Render (`render.yaml`, deployed straight from the existing `Dockerfile` with no code changes — `DATABASE_URL`, `JWT_SECRET`, and `ALLOWED_ORIGINS` set as Render environment variables, never committed anywhere), and `packages/web` running on Vercel (`VITE_API_BASE_URL` set at build time to the Render URL, since Vite bakes environment variables in at build time rather than reading them at runtime). Free tier on all three — worth knowing the API sleeps after ~15 minutes idle and takes 30-60s to wake on the next request, a real trade-off of $0/month, not a bug. A real user has registered and signed in through the full deployed chain, not just a health check.
- Full React replacement for the Streamlit UI, and retiring `app.py` — Export Centre and Project Settings above close two pieces of this; daypart/top-placements drill-down (blocked on upload data that isn't captured yet — see the Programmes row above) and actually retiring `app.py` remain
- Automated report templates
- Scheduled ingestion
- API connections to monitoring providers
