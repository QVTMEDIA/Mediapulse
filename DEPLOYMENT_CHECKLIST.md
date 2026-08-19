# Deployment Checklist

## Required

- Set a strong `GRP_APP_PASSWORD`
- Use `.xlsx`, `.xls`, or `.csv` inputs only
- Keep `.streamlit/secrets.toml` out of git
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
- Follow `STREAMLIT_CLOUD_DEPLOYMENT.md`

## Operational Notes

- Upload limits are enforced in the app:
  - 10 MB per file
  - 100,000 parsed rows
  - 100 parsed columns
- `.xlsm` files are blocked because macro-enabled uploads are unnecessary for calculation and increase risk.
- This app does not yet provide per-user accounts, database storage, or audit logs.
