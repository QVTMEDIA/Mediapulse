from fastapi import APIRouter, Depends, HTTPException

from ..auth import get_current_user, require_role
from ..repositories.brands import BrandAlreadyExists, BrandRecord, BrandsRepository, get_brands_repository
from ..repositories.calculations import CalculationsRepository, get_calculations_repository
from ..repositories.matches import MatchesRepository, get_matches_repository
from ..repositories.projects import ProjectsRepository, get_projects_repository
from ..repositories.uploads import UploadsRepository, get_uploads_repository
from ..schemas.brands import BrandCreate, BrandOut

router = APIRouter(prefix='/api/projects/{project_id}/brands', tags=['brands'], dependencies=[Depends(get_current_user)])


def _to_out(record: BrandRecord) -> BrandOut:
    return BrandOut(brand_id=record.id, project_id=record.project_id, name=record.name, created_at=record.created_at)


@router.get('', response_model=list[BrandOut])
def list_brands(
    project_id: str,
    repo: BrandsRepository = Depends(get_brands_repository),
    projects_repo: ProjectsRepository = Depends(get_projects_repository),
):
    if projects_repo.get_project(project_id) is None:
        raise HTTPException(status_code=404, detail='Project not found')
    return [_to_out(record) for record in repo.list_brands(project_id)]


@router.post('', response_model=BrandOut, status_code=201)
def create_brand(
    project_id: str,
    payload: BrandCreate,
    repo: BrandsRepository = Depends(get_brands_repository),
    projects_repo: ProjectsRepository = Depends(get_projects_repository),
):
    if projects_repo.get_project(project_id) is None:
        raise HTTPException(status_code=404, detail='Project not found')
    try:
        record = repo.create_brand(project_id, payload)
    except BrandAlreadyExists as exc:
        raise HTTPException(status_code=409, detail=f'Brand "{exc}" already exists for this project') from exc
    return _to_out(record)


@router.delete('/{brand_id}', status_code=204)
def delete_brand(
    project_id: str,
    brand_id: str,
    repo: BrandsRepository = Depends(get_brands_repository),
    projects_repo: ProjectsRepository = Depends(get_projects_repository),
    uploads_repo: UploadsRepository = Depends(get_uploads_repository),
    matches_repo: MatchesRepository = Depends(get_matches_repository),
    calculations_repo: CalculationsRepository = Depends(get_calculations_repository),
    _current_user=Depends(require_role('owner', 'admin')),
):
    """Data-management action (PRODUCT_ROADMAP.md's Project Settings row).
    Same audit-trail guard as deleting an upload: refuses (409) if any of
    this brand's media_activity rows were ever included in a calculated
    run. Only removes this brand's media_activity rows, not the uploads
    that produced them — a composite_report upload can span several
    brands, so deleting one brand shouldn't take its siblings' data with it."""
    if projects_repo.get_project(project_id) is None:
        raise HTTPException(status_code=404, detail='Project not found')
    if repo.get_brand(project_id, brand_id) is None:
        raise HTTPException(status_code=404, detail='Brand not found for this project')
    activity_ids = [a.id for a in uploads_repo.list_media_activity(project_id) if a.brand_id == brand_id]
    if calculations_repo.has_calculations_for_media_activity(activity_ids):
        raise HTTPException(
            status_code=409,
            detail='This brand has already been included in a calculated run and cannot be deleted, '
            'to protect that run\'s audit trail.',
        )
    matches_repo.delete_matches_for_media_activity(activity_ids)
    uploads_repo.delete_media_activity_for_brand(project_id, brand_id)
    if not repo.delete_brand(project_id, brand_id):
        raise HTTPException(status_code=404, detail='Brand not found for this project')
