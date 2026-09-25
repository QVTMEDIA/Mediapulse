from datetime import datetime
from typing import List

from .common import CamelModel


class SoeFilterOptionsOut(CamelModel):
    """Distinct values actually present in soe_activity -- what the SOE
    Explorer's filter dropdowns are populated from."""

    mediums: List[str]
    stations: List[str]
    regions: List[str]
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


class SoeUploadOut(CamelModel):
    upload_id: str
    file_name: str
    mapped_rows: int
    issue_rows: int
    uploaded_at: datetime
