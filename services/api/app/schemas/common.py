from pydantic import BaseModel, ConfigDict
from pydantic.alias_generators import to_camel


class CamelModel(BaseModel):
    """Base model that serializes snake_case fields as camelCase JSON,
    per the field-naming rule in API_CONTRACT.md."""

    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True, from_attributes=True)
