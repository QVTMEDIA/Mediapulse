-- Mediapulse database schema (Postgres / Supabase)
--
-- Implements the data model in PRODUCT_ROADMAP.md and backs the entities in
-- API_CONTRACT.md. Written as plain Postgres DDL so it works unmodified on a
-- self-hosted Postgres instance or on Supabase (which is Postgres underneath).
-- Supabase-specific pieces (auth.users, Row Level Security policies) are
-- called out separately at the bottom and are optional to adopt.
--
-- Audit rule this schema exists to satisfy (PRODUCT_ROADMAP.md):
-- every calculated GRP row must trace back to its source upload, source row
-- number, normalized match key, rating dataset, rating row used, calculation
-- timestamp, and export/run ID.

create extension if not exists pgcrypto; -- gen_random_uuid()

create or replace function set_updated_at()
returns trigger as $$
begin
  new.updated_at = now();
  return new;
end;
$$ language plpgsql;

-- Mirrors grp_calculator.normalize_text: collapse internal whitespace, trim,
-- uppercase. Used by the match_key generated columns below so SQL-side exact
-- matching agrees with the Python matching engine on the same input.
create or replace function normalize_match_text(value text)
returns text
language sql
immutable
as $$
  select upper(regexp_replace(trim(both from coalesce(value, '')), '\s+', ' ', 'g'));
$$;

-- Mirrors grp_calculator.normalize_day/DAY_MAP. `day` is stored as whatever
-- text the source gave (grp_calculator's own report builders do the same —
-- they keep the raw/derived day text in the `Day` column and only normalize
-- when computing a Match Key), so normalization has to happen here rather
-- than being assumed already-done on write. An earlier version of this
-- schema assumed `day` was pre-normalized before storage and used a plain
-- upper(trim(day)) here — that silently disagreed with grp_calculator's
-- real behavior whenever `day` held a full name like "Monday" rather than
-- "MON", producing a different match key on each side for identical data.
create or replace function normalize_match_day(value text)
returns text
language sql
immutable
as $$
  select case lower(trim(coalesce(value, '')))
    when 'monday' then 'MON' when 'mon' then 'MON'
    when 'tuesday' then 'TUE' when 'tue' then 'TUE' when 'tues' then 'TUE'
    when 'wednesday' then 'WED' when 'wed' then 'WED'
    when 'thursday' then 'THU' when 'thu' then 'THU' when 'thur' then 'THU' when 'thurs' then 'THU'
    when 'friday' then 'FRI' when 'fri' then 'FRI'
    when 'saturday' then 'SAT' when 'sat' then 'SAT'
    when 'sunday' then 'SUN' when 'sun' then 'SUN'
    else upper(left(normalize_match_text(value), 3))
  end;
$$;

-- ---------------------------------------------------------------------------
-- users
-- ---------------------------------------------------------------------------
-- Real multi-user auth (Phase 3): password_hash is PBKDF2-HMAC-SHA256 (see
-- services/api/app/security.py), not bcrypt/scrypt — a deliberate choice to
-- avoid a compiled dependency; nullable because a user provisioned another
-- way (e.g. a future Supabase Auth migration, or an invite not yet accepted)
-- may not have a local password at all. `role` is a global role, not a
-- per-project ACL — every authenticated user can see every project; only
-- 'owner'/'admin' can archive/delete a project or change another user's
-- role. Per-project membership, teams/workspaces, and client accounts are
-- a bigger, still-unstarted undertaking (see PRODUCT_ROADMAP.md Phase 3).
-- If adopting Supabase Auth later, this table can become a thin profile
-- table keyed by auth.users(id) instead of owning its own id/email/password.

create table users (
  id uuid primary key default gen_random_uuid(),
  email text not null unique,
  display_name text,
  password_hash text,
  role text not null default 'member', -- 'owner' | 'admin' | 'member'
  created_at timestamptz not null default now()
);

-- ---------------------------------------------------------------------------
-- projects
-- ---------------------------------------------------------------------------

create table projects (
  id uuid primary key default gen_random_uuid(),
  name text not null,
  client text,
  category text,
  market text,
  start_date date,
  end_date date,
  target_audience text,
  media_types text[] not null default '{}', -- e.g. {TV,Radio}
  ratings_provider text,
  ratings_period text,
  status text not null default 'Setup', -- 'Setup' | 'Data Review' | 'Complete'
  archived boolean not null default false,
  notes text,
  owner_name text,                             -- free-text owner (current product behavior; no real accounts yet)
  owner_id uuid references users(id) on delete set null, -- reserved for Phase 3 multi-user auth
  created_at timestamptz not null default now(),
  updated_at timestamptz not null default now()
);

