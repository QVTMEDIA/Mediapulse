from datetime import datetime

from pydantic import Field

from .common import CamelModel


class StationAliasCreate(CamelModel):
    alias_name: str = Field(min_length=1)
    canonical_name: str = Field(min_length=1)


class StationAliasOut(CamelModel):
    station_alias_id: str
    alias_name: str
    canonical_name: str
    created_by_name: str
    created_at: datetime
