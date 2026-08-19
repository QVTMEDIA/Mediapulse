# Deployment Checklist

## Required

- Set a strong password:
  - Streamlit Cloud: `APP_PASSWORD`
  - Local/Docker: `GRP_APP_PASSWORD`
- Confirm password login works
- Confirm repeated incorrect passwords trigger a temporary lockout
- Use `.xlsx`, `.xls`, or `.csv` inputs only
- Keep `.streamlit/secrets.toml` out of git
- Confirm project metadata storage is acceptable:
  - default SQLite path: `.streamlit/mediapulse_projects.db`
  - optional override: `PROJECT_DB_PATH` or `MEDIAPULSE_PROJECT_DB`
- Run tests before deployment:
  - `python -m unittest discover -s tests -v`
- Confirm the app health endpoint responds:
  - `http://localhost:8501/_stcore/health`

## Docker

- Install Docker Desktop or Docker Engine
- Build:
  - `docker build -t mediapulse .`
- Run:
  - `docker compose up --build`
- Confirm browser access:
  - `http://localhost:8501`

## Streamlit Community Cloud

- Live app:
  - `https://mediapulse-ypza7n5q3holruocrdgdmy.streamlit.app/`
- Use repository `QVTMEDIA/Mediapulse`
- Use branch `main`
- Use main file path `app.py`
- Set Python version to `3.14` if available
- Add secret:
  - `APP_PASSWORD = "replace-with-a-strong-password"`
- If the app says "Password gate is disabled", set `APP_PASSWORD` in **Manage app > Settings > Secrets** and reboot.
- Follow `STREAMLIT_CLOUD_DEPLOYMENT.md`

## Operational Notes

- Upload limits are enforced in the app:
  - 10 MB per file
  - 100,000 parsed rows
  - 100 parsed columns
- `.xlsm` files are blocked because macro-enabled uploads are unnecessary for calculation and increase risk.
- The current SQLite project store is for a single app deployment. It does not yet provide per-user accounts, shared production database storage, or audit logs.
