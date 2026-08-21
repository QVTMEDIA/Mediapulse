# Mediapulse Database

`schema.sql` is the executable Postgres schema for the target architecture in `FRONTEND_MIGRATION.md`:

```
Vite + React frontend
        |
Python API service
        |
Postgres/Supabase database
        |
GRP calculation engine
```

It implements the data model described in `PRODUCT_ROADMAP.md` and backs the entities in `API_CONTRACT.md`. Apply it with `psql` against a fresh database, or paste it into the Supabase SQL editor — it's plain DDL with no Supabase-specific dependencies, so it runs unmodified on either.

## Table map

| Table | Purpose |
| --- | --- |
| `users` | Real multi-user auth account: email, PBKDF2-hashed password (`password_hash`), global role. `services/api`'s `/api/auth/*` reads/writes this table now (see `services/api/README.md`); `app.py` (the Streamlit reference product) is untouched and still gates on the single shared `GRP_APP_PASSWORD` instead. |
| `projects` | One row per campaign/category workspace — the metadata already stored in SQLite today. |
| `ratings_datasets` / `ratings` | The shared **Ratings Library**: a dataset is uploaded once and reused across projects via `project_ratings_datasets`. |
| `project_ratings_datasets` | Join table — which ratings datasets a project currently uses. |
| `brands` | Brands within a project (from brand/composite report uploads). |
| `mapping_templates` | Saved column-mapping per report source, reused on future uploads from the same source. |
| `uploads` | One row per uploaded file, with mapping outcome counts. |
| `media_activity` | The normalized spot-level rows produced after mapping — the audit trail's `source_file`/`source_row_number` live here. |
| `rating_matches` | Current match state (exact/suggested/unmatched/manual) per `media_activity` row. |
| `grp_runs` | One row per calculation run. `is_current` (Phase 3) marks the run `GET /runs/latest` returns — normally the newest, but `POST /versions/{id}/restore` can pin it back to an older one without deleting anything. |
| `grp_calculations` | Row-level GRP audit trail for a run — snapshots which `rating_match` was used, so later corrections don't rewrite history. |
| `brand_shares` | Per-run brand rollup (GRP, SOV, TV/Radio split) backing the SOV chart and brand comparison screen. |
| `grp_by_station` / `grp_by_programme` | Views, not tables — cheap aggregates over `grp_calculations` for the Stations/Programmes screens. No need to materialize until they're a proven bottleneck. |
| `validation_issues` | Data Quality screen feed. |
| `project_versions` | Unused — Phase 3's `GET /api/projects/{projectId}/versions` computes version history on read from `grp_runs` instead (every run already is a version; a `grp_runs` row and its `is_current` flag are the only state a "version" needs), the same pattern `validation_issues` below uses. This table stays in the schema for a future write path (e.g. a user-supplied description per version) that doesn't exist yet, not because it's in use today. |
| `exports` | Export Centre history — metadata only (which run, which format, who, when). `storage_path` stays `null`: no object storage is configured in this environment, so `services/api` regenerates the `.xlsx` on every download from the frozen `run_id` instead of reading a stored file (see `services/api/README.md`). |

## Design notes

- **`match_key` is a trigger-maintained column**, computed to match `grp_calculator.make_key`/`normalize_text`/`normalize_day` field-for-field (whitespace-collapsed, trimmed, uppercased; `programme`+`time_band` joined with a space via `normalize_match_text()`/`concat_ws`; `day` mapped to its 3-letter code via `normalize_match_day()`, a SQL port of `grp_calculator.DAY_MAP`). Keeping the normalization logic identical in SQL and in the Python engine is deliberate — the API layer can push exact-match filtering into Postgres (`where match_key = ...`) while fuzzy/suggested matching stays in Python. `day` itself is stored as whatever text the source gave (e.g. "Monday", not "MON") — `grp_calculator`'s own report builders keep the raw/derived text in the `Day` column and only normalize when computing a Match Key, so `match_key` normalizes on write rather than assuming it was normalized already. (An earlier version of this schema got that backwards — see `CHANGELOG.md`.) This was originally a `generated always as (...) stored` column — Supabase's Postgres rejected that with `ERROR: 42P17: generation expression is not immutable` despite `normalize_match_text`/`normalize_match_day` being declared `immutable`, so it was switched to a plain column set by a `before insert or update` trigger (`ratings_set_match_key()`/`media_activity_set_match_key()`), which isn't held to the same provable-immutability requirement and produces an identical value. `services/api` never inserted into `match_key` explicitly, so this needed no application-code change — see `CHANGELOG.md`.
- **`rating_matches` is 1:1 with `media_activity`**, representing the *current* match state. `grp_calculations.rating_match_id` snapshots which match was used at calculation time, so re-running or manually correcting a match later doesn't corrupt a past run's audit trail.
- **Station/programme rollups are views, not tables.** They're cheap joins over an already-computed run; storing them separately would just be another thing to keep in sync.
- **Ratings datasets are decoupled from projects on purpose** — that's what makes the Ratings Library possible (upload "Nigeria TV Ratings – Q1 2026" once, attach it to several projects) instead of every project owning a private copy.

## Migration path off SQLite

`project_store.py` today stores only project metadata, as a JSON blob per row (`project_json` column) — there is no existing data for `ratings`, `media_activity`, `rating_matches`, or `grp_calculations`, because those never persisted past a Streamlit session. That significantly simplifies the migration:

1. **Stand up Postgres/Supabase and apply `schema.sql`.**
2. **Migrate `projects` only.** Write a one-off script that reads `load_projects()` from `project_store.py`, maps each JSON blob's fields to the `projects` columns above (camelCase → snake_case per `API_CONTRACT.md`), and inserts. This is the only table with real data to carry over.
3. **Everything else starts empty.** Ratings, uploads, media activity, matches, and calculations begin populating only once the API layer writes to the new tables — there's no backfill needed or possible for them.
4. **Introduce a data-access module** (e.g. `db.py`, using `psycopg`/SQLAlchemy, or the `supabase-py` client) behind the same kind of function boundary `project_store.py` already uses, so `app.py` — and later the API service — can be pointed at it without a rewrite of calling code.
5. **Retire `project_store.py`'s SQLite path** once the API service is the only writer, per `FRONTEND_MIGRATION.md` step 6.

## Open decisions (not resolved by this schema)

- **Supabase vs. self-hosted Postgres.** This schema runs on either; the choice affects auth (Supabase Auth vs. rolling your own), hosting/ops, and whether Row Level Security (sketched at the bottom of `schema.sql`) is worth turning on.
- **DB access library for the Python API service** — SQLAlchemy, plain `psycopg`, or `supabase-py`, depending on the answer above.
- **Migration tooling** — this schema is currently a single hand-written file; once schema changes start happening incrementally, adopt a migration tool (Alembic, or Supabase's own migration CLI) rather than hand-editing `schema.sql` in place.
