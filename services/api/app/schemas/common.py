from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class CamelModel(BaseModel):
    """Base model that serializes snake_case fields as camelCase JSON,
    per the field-naming rule in API_CONTRACT.md."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, from_attributes=True)


class MappingWarningOut(CamelModel):
    """A saved mapping template disagreed with fresh column auto-detection
    for one field on this upload — see parsing.py's MappingWarning for why
    this matters (a stale template silently overriding a better match is a
    real, previously invisible cause of "0 matches"). Shared between the
    media-report and ratings upload responses (schemas/uploads.py,
    schemas/ratings.py), so it lives here rather than in either."""

    field: str
    template_column: str
    detected_column: str
