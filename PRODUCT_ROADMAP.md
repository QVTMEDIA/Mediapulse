# Mediapulse Product Roadmap

Mediapulse should evolve from an upload-and-calculate utility into a project-based media intelligence platform.

Core principle:

One project equals one campaign or category analysis workspace.

Every final GRP must remain auditable back to the individual media placement and the exact rating used.

## Current Product Spine

The current app supports:

- Project setup metadata
- Session-based Projects home with create, open, duplicate, archive, delete, export, and import
- Composite report workflow
- Separate Ratings + Brand Reports workflow
- Upload interpretation and column mapping review
- GRP and SOV calculations
- Validation tables and unmatched row suggestions
- Excel export with project, run, validation, summary, audit, and issue sheets
- Basic password protection for shared deployments

## Target Navigation

Inside each project, the long-term navigation should become:

- Overview
- Brands
- Stations
- Programmes
- Activity
- Data Quality
- Ratings
- Exports
- Project Settings

## Phase 1: Core Product

- Project setup and metadata
- Project list with manifest import/export
- Ratings upload
- Multiple brand uploads
- Composite report upload
- Column mapping
- Exact matching
- Suggested matches for unmatched rows
- GRP calculation
- SOV calculation
- Basic dashboard
- Excel export

## Phase 2: Intelligence

- Saved ratings library
- Saved mapping templates by report source
- Manual mismatch correction
- Station analysis
- Programme and daypart analysis
- Brand comparison screen
- Weekly and monthly trends
- Data quality screen

## Phase 3: Enterprise

- Persistent database storage
- Multiple users
- Teams and workspaces
- Client accounts
- Project version history
- Role-based permissions
- Automated report templates
- Scheduled ingestion
- API connections to monitoring providers

## Recommended Data Model

Future persistent storage should separate:

- users
- projects
- ratings_datasets
- ratings
- brands
- uploads
- media_activity
- rating_matches
- grp_calculations
- project_versions
- exports

## Export Direction

Excel exports should continue moving toward:

- Project Info
- Executive Summary
- GRP & SOV
- Brand Comparison
- Station Performance
- Programme Performance
- Spot-Level Calculations
- Unmatched Records
- Ratings Used
