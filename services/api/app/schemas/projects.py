from datetime import date, datetime
from typing import List, Optional

from pydantic import Field, field_validator

from .common import CamelModel

PROJECT_STATUS_OPTIONS = ('Setup', 'Data Review', 'Complete')
MEDIA_TYPE_OPTIONS = ('TV', 'Radio')


def _validate_status(value: Optional[str]) -> Optional[str]:
    if value is not None and value not in PROJECT_STATUS_OPTIONS:
        raise ValueError(f'status must be one of {PROJECT_STATUS_OPTIONS}')
    return value


def _validate_media_types(value: Optional[List[str]]) -> Optional[List[str]]:
    if value is not None:
        unknown = [media for media in value if media not in MEDIA_TYPE_OPTIONS]
        if unknown:
            raise ValueError(f'unsupported media types: {unknown}. Allowed: {MEDIA_TYPE_OPTIONS}')
    return value


class ProjectCreate(CamelModel):
    project_name: str = Field(min_length=1)
    project_owner: str = ''
    client: str = ''
    category: str = ''
    market: str = ''
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    target_audience: str = ''
    media_types: List[str] = Field(default_factory=list)
    ratings_provider: str = ''
    ratings_period: str = ''
    status: str = 'Setup'
    notes: str = ''

    _check_status = field_validator('status')(_validate_status)
    _check_media_types = field_validator('media_types')(_validate_media_types)


class ProjectUpdate(CamelModel):
    project_name: Optional[str] = Field(default=None, min_length=1)
    project_owner: Optional[str] = None
    client: Optional[str] = None
    category: Optional[str] = None
    market: Optional[str] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    target_audience: Optional[str] = None
    media_types: Optional[List[str]] = None
    ratings_provider: Optional[str] = None
    ratings_period: Optional[str] = None
    status: Optional[str] = None
    archived: Optional[bool] = None
    notes: Optional[str] = None

    _check_status = field_validator('status')(_validate_status)
    _check_media_types = field_validator('media_types')(_validate_media_types)


class ProjectOut(CamelModel):
    project_id: str
    project_name: str
    project_owner: str
    client: str
    category: str
    market: str
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    target_audience: str
    media_types: List[str]
    ratings_provider: str
    ratings_period: str
    status: str
    archived: bool
    notes: str
    created_at: datetime
    updated_at: datetime