create trigger projects_set_updated_at
  before update on projects
  for each row execute function set_updated_at();

create index projects_status_idx on projects (status) where not archived;

-- ---------------------------------------------------------------------------
-- ratings_datasets / ratings  (the shared Ratings Library)
-- ---------------------------------------------------------------------------
-- A ratings dataset is NOT owned by one project — it's uploaded once (e.g.
-- "Nigeria TV Ratings - Q1 2026") and attached to whichever projects use it,
-- via project_ratings_datasets.

create table ratings_datasets (
  id uuid primary key default gen_random_uuid(),
  provider text,
  period text,
  market text,
  audience text,
  media_types text[] not null default '{}',
  row_count int not null default 0,
  invalid_rows int not null default 0,
  duplicate_keys int not null default 0,
  status text not null default 'Needs Review', -- 'Ready' | 'Needs Review'
  uploaded_by uuid references users(id) on delete set null,
  uploaded_at timestamptz not null default now()
);

-- match_key was originally a `generated always as (...) stored` column here
-- (and on media_activity below) — Postgres rejected that with `ERROR: 42P17:
-- generation expression is not immutable` on Supabase, even though
-- normalize_match_text/normalize_match_day are declared IMMUTABLE. A
-- trigger-maintained plain column sidesteps that class of error entirely
-- (triggers aren't held to the same provable-immutability bar generated
-- columns are) while producing the exact same value on every insert/update,
-- so nothing about querying it (`where match_key = ...`, the index below)
-- changes. services/api never inserts into match_key explicitly — it always
-- relied on this being computed automatically — so this swap needed no
-- application-code change.
create table ratings (
  id uuid primary key default gen_random_uuid(),
  ratings_dataset_id uuid not null references ratings_datasets(id) on delete cascade,
  medium text not null,
  station text not null,
  day text not null,          -- normalized 3-letter code (Mon, Tue, ...)
  programme text,
  time_band text,
  rating numeric(7,3) not null,
  start_time time,
  end_time time,
  week int,
  month int,
  -- normalized match key, computed the same way as grp_calculator.make_key:
  -- MEDIUM | STATION | DAY | PROGRAMME/TIME BAND — set by the trigger below,
  -- not a generated column (see the comment above this table).
  match_key text
);

create or replace function ratings_set_match_key()
returns trigger as $$
begin
  new.match_key := normalize_match_text(new.medium) || '|' || normalize_match_text(new.station) || '|' ||
    normalize_match_day(new.day) || '|' || normalize_match_text(concat_ws(' ', new.programme, new.time_band));
  return new;
end;
$$ language plpgsql;

create trigger ratings_set_match_key_trigger
  before insert or update on ratings
  for each row execute function ratings_set_match_key();

create index ratings_dataset_idx on ratings (ratings_dataset_id);
create index ratings_match_key_idx on ratings (match_key);

create table project_ratings_datasets (
  project_id uuid not null references projects(id) on delete cascade,
  ratings_dataset_id uuid not null references ratings_datasets(id) on delete restrict,
  attached_at timestamptz not null default now(),
  primary key (project_id, ratings_dataset_id)
);

-- ---------------------------------------------------------------------------
-- brands
-- ---------------------------------------------------------------------------

create table brands (
  id uuid primary key default gen_random_uuid(),
  project_id uuid not null references projects(id) on delete cascade,
  name text not null,
  created_at timestamptz not null default now(),
  unique (project_id, name)
);

create index brands_project_idx on brands (project_id);

-- ---------------------------------------------------------------------------
-- mapping_templates
-- ---------------------------------------------------------------------------
-- Not project-scoped: a confirmed column mapping is reusable across projects
-- for the same report source (e.g. "Media Monitoring Agency A").

create table mapping_templates (
  id uuid primary key default gen_random_uuid(),
  source_label text not null unique,
  -- logical field -> uploaded column name, e.g. {"channel": "Media Channel",
  -- "brand": "Advertiser", ...} — matches the shape app/parsing.py already
  -- builds internally, so a saved template can be applied without translation.
  field_mapping jsonb not null,
  created_at timestamptz not null default now(),
  last_used_at timestamptz
);

