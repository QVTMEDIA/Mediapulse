# Mediapulse

Mediapulse is a Streamlit app for automatically calculating TV/Radio GRPs and GRP-based Share of Voice from programme ratings, brand media reports, and composite media reports.

Live app: https://mediapulse-ypza7n5q3holruocrdgdmy.streamlit.app/

The current deployed MVP is Streamlit. A Vite/React frontend is available under `packages/web` as the migration path for the product UI.

## What it does

- Upload programme ratings in Excel or CSV.
- Upload multiple brand TV/Radio reports.
- Upload one or more composite reports that already contain spots and ratings/GRPs.
- Create, open, duplicate, archive, delete, export, and import project workspaces.
- Capture project metadata with client, category, owner, market, audience, dates, and media assumptions.
- Save project metadata to a local SQLite store for the current deployment.
- Auto-detect common column names and let the user correct the mapping.
- Match on Medium + Channel/Station + Day + Programme/Time Band.
- Calculate row GRP = Spots x Matched Rating.
- Calculate TV GRPs, Radio GRPs, Total GRPs, Total Category GRPs and GRP-based SOV.
- Flag unmatched rows.
- Suggest close rating matches for unmatched rows.
- Export results to Excel with run and validation summary sheets.
- If a brand column is missing, uses the uploaded filename as the brand name.

## Upload and processing rules

- Accepted uploads are `.xlsx`, `.xls`, and `.csv`; PDFs, screenshots, ZIP files, and macro workbooks are not supported.
- Keep each uploaded file under 10 MB. Excel workbooks must stay under 120 MB after expansion.
- Keep each selected sheet under 100,000 data rows, 100 columns, and 2,000,000 cells.
- Keep workbooks to 12 sheets or fewer, and remove unused or hidden tabs before upload.
- Use flat data: one header row and one airing, spot, or programme row per record.
- Remove grand totals, subtotal blocks, notes, merged title rows, pivot tables, charts, and formatting-heavy tabs before upload.
- Split large reports by month, brand, medium, campaign, or market before upload.
- Run calculations, fuzzy unmatched suggestions, and Excel exports only after sheet/header/mapping choices look correct.

## Run locally

Run the Streamlit MVP:

```bash
pip install -r requirements.txt
streamlit run app.py
```

On Windows, you can also run:

```powershell
.\run_app.ps1
```

Run the Vite/React frontend:

```powershell
cd packages/web
npm install
npm run dev
```

Or:

```powershell
.\run_web.ps1
```

## Run tests

```powershell
.\run_tests.ps1
```

or:

```bash
python -m unittest discover -s tests -v
```

## Run with Docker

Build the image:

```bash
docker build -t mediapulse .
```

Run locally without a password gate:

```bash
docker run --rm -p 8501:8501 mediapulse
```

Run with a password gate:

```powershell
$env:GRP_APP_PASSWORD = "replace-with-a-strong-password"
docker run --rm -p 8501:8501 -e GRP_APP_PASSWORD=$env:GRP_APP_PASSWORD mediapulse
```

Or use Docker Compose:

```powershell
$env:GRP_APP_PASSWORD = "replace-with-a-strong-password"
docker compose up --build
```

Then open `http://localhost:8501`.

## Deploy to Streamlit Community Cloud

Use `STREAMLIT_CLOUD_DEPLOYMENT.md` for the exact GitHub repo, branch, entrypoint, Python version, and secret settings.

Current deployment: https://mediapulse-ypza7n5q3holruocrdgdmy.streamlit.app/

## Product roadmap

The long-term project-based platform direction is tracked in `PRODUCT_ROADMAP.md`.

The current Projects home saves metadata to a local SQLite store. Export the project manifest if you need to move metadata between deployments or app environments. Supabase/Postgres storage is still the recommended next step for durable multi-user use.

The Vite/React migration plan is tracked in `FRONTEND_MIGRATION.md`. The initial API surface is tracked in `API_CONTRACT.md`.

## Project storage

By default, project metadata is stored at `.streamlit/mediapulse_projects.db`. You can override that path with:

- environment variable `MEDIAPULSE_PROJECT_DB`, or
- Streamlit secret `PROJECT_DB_PATH`

This SQLite store is useful for local work and a single Streamlit deployment. It is not a replacement for production database storage with users, permissions, version history, and audit logs.

## CI and release checks

GitHub Actions are configured in `.github/workflows/ci.yml` to run:

- unit tests
- Python compile checks
- Docker image build

Before sharing a new version, follow `RELEASE_CHECKLIST.md`. Before deploying to a server, follow `DEPLOYMENT_CHECKLIST.md`.

Release history is tracked in `CHANGELOG.md`.

## Password gate

The app supports a simple password gate for shared deployments. Set either:

- environment variable `GRP_APP_PASSWORD`, or
- Streamlit secret `APP_PASSWORD`

For local Streamlit secrets, copy `.streamlit/secrets.toml.example` to `.streamlit/secrets.toml` and replace the placeholder password. The real `.streamlit/secrets.toml` file is ignored by git.

If no password is configured, the app runs with the password gate disabled and shows setup instructions in the app.

For shared deployments, the password gate also expires authenticated sessions after 8 hours and temporarily locks the form after 5 failed attempts.

## Recommended input fields

### Ratings file
- Medium
- Channel / Station
- Day
- Programme / Time Band
- Rating (%)
- Source / Period (optional)

### Brand report
- Brand (optional; filename is used when absent)
- Medium
- Date or Day
- Channel / Station
- Programme / Time Band
- Spots

### Composite report
- Brand (optional; filename is used when absent)
- Medium (optional; app default can be used)
- Date or Day
- Channel / Station
- Programme / Time Band
- Spots
- Rating (%) or GRP

## Matching logic

The normalized match key is:

`MEDIUM | CHANNEL/STATION | DAY | PROGRAMME/TIME BAND`

All text is trimmed and made uppercase. Day names are normalized to 3-letter codes.

## Production improvements

For a shared company deployment, add full authentication, database storage, saved rating waves, fuzzy-match review, user roles, and an audit log.

## Upload limits

- Allowed file types: `.xlsx`, `.xls`, `.csv`
- Blocked file type: `.xlsm`
- Maximum file size: 10 MB
- Maximum parsed rows: 100,000
- Maximum parsed columns: 100
