# Mediapulse Vite/React Migration

The Streamlit app remains the working production MVP. The Vite/React frontend is being added alongside it so screens can move over gradually without interrupting the deployed calculator.

## Current Split

- `app.py`: Streamlit UI and deployed MVP.
- `grp_calculator.py`: Python calculation and validation engine.
- `project_store.py`: local SQLite project metadata store (used only by `app.py`).
- `packages/web`: Vite/React frontend — the whole app now sits behind real sign-in (`src/AuthScreen.tsx`), with eight real nav screens past that gate (Projects — including a Project Settings panel for field edits and data management, Ratings, Matches, Activity, Reports, Quality, Settings, Exports), each wired to `services/api` with no sample data; see `src/sections/` for the screen/panel components.
- `services/api`: Python API service — projects (including delete/detach data-management routes), brands, the Ratings Library, `brand_report`/`composite_report` uploads, saved mapping templates, matching, GRP calculation, station/programme/trend aggregation, validation issues, real multi-user auth + role-based permissions (`/api/auth/*`, `/api/users`), project version history + restore (`/api/projects/{id}/versions`), and the full-workbook Export Centre (`/api/projects/{id}/exports`) are implemented against Postgres; only upload preview/re-map (a deliberate gap — mapping applies automatically instead) and Phase 3's remaining deployment/scheduling/provider-connection items stay stubbed or not-yet-started. Imports `grp_calculator.py` directly for upload parsing, match suggestions, and the brand-rollup calculation (see `services/api/README.md`), so it isn't fully standalone from the repo root the way its own Dockerfile/requirements might suggest.
- `db/schema.sql`: the Postgres schema `services/api` reads/writes.

## Target Architecture

```text
Vite + React frontend
        |
Python API service
        |
Postgres/Supabase database
        |
GRP calculation engine
```

The calculation engine should stay in Python. The React app should own navigation, project dashboards, uploads, mapping review, manual match correction, and report exploration.

## Migration Order

1. Keep Streamlit as the reference product while React is built.
2. Define API contracts for projects, ratings datasets, uploads, GRP runs, and validation issues.
3. Move Projects home and Ratings Library to React first — **done**. Projects home is live (list/search/create/archive against `services/api`), its Overview KPIs/Brand SOV panel pull real GRP run data with a "Calculate" button, and its Upload form takes a project from a blank brand list to a real calculated GRP (create brand → upload a `brand_report` file → Calculate). The Ratings screen uploads a real spreadsheet or attaches an existing dataset from the library — no more sample data, no more needing curl/`/docs` to seed ratings.
4. Add a Python API wrapper around the existing calculation functions — **done**: `services/api` covers the full pipeline (projects, brands, ratings, uploads, matching, calculation, validation issues) against Postgres.
5. Move upload mapping and report generation workflows after the API is stable — **done**: both `brand_report` (single-brand-per-file) and `composite_report` (multi-brand-per-file, brand resolved per row from a Brand column) upload ingestion are live end to end, including a React form that switches between the two. Column mapping applies automatically (auto-detect, or a saved template keyed by a "Source label") rather than through a separate preview/re-map step — that dedicated review UI is not built, and isn't currently planned; see `PRODUCT_ROADMAP.md`. Report generation (station/programme/trend/brand-comparison) is **done**: a new Reports screen in `packages/web`.
6. Match review and audit — **done**: the Matches screen groups exact/suggested/unmatched/manual rows with Confirm/Reject on suggested matches, a picker to manually assign any attached rating to an `unmatched` row, and a Recompute action to retry `unmatched` rows after new ratings are attached. The Activity screen shows every calculated row (brand/station/programme/day/rating/GRP) as an audit trail.
7. Replace local SQLite with Supabase/Postgres before multi-user production use — **done**: `db/schema.sql` is applied to a real Supabase Postgres instance (via the Session pooler connection string — Supabase's Direct Connection host doesn't resolve over IPv4 on most networks, worth knowing before anyone else tries this), not just local `docker-compose`.
8. Deploy the API and frontend somewhere reachable, not just localhost — **done**: `services/api` on Render (`render.yaml`, the existing `Dockerfile` unchanged), `packages/web` on Vercel (`VITE_API_BASE_URL` set at build time to the Render URL — Vite bakes env vars in at build, they aren't read at runtime, so this has to be set before the build that needs it, not after). Both on free tiers; the API sleeps after ~15 minutes idle and takes 30-60s to wake on the next request, a real trade-off of the $0 tier, not a bug.
8. Real multi-user auth — **done**: `services/api` issues real JWTs against PBKDF2-hashed passwords (`POST /api/auth/register` + `/login`), every route requires one, and role (`owner`/`admin`/`member`) gates the sensitive actions (archive/delete a project, manage other users). `packages/web` gates the whole app behind a sign-in screen and adds a Settings screen for account/team management. Roles are global, not per-project — real workspaces/teams/client accounts (separate accounts seeing only their own projects) are a bigger, still-unstarted piece of this, not something the current role field does.
9. Project version history and restore — **done**: every `calculate` call already created a new `grp_runs` row; that row now also carries `is_current`, and `GET /versions` + `POST /versions/{id}/restore` expose that history and let an owner/admin pin the project's "current" numbers back to an older run without losing anything the newer run calculated. `packages/web`'s Projects panel shows the list with a Restore button.
10. Export Centre — **done** for the full Excel workbook (the format the Streamlit reference product already produces); executive-summary Excel, PDF/presentation, and CSV remain **planned**. `POST /exports` + `GET /exports/{id}/download` build all 8 sheets `PRODUCT_ROADMAP.md`'s "Export workbook structure" calls for, regenerated fresh on every download from a frozen run rather than read from object storage (none is configured here). `packages/web`'s new Exports screen generates and downloads through this pipeline.
11. Project Settings (field edits + data management) — **done**: `PATCH /api/projects/{id}` already covered field edits since Phase 1, but `packages/web` never had a form for it until now — a new Project Settings panel does, plus new `DELETE` routes for uploads/brands (refused with a 409 once a run depends on them, to protect that run's audit trail) and ratings-dataset detach (no such restriction — it never touches anything already calculated).

## Frontend Commands

```powershell
cd packages/web
npm install
npm run dev
npm run build
```

The Vite development server defaults to `http://127.0.0.1:5173`.

## Running the frontend against the API

Every screen calls `services/api` directly from the browser, so both need to be running:

```powershell
# terminal 1
cd services/api
$env:API_REPOSITORY = "memory"   # or point DATABASE_URL at Postgres
python -m uvicorn app.main:app --port 8000

# terminal 2
cd packages/web
npm run dev
```

The frontend defaults to `http://127.0.0.1:8000`; override with a `VITE_API_BASE_URL` in `packages/web/.env.local` (see `.env.example`). The API's CORS policy (`ALLOWED_ORIGINS` in `services/api/app/main.py`) already allows the default Vite dev/preview ports. Without the API running, the Projects panel shows an inline connection-error state rather than failing silently — everything else (nav, search input) still works since it doesn't touch the network.