-- ---------------------------------------------------------------------------
-- uploads
-- ---------------------------------------------------------------------------

create table uploads (
  id uuid primary key default gen_random_uuid(),
  project_id uuid not null references projects(id) on delete cascade,
  brand_id uuid references brands(id) on delete set null,
  file_name text not null,
  kind text not null, -- 'ratings' | 'brand_report' | 'composite_report'
  mapping_template_id uuid references mapping_templates(id) on delete set null,
  mapped_rows int not null default 0,
  issue_rows int not null default 0,
  uploaded_by uuid references users(id) on delete set null,
  uploaded_at timestamptz not null default now()
);

create index uploads_project_idx on uploads (project_id);

-- ---------------------------------------------------------------------------
-- media_activity
-- ---------------------------------------------------------------------------
-- The normalized, standard-structure row produced after column mapping.
-- source_file + source_row_number preserve the audit trail back to the
-- original upload cell.

create table media_activity (
  id uuid primary key default gen_random_uuid(),
  project_id uuid not null references projects(id) on delete cascade,
  brand_id uuid not null references brands(id) on delete cascade,
  upload_id uuid not null references uploads(id) on delete cascade,
  medium text not null,
  station text not null,
  activity_date date,
  day text not null,
  programme text,
  time_band text,
  spots int not null default 0,
  duration int,
  ad_type text,
  start_time time,
  end_time time,
  campaign text,
  product text,
  source_file text,
  source_row_number int,
  -- Trigger-maintained, not a generated column — see the comment above the
  -- ratings table for why.
  match_key text
);

create or replace function media_activity_set_match_key()
returns trigger as $$
begin
  new.match_key := normalize_match_text(new.medium) || '|' || normalize_match_text(new.station) || '|' ||
    normalize_match_day(new.day) || '|' || normalize_match_text(concat_ws(' ', new.programme, new.time_band));
  return new;
end;
$$ language plpgsql;

create trigger media_activity_set_match_key_trigger
  before insert or update on media_activity
  for each row execute function media_activity_set_match_key();

create index media_activity_project_idx on media_activity (project_id);
create index media_activity_brand_idx on media_activity (brand_id);
create index media_activity_match_key_idx on media_activity (match_key);

-- ---------------------------------------------------------------------------
-- rating_matches
-- ---------------------------------------------------------------------------
-- Current match state for a media_activity row. One row per media_activity
-- row (its "live" match); grp_calculations snapshots which rating_match was
-- used for a given run, so a later manual correction doesn't rewrite history.

create table rating_matches (
  id uuid primary key default gen_random_uuid(),
  media_activity_id uuid not null references media_activity(id) on delete cascade,
  matched_rating_id uuid references ratings(id) on delete set null,
  match_status text not null, -- 'exact' | 'suggested' | 'unmatched' | 'manual'
  match_confidence numeric(4,3), -- 0..1, set for 'suggested'
  match_key text not null,
  corrected_by uuid references users(id) on delete set null,
  corrected_at timestamptz,
  created_at timestamptz not null default now(),
  unique (media_activity_id)
);

create index rating_matches_status_idx on rating_matches (match_status);

-- ---------------------------------------------------------------------------
-- grp_runs / grp_calculations / brand_shares
-- ---------------------------------------------------------------------------
-- A "run" is one calculation pass over a project's media_activity. Row-level
-- grp_calculations are the audit trail; brand_shares is the per-run rollup
-- that backs the SOV chart and brand comparison screen. Station- and
-- programme-level views are derived by joining grp_calculations to
-- media_activity rather than stored separately (see views below).

