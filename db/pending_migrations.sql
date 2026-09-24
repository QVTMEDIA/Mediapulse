-- Pending ALTER TABLE pass for the live Supabase instance.
--
-- db/schema.sql is the source of truth and is applied in full on a fresh
-- database; this file exists only because this project hand-edits
-- schema.sql in place rather than using a migration tool (see the "Open
-- decisions" section of db/README.md), so columns added to schema.sql
-- after the live instance was first stood up have to be applied here by
-- hand. Every statement below is idempotent (IF NOT EXISTS) and additive
-- (nullable or DEFAULTed, so existing rows never need a backfill) --
-- matches the exact column definition in schema.sql at the time this file
-- was written. Safe to run against a database that already has some or
-- all of these columns.
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
