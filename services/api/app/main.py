import os

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from psycopg.errors import InvalidTextRepresentation

from .routers import (
    activity_log,
    auth,
    brands,
    exports,
    mapping_templates,
    matches,
    projects,
    ratings,
    runs,
    soe,
    station_aliases,
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
_default_origins = (
    'http://127.0.0.1:5173,http://localhost:5173,http://127.0.0.1:4173,http://localhost:4173,'
    'https://mediapulse-eta.vercel.app'
)
_allowed_origins = {
    origin.strip().rstrip('/')
    for origin in os.environ.get('ALLOWED_ORIGINS', _default_origins).split(',')
    if origin.strip()
}
app.add_middleware(
    CORSMiddleware,
    allow_origins=sorted(_allowed_origins),
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
app.include_router(soe.router)
app.include_router(stubs.router)
app.include_router(activity_log.router)
app.include_router(station_aliases.router)


# Every id column in db/schema.sql is `uuid`, and every repository's
# get-by-id method (get_project, get_brand, ...) just passes whatever string
# a path parameter handed it straight into a `WHERE id = %s` -- there's no
# separate "is this even a valid id?" check anywhere before the query runs.
# A real, malformed id (a stale bookmark, a copy-paste typo, a test script's
# "does-not-exist" placeholder) makes Postgres itself reject the value with
# "invalid input syntax for type uuid", which reaches here as an unhandled
# InvalidTextRepresentation and would otherwise surface as a bare 500 -- found
# live: GET /api/projects/does-not-exist 500'd instead of 404'ing, on every
# such route across the app, not just one. A malformed id was never found,
# which is exactly what 404 already means everywhere else in this API.
@app.exception_handler(InvalidTextRepresentation)
async def invalid_id_format_handler(request: Request, exc: InvalidTextRepresentation) -> JSONResponse:
    return JSONResponse(status_code=404, content={'detail': 'Not found.'})


@app.get('/api/health', tags=['health'])
async def health():
    return {'status': 'ok'}
