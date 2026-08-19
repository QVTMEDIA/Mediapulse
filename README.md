# Mediapulse

Mediapulse is a Streamlit app for automatically calculating TV/Radio GRPs and GRP-based Share of Voice from programme ratings, brand media reports, and composite media reports.

Live app: https://mediapulse-ypza7n5q3holruocrdgdmy.streamlit.app/

## What it does

- Upload programme ratings in Excel or CSV.
- Upload multiple brand TV/Radio reports.
- Upload one or more composite reports that already contain spots and ratings/GRPs.
- Create a project workspace with client, category, market, audience, dates, and media assumptions.
- Auto-detect common column names and let the user correct the mapping.
- Match on Medium + Channel/Station + Day + Programme/Time Band.
- Calculate row GRP = Spots x Matched Rating.
- Calculate TV GRPs, Radio GRPs, Total GRPs, Total Category GRPs and GRP-based SOV.
- Flag unmatched rows.
- Suggest close rating matches for unmatched rows.
- Export results to Excel with run and validation summary sheets.
- If a brand column is missing, uses the uploaded filename as the brand name.

## Run locally

```bash
pip install -r requirements.txt
streamlit run app.py
```

On Windows, you can also run:

```powershell
.\run_app.ps1
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

For a shared company deployment, add authentication, database storage, saved rating waves, brand/project workspaces, fuzzy-match review, user roles, and an audit log.

## Upload limits

- Allowed file types: `.xlsx`, `.xls`, `.csv`
- Blocked file type: `.xlsm`
- Maximum file size: 10 MB
- Maximum parsed rows: 100,000
- Maximum parsed columns: 100
