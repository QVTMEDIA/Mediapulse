from fastapi import APIRouter, Depends, HTTPException, Query

from ..auth import get_current_user
from ..repositories.mapping_templates import (
    MappingTemplateRecord,
    MappingTemplatesRepository,
    get_mapping_templates_repository,
)
from ..schemas.mapping_templates import MappingTemplateCreate, MappingTemplateOut

# Every route in this router requires a logged-in user (any role) — see
# app/auth.py. Applied at the router level rather than per-route so a new
# route added here can't accidentally ship unauthenticated.
router = APIRouter(prefix='/api/mapping-templates', tags=['mapping-templates'], dependencies=[Depends(get_current_user)])


def _to_out(record: MappingTemplateRecord) -> MappingTemplateOut:
    return MappingTemplateOut(
        mapping_template_id=record.id,
        source_label=record.source_label,
        field_mapping=record.field_mapping,
        created_at=record.created_at,
        last_used_at=record.last_used_at,
    )


@router.get('', response_model=list[MappingTemplateOut])
def list_mapping_templates(repo: MappingTemplatesRepository = Depends(get_mapping_templates_repository)):
    return [_to_out(record) for record in repo.list_templates()]


@router.post('', response_model=MappingTemplateOut, status_code=201)
def create_mapping_template(
    payload: MappingTemplateCreate,
    repo: MappingTemplatesRepository = Depends(get_mapping_templates_repository),
):
    """Also how an upload's auto-detected mapping gets saved for reuse — see
    the `sourceLabel`/`saveAsTemplate` form fields on the upload endpoints,
    which call this same save_template() under the hood."""
    return _to_out(repo.save_template(payload.source_label, payload.field_mapping))


@router.get('/suggest', response_model=MappingTemplateOut)
def suggest_mapping_template(
    source_label: str = Query(..., alias='sourceLabel'),
    repo: MappingTemplatesRepository = Depends(get_mapping_templates_repository),
):
    record = repo.get_by_source_label(source_label)
    if record is None:
        raise HTTPException(status_code=404, detail='No saved mapping template for that source label')
    return _to_out(record)
