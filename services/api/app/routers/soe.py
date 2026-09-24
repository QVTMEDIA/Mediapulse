from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query

from ..auth import get_current_user
from ..repositories.brands import BrandsRepository, get_brands_repository
from ..repositories.projects import ProjectsRepository, get_projects_repository
from ..repositories.uploads import UploadsRepository, get_uploads_repository
from ..schemas.soe import SoeBrandOut, SoeFilterOptionsOut, SoeReportOut

router = APIRouter(prefix='/api/projects/{project_id}/soe', tags=['soe'], dependencies=[Depends(get_current_user)])


def _brand_names(brands_repo: BrandsRepository, project_id: str) -> dict:
    """{brand_id: name} for every brand in the project -- one list_brands()
    call rather than one get_brand() per row; see routers/runs.py's
    identical helper for the full reasoning (found live: a project with a
    few thousand rows meant a few thousand sequential connections)."""
    return {brand.id: brand.name for brand in brands_repo.list_brands(project_id)}


@router.get('/filters', response_model=SoeFilterOptionsOut)
def get_soe_filters(
    project_id: str,
    upload_id: Optional[str] = Query(default=None),
    repo: UploadsRepository = Depends(get_uploads_repository),
    projects_repo: ProjectsRepository = Depends(get_projects_repository),
):
    if projects_repo.get_project(project_id) is None:
        raise HTTPException(status_code=404, detail='Project not found')
    options = repo.list_soe_filter_options(project_id, upload_id=upload_id)
    return SoeFilterOptionsOut(
        mediums=options.mediums, stations=options.stations, regions=options.regions, days=options.days
    )


@router.get('', response_model=SoeReportOut)
def get_soe(
    project_id: str,
    upload_id: Optional[str] = Query(default=None),
    medium: List[str] = Query(default_factory=list),
    station: List[str] = Query(default_factory=list),
    region: List[str] = Query(default_factory=list),
    day: List[str] = Query(default_factory=list),
    date_from: Optional[date] = Query(default=None),
    date_to: Optional[date] = Query(default=None),
    repo: UploadsRepository = Depends(get_uploads_repository),
    brands_repo: BrandsRepository = Depends(get_brands_repository),
    projects_repo: ProjectsRepository = Depends(get_projects_repository),
):
    """Share of Expenditure, filterable and computed live from
    media_activity -- distinct from Spend Intelligence's brand_shares
    snapshot (fixed at the last Calculate run, only three medium buckets):
    this recomputes on every request from whatever filters are given, so
    it works before a project has ever been calculated and supports
    arbitrary filter combinations rather than three fixed ones. Each
    repeated query param (e.g. ?medium=TV&medium=Radio) is OR'd within its
    own dimension; different dimensions AND together. upload_id scopes to
    one uploaded file -- the SOE Explorer analyzes a single upload at a
    time, never pools every upload a project has ever had."""
    if projects_repo.get_project(project_id) is None:
        raise HTTPException(status_code=404, detail='Project not found')
    rows = repo.query_soe(
        project_id,
        upload_id=upload_id,
        mediums=medium or None,
        stations=station or None,
        regions=region or None,
        days=day or None,
        date_from=date_from,
        date_to=date_to,
    )
    brand_names = _brand_names(brands_repo, project_id)
    total_spend = sum(row.spend for row in rows)
    brands = sorted(
        (
            SoeBrandOut(
                brand_id=row.brand_id,
                brand=brand_names.get(row.brand_id, 'Unknown brand'),
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
