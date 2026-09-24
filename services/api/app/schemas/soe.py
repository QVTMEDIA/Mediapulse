from typing import List

from .common import CamelModel


class SoeFilterOptionsOut(CamelModel):
    """Distinct values actually present in this project's media_activity --
    what the SOE Explorer's filter dropdowns are populated from."""

    mediums: List[str]
    stations: List[str]
    regions: List[str]
    days: List[str]


class SoeBrandOut(CamelModel):
    brand_id: str
    brand: str
    spend: float
    spots: int
    # Percent of the filtered set's total spend, not the whole project's --
    # recomputed against whatever filters were applied, unlike brand_shares.
    # soe from the calculated-run snapshot.
    soe: float


class SoeReportOut(CamelModel):
    total_spend: float
    brands: List[SoeBrandOut]
