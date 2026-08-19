$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

if (-not $env:GRP_APP_PASSWORD) {
    Write-Warning "GRP_APP_PASSWORD is not set. The app will run locally with the password gate disabled."
    Write-Warning "For shared deployment, set GRP_APP_PASSWORD before starting the app."
}

python -m streamlit run app.py --server.port 8501 --browser.gatherUsageStats false
