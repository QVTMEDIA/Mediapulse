# Mediapulse Vite/React Migration

The Streamlit app remains the working production MVP. The Vite/React frontend is being added alongside it so screens can move over gradually without interrupting the deployed calculator.

## Current Split

- `app.py`: Streamlit UI and deployed MVP.
- `grp_calculator.py`: Python calculation and validation engine.
- `project_store.py`: local SQLite project metadata store.
- `packages/web`: Vite/React frontend shell.

## Target Architecture

```text
Vite + React frontend
        |
Python API service
        |
Postgres/Supabase database
        |
GRP calculation engine
```

The calculation engine should stay in Python. The React app should own navigation, project dashboards, uploads, mapping review, manual match correction, and report exploration.

## Migration Order

1. Keep Streamlit as the reference product while React is built.
2. Define API contracts for projects, ratings datasets, uploads, GRP runs, and validation issues.
3. Move Projects home and Ratings Library to React first.
4. Add a Python API wrapper around the existing calculation functions.
5. Move upload mapping and report generation workflows after the API is stable.
6. Replace local SQLite with Supabase/Postgres before multi-user production use.

## Frontend Commands

```powershell
cd packages/web
npm install
npm run dev
npm run build
```

The Vite development server defaults to `http://127.0.0.1:5173`.
