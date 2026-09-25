from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile

from ..auth import get_current_user, require_role
from ..parsing import parse_composite_report
from ..repositories.soe import SoeRepository, SoeUploadRecord, get_soe_repository
from ..schemas.soe import SoeBrandOut, SoeFilterOptionsOut, SoeReportOut, SoeUploadOut

router = APIRouter(prefix='/api/soe', tags=['soe'], dependencies=[Depends(get_current_user)])


def _upload_to_out(record: SoeUploadRecord) -> SoeUploadOut:
    return SoeUploadOut(
        upload_id=record.id,
        file_name=record.file_name,
        mapped_rows=record.mapped_rows,
        issue_rows=record.issue_rows,
        uploaded_at=record.uploaded_at,
    )


@router.get('/uploads', response_model=list[SoeUploadOut])
def list_soe_uploads(repo: SoeRepository = Depends(get_soe_repository)):
    return [_upload_to_out(record) for record in repo.list_uploads()]


@router.post('/uploads', response_model=SoeUploadOut, status_code=201)
async def create_soe_upload(
    default_medium: str = Form('TV'),
    file: UploadFile = File(...),
    repo: SoeRepository = Depends(get_soe_repository),
):
    """Deliberately not nested under /api/projects/{project_id} -- this data
    is never attached to a project (or a brand, beyond the plain text a
    file's own Brand column supplies), so it never feeds the Matching
    Engine or a calculated GRP run. Reuses parse_composite_report() as-is:
    it already reads a per-row Brand column as plain text (with a
    filename-derived fallback when a row's Brand is blank), never resolving
    a Brand entity — exactly the shape this needs."""
    data = await file.read()
    file_name = file.filename or 'uploaded_file'
    try:
        parsed = parse_composite_report(data, file_name, default_medium)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    upload_record, _activity_records = repo.create_upload_with_activity(
        file_name, parsed.rows, issue_rows=parsed.issue_rows
    )
    return _upload_to_out(upload_record)


@router.delete('/uploads/{upload_id}', status_code=204)
def delete_soe_upload(
    upload_id: str,
    repo: SoeRepository = Depends(get_soe_repository),
    _current_user=Depends(require_role('owner', 'admin')),
):
    if not repo.delete_upload(upload_id):
        raise HTTPException(status_code=404, detail='Upload not found')


@router.get('/filters', response_model=SoeFilterOptionsOut)
def get_soe_filters(
    upload_id: Optional[str] = Query(default=None),
    repo: SoeRepository = Depends(get_soe_repository),
):
    options = repo.list_filter_options(upload_id=upload_id)
    return SoeFilterOptionsOut(
        mediums=options.mediums, stations=options.stations, regions=options.regions, days=options.days
    )


@router.get('', response_model=SoeReportOut)
def get_soe(
    upload_id: Optional[str] = Query(default=None),
    medium: List[str] = Query(default_factory=list),
    station: List[str] = Query(default_factory=list),
    region: List[str] = Query(default_factory=list),
    day: List[str] = Query(default_factory=list),
    date_from: Optional[date] = Query(default=None),
    date_to: Optional[date] = Query(default=None),
    repo: SoeRepository = Depends(get_soe_repository),
):
    """Share of Expenditure, filterable and computed live from soe_activity.
    Each repeated query param (e.g. ?medium=TV&medium=Radio) is OR'd within
    its own dimension; different dimensions AND together. upload_id scopes
    to one uploaded file -- the SOE Explorer analyzes a single upload at a
    time, never pools every upload ever made."""
    rows = repo.query_soe(
        upload_id=upload_id,
        mediums=medium or None,
        stations=station or None,
        regions=region or None,
        days=day or None,
        date_from=date_from,
        date_to=date_to,
    )
    total_spend = sum(row.spend for row in rows)
    brands = sorted(
        (
            SoeBrandOut(
                brand=row.brand,
                spend=row.spend,
                spots=row.spots,
                soe=(row.spend / total_spend * 100) if total_spend > 0 else 0.0,
            )
            for row in rows
        ),
        key=lambda b: b.spend,
        reverse=True,
    )
    return SoeReportOut(total_spend=total_spend, brands=brands)
