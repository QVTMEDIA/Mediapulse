from datetime import datetime
from typing import Dict, Optional

from .common import CamelModel


class MappingTemplateOut(CamelModel):
    mapping_template_id: str
    source_label: str
    field_mapping: Dict[str, str]
    created_at: datetime
    last_used_at: Optional[datetime] = None


class MappingTemplateCreate(CamelModel):
    source_label: str
    field_mapping: Dict[str, str]
