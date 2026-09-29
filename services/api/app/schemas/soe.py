from datetime import datetime
from typing import List

from .common import CamelModel


class SoeFilterOptionsOut(CamelModel):
    """Distinct values actually present in soe_activity -- what the SOE
    Explorer's filter dropdowns are populated from."""

    brands: List[str]
    mediums: List[str]
    stations: List[str]
    regions: List[str]
    states: List[str]
    days: List[str]


class SoeBrandOut(CamelModel):
    # No brandId -- this data has no project, so there's no Brand entity to
    # point at. `brand` is the vendor's own text from the file's Brand
    # column, taken as-is.
    brand: str
    spend: float
    spots: int
    # Percent of the filtered set's total spend, recomputed against
    # whatever filters were applied.
    soe: float


class SoeReportOut(CamelModel):
    total_spend: float
    brands: List[SoeBrandOut]


class SoeStationRowOut(CamelModel):
    """One row of a brand's "media buy details" drill-down -- what a click
    on a SoeBrandOut row opens."""

    station: str
    medium: str
    spend: float
    spots: int
    # Percent of this brand's own (filtered) total spend at this station --
    # distinct from SoeBrandOut.soe, which is share of every brand's spend.
    share: float


class SoeBrandDetailOut(CamelModel):
    brand: str
    total_spend: float
    total_spots: int
    stations: List[SoeStationRowOut]


class SoeUploadOut(CamelModel):
    upload_id: str
    file_name: str
    mapped_rows: int
    issue_rows: int
    uploaded_at: datetime
