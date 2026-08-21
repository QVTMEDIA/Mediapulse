import os

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .routers import (
    auth,
    brands,
    exports,
    mapping_templates,
    matches,
    projects,
    ratings,
    runs,
    stubs,
    uploads,
    users,
    validation,
    versions,
)

app = FastAPI(
    title='Mediapulse API',
    version='0.1.0',
    description='Backend for the Vite/React frontend, per API_CONTRACT.md. '
                 'See services/api/README.md for implementation status.',
)

# Comma-separated list; defaults cover the Vite dev server and `vite preview`.
_default_origins = 'http://127.0.0.1:5173,http://localhost:5173,http://127.0.0.1:4173,http://localhost:4173'
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in os.environ.get('ALLOWED_ORIGINS', _default_origins).split(',') if origin.strip()],
    allow_credentials=True,
    allow_methods=['*'],
    allow_headers=['*'],
)

app.include_router(auth.router)
app.include_router(users.router)
app.include_router(projects.router)
app.include_router(brands.router)
app.include_router(uploads.router)
app.include_router(matches.router)
app.include_router(runs.router)
app.include_router(validation.router)
app.include_router(mapping_templates.router)
app.include_router(ratings.router)
app.include_router(versions.router)
app.include_router(exports.router)
app.include_router(stubs.router)


@app.get('/api/health', tags=['health'])
def health():
    return {'status': 'ok'}
