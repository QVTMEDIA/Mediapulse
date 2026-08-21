from datetime import datetime

from pydantic import Field

from .common import CamelModel


class BrandCreate(CamelModel):
    name: str = Field(min_length=1)


class BrandOut(CamelModel):
    brand_id: str
    project_id: str
    name: str
    created_at: datetime