-- is_current: exactly one row per project is true at a time (enforced in
-- application code, not a partial unique index — see
-- services/api/app/repositories/calculations.py's create_run/restore_run).
-- A fresh calculate() always makes its new run current; POST
-- .../versions/{versionId}/restore (Phase 3 version history) can pin it
-- back to an older run without deleting the newer one — grp_calculations
-- for every run stay in the table regardless, so nothing about the audit
-- trail is lost by restoring.
create table grp_runs (
  id uuid primary key default gen_random_uuid(),
  project_id uuid not null references projects(id) on delete cascade,
  total_brands int not null default 0,
  total_spots int not null default 0,
  total_grps numeric(14,3) not null default 0,
  matched_rows int not null default 0,
  unmatched_rows int not null default 0,
  is_current boolean not null default true,
  triggered_by uuid references users(id) on delete set null,
  generated_at timestamptz not null default now()
);

create index grp_runs_project_idx on grp_runs (project_id, generated_at desc);
create index grp_runs_current_idx on grp_runs (project_id) where is_current;

create table grp_calculations (
  id uuid primary key default gen_random_uuid(),
  run_id uuid not null references grp_runs(id) on delete cascade,
  media_activity_id uuid not null references media_activity(id) on delete cascade,
  rating_match_id uuid references rating_matches(id) on delete set null,
  spots int not null,
  rating numeric(7,3),
  grp numeric(14,3) not null,
  calculated_at timestamptz not null default now()
);

create index grp_calculations_run_idx on grp_calculations (run_id);
create index grp_calculations_activity_idx on grp_calculations (media_activity_id);

create table brand_shares (
  run_id uuid not null references grp_runs(id) on delete cascade,
  brand_id uuid not null references brands(id) on delete cascade,
  total_grps numeric(14,3) not null default 0,
  tv_grps numeric(14,3) not null default 0,
  radio_grps numeric(14,3) not null default 0,
  sov numeric(6,3) not null default 0,
  spots int not null default 0,
  avg_rating numeric(7,3),
  primary key (run_id, brand_id)
);

-- Station- and programme-level rollups (Stations / Programmes screens):
-- computed on demand rather than stored, since they're cheap aggregates over
-- an already-materialized run.

create view grp_by_station as
  select
    gc.run_id,
    ma.project_id,
    ma.brand_id,
    ma.station,
    sum(gc.grp) as total_grps,
    sum(gc.spots) as total_spots
  from grp_calculations gc
  join media_activity ma on ma.id = gc.media_activity_id
  group by gc.run_id, ma.project_id, ma.brand_id, ma.station;

create view grp_by_programme as
  select
    gc.run_id,
    ma.project_id,
    ma.brand_id,
    ma.programme,
    sum(gc.grp) as total_grps,
    sum(gc.spots) as total_spots
  from grp_calculations gc
  join media_activity ma on ma.id = gc.media_activity_id
  group by gc.run_id, ma.project_id, ma.brand_id, ma.programme;

-- ---------------------------------------------------------------------------
-- validation_issues
-- ---------------------------------------------------------------------------

create table validation_issues (
  id uuid primary key default gen_random_uuid(),
  project_id uuid not null references projects(id) on delete cascade,
  run_id uuid references grp_runs(id) on delete cascade,
  severity text not null, -- 'info' | 'warning' | 'error'
  area text not null,
  message text not null,
  rows int not null default 0,
  created_at timestamptz not null default now()
);

create index validation_issues_project_idx on validation_issues (project_id);

-- ---------------------------------------------------------------------------
-- project_versions
-- ---------------------------------------------------------------------------

create table project_versions (
  id uuid primary key default gen_random_uuid(),
  project_id uuid not null references projects(id) on delete cascade,
  run_id uuid references grp_runs(id) on delete set null,
  description text,
  created_at timestamptz not null default now()
);

create index project_versions_project_idx on project_versions (project_id, created_at desc);

-- ---------------------------------------------------------------------------
-- exports
-- ---------------------------------------------------------------------------

create table exports (
  id uuid primary key default gen_random_uuid(),
  project_id uuid not null references projects(id) on delete cascade,
  run_id uuid references grp_runs(id) on delete set null,
  format text not null, -- 'xlsx_full' | 'xlsx_summary' | 'pdf' | 'csv'
  storage_path text,     -- object storage key/URL for the generated file
  generated_by uuid references users(id) on delete set null,
  generated_at timestamptz not null default now()
);

create index exports_project_idx on exports (project_id, generated_at desc);

-- ---------------------------------------------------------------------------
-- Optional: Supabase Row Level Security
-- ---------------------------------------------------------------------------
-- Only relevant if/when this deploys on Supabase with Supabase Auth. Left
-- disabled by default so this schema also runs as-is on plain Postgres.
-- Example shape, once `owner_id`/auth wiring exists:
--
-- alter table projects enable row level security;
-- create policy "owners manage their projects" on projects
--   for all using (owner_id = auth.uid());
