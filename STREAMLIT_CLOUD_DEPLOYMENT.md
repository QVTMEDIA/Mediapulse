# Streamlit Community Cloud Deployment

Use this guide to deploy Mediapulse from the GitHub repository.

## App settings

- Repository: `QVTMEDIA/Mediapulse`
- Branch: `main`
- Main file path: `app.py`
- Suggested app URL/subdomain: `mediapulse`
- Current live app: `https://mediapulse-ypza7n5q3holruocrdgdmy.streamlit.app/`
- Preferred Python version: `3.14`

The app has been tested locally on Python `3.14.3`, and GitHub Actions also runs Python `3.14`.

If Streamlit Community Cloud does not offer Python `3.14` in Advanced settings, choose the newest available Python version and deploy. If dependency installation fails, use the build log to adjust `requirements.txt` to versions supported by that runtime.

## Secrets

Set this in Streamlit Community Cloud app settings under **Secrets**:

```toml
APP_PASSWORD = "replace-with-a-strong-password"
```

Do not commit a real `.streamlit/secrets.toml` file. The repo includes `.streamlit/secrets.toml.example` only as a local template.

If the live app shows "Password gate is disabled", open **Manage app**, then **Settings**, then **Secrets**. Paste the `APP_PASSWORD` block above, save it, and reboot the app.

## Deployment steps

1. Go to Streamlit Community Cloud.
2. Sign in with GitHub.
3. Authorize access to the private repo `QVTMEDIA/Mediapulse` if prompted.
4. Create a new app.
5. Choose:
   - Repository: `QVTMEDIA/Mediapulse`
   - Branch: `main`
   - Main file path: `app.py`
6. Open Advanced settings.
7. Set Python version to `3.14` if available.
8. Add the `APP_PASSWORD` secret shown above.
9. Deploy the app.
10. After deployment, sign in with the password and test:
   - Ratings + brand report upload
   - Composite report upload
   - Excel export
   - Unmatched row review

## After deployment

- Open the live app: `https://mediapulse-ypza7n5q3holruocrdgdmy.streamlit.app/`
- Keep `APP_PASSWORD` strong and rotate it if shared outside the team.
- Do not upload files larger than 10 MB.
- If the app fails to build, check the Streamlit build log first. Most deployment failures will be caused by Python runtime or package version mismatches.
- If the app starts but uploads behave differently from local testing, download the uploaded source file and compare the detected column mapping in the preview.
