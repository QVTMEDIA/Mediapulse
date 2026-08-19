# Release Checklist

Use this before sharing a new version of the app.

- Run `.\run_tests.ps1`
- Confirm both workflows manually:
  - Composite Report with `Composite 2026.xlsx`
  - Separate Ratings + Brand Reports with the bundled sample files
- Confirm exports open in Excel:
  - `Composite_GRP_SOV_results.xlsx`
  - `Matched_GRP_SOV_results.xlsx`
- Confirm `.xlsm` uploads are blocked
- Confirm `GRP_APP_PASSWORD` is set for any shared deployment
- Build Docker image if deploying by container:
  - `docker build -t grp-sov-app .`
- Update README if workflow, limits, or run commands changed
- Commit with a clear release message
