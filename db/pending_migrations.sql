-- Pending schema changes for the live Supabase instance.
--
-- db/schema.sql is the source of truth and is applied in full on a fresh
-- database; this file exists only because this project hand-edits
-- schema.sql in place rather than using a migration tool (see the "Open
-- decisions" section of db/README.md), so columns/tables added to
-- schema.sql after the live instance was first stood up have to be applied
-- here by hand. Every statement below is idempotent (IF NOT EXISTS) and
-- additive (a new column is nullable or DEFAULTed, so existing rows never
-- need a backfill) -- matches the exact definition in schema.sql at the
-- time this file was written. Safe to run against a database that already
-- has some or all of these changes.
--
-- Run this in the Supabase SQL editor, or `psql < db/pending_migrations.sql`
-- against the same DATABASE_URL services/api uses. After it succeeds,
-- delete the corresponding line from services/api/README.md's
-- "db/schema.sql has changed" paragraph -- that's the running tally this
-- file closes out.

-- Ratings-source priority (project↔dataset attachment ordering) --
-- services/api PR "Let users rank ratings sources when multiple overlap
-- on a match key".
alter table project_ratings_datasets
  add column if not exists priority integer not null default 0;

-- SOE Explorer geography filter -- services/api PR "Add a standalone SOE
-- Explorer tab, filterable by medium/station/region/day/date".
alter table media_activity
  add column if not exists region text;

-- Cable TV granularity -- services/api PR adding brand_shares.cable_tv_grps
-- alongside the original tv_grps/radio_grps split.
alter table brand_shares
  add column if not exists cable_tv_grps numeric(14,3) not null default 0;

-- Spend Intelligence's medium breakdown -- services/api PR adding
-- brand_shares.tv_spend/cable_tv_spend/radio_spend alongside total_spend/soe.
alter table brand_shares
  add column if not exists tv_spend numeric(14,2) not null default 0;
alter table brand_shares
  add column if not exists cable_tv_spend numeric(14,2) not null default 0;
alter table brand_shares
  add column if not exists radio_spend numeric(14,2) not null default 0;

-- SOE Explorer uploads, made project-less entirely -- services/api PR
-- "SOE Explorer uploads no longer attach to any project". Supersedes an
-- earlier attempt (uploads.soe_only, an excluded-from-matching flag on a
-- still-project-attached upload) that never shipped to this instance --
-- nothing to roll back, this is the first and only version that applies.
create table if not exists soe_uploads (
  id uuid primary key default gen_random_uuid(),
  file_name text not null,
  mapped_rows int not null default 0,
  issue_rows int not null default 0,
  uploaded_by uuid references users(id) on delete set null,
  uploaded_at timestamptz not null default now()
);

create table if not exists soe_activity (
  id uuid primary key default gen_random_uuid(),
  upload_id uuid not null references soe_uploads(id) on delete cascade,
  brand text not null,
  medium text not null,
  station text not null,
  activity_date date,
  day text not null,
  programme text not null,
  spots int not null default 0,
  cost numeric(14,2),
  time_band text not null default '',
  region text not null default '',
  state text not null default '',
  source_file text not null
);

create index if not exists soe_activity_upload_idx on soe_activity (upload_id);

-- SOE Explorer State filter, independent of Region -- services/api PR
-- "Include option to filter by State on the SOE Explorer page". Safety
-- net in case soe_activity was already created by the block above on an
-- earlier run of this file, before `state` existed here.
alter table soe_activity
  add column if not exists state text not null default '';
