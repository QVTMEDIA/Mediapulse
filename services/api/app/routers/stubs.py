"""Route surface from API_CONTRACT.md that isn't implemented yet.

Registered explicitly (rather than left absent) so the full target API is
visible in /docs and callers get a clear 501 + roadmap pointer instead of a
plain 404 while these are built out. Remove an entry here as soon as a real
router implements it.
"""

import json

from fastapi import APIRouter, Response

router = APIRouter(prefix='/api', tags=['not-yet-implemented'])

# (method, path, roadmap note) — paths use the same {param} names as API_CONTRACT.md.
_NOT_IMPLEMENTED_ROUTES = [
    ('GET', '/projects/{project_id}/uploads/{upload_id}/preview', 'Upload ingestion — Phase 1'),
    ('POST', '/projects/{project_id}/uploads/{upload_id}/map', 'Column mapping — Phase 1'),
]


def _make_stub(note: str):
    body = json.dumps({'detail': 'Not implemented yet.', 'roadmap': note})

    def handler():
        return Response(status_code=501, media_type='application/json', content=body)

    return handler


for _method, _path, _note in _NOT_IMPLEMENTED_ROUTES:
    router.add_api_route(_path, _make_stub(_note), methods=[_method], status_code=501)
