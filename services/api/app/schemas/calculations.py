from datetime import date, datetime
from typing import Optional

from .common import CamelModel


class GrpRunSummaryOut(CamelModel):
    run_id: str
    project_id: str
    total_brands: int
    total_spots: int
    total_grps: float
    # Sum of resolved media spend across every activity row in this run,
    # matched or not — see BrandShareOut.total_spend / db/schema.sql's
    # comment on brand_shares.total_spend for why this differs from GRP.
    total_spend: float
    matched_rows: int
    unmatched_rows: int
    # True for the run currently shown as "latest" — the newest run unless a
    # version-history restore (POST .../versions/{versionId}/restore) pinned
    # it back to an older one. Not in API_CONTRACT.md's original field list;
    # added alongside Phase 3 version history.
    is_current: bool
    generated_at: datetime


class GrpCalculationRowOut(CamelModel):
    grp_calculation_id: str
    run_id: str
    media_activity_id: str
    brand_id: str
    brand: str  # joined in by the router, same pattern as BrandShareOut.brand
    station: str
    programme: str
    day: str
    medium: str
    spots: int
    rating: float
    grp: float
    calculated_at: datetime


class BrandShareOut(CamelModel):
    run_id: str
    brand_id: str
    brand: str  # joined in by the router (brand_shares doesn't itself store a name)
    total_grps: float
    tv_grps: float
    radio_grps: float
    sov: float
    spots: int
    avg_rating: Optional[float] = None
    # Share of Expenditure — brand spend / category spend, summed across
    # every one of the brand's media_activity rows regardless of match
    # status (unlike total_grps/sov, which only count matched rows).
    total_spend: float
    soe: float


class StationShareOut(CamelModel):
    run_id: str
    brand_id: str
    brand: str
    station: str
    total_grps: float
    spots: int


class ProgrammeShareOut(CamelModel):
    run_id: str
    brand_id: str
    brand: str
    programme: str
    total_grps: float
    spots: int


class TrendPointOut(CamelModel):
    run_id: str
    brand_id: str
    brand: str
    week_start: date
    total_grps: float
    spots: int
