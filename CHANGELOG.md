# Changelog

## Unreleased

### Added

- Session-based project workspace setup before upload workflows.
- Project metadata export sheet.
- Product roadmap for the project-based media intelligence platform.

## v0.2 - 2026-08-19

### Added

- Upload mapping review panels for Composite, Ratings, and Brand uploads.
- Excel export sheets for run summaries and validation summaries.
- Composite report template download.
- Suggested rating matches for unmatched rows.
- Password gate session timeout and temporary failed-login lockout.
- Clear in-app setup guidance when `APP_PASSWORD` is missing on Streamlit Cloud.
- Dev container configuration.

### Fixed

- Prevented a mapping review error when numeric warning checks saw blank non-numeric fields.

## v0.1 - 2026-08-19

### Added

- Initial Mediapulse deployment on Streamlit Community Cloud.
- Composite report workflow.
- Separate Ratings + Brand Reports workflow.
- Excel exports for calculated GRP/SOV results.
- Upload validation, file-size limits, `.xlsm` blocking, and formula-safe Excel exports.
- GitHub Actions CI for tests, compile checks, and Docker build.
