from datetime import datetime, timezone
from typing import Any, Literal
from uuid import uuid4
from pydantic import BaseModel, Field
from ..types import SnowflakeID


def _convert_id_for_js(v: dict):
    for key, value in v.items():
        if isinstance(value, SnowflakeID):
            v[key] = str(value)
        elif isinstance(value, dict):
            v[key] = _convert_id_for_js(value)
        else:
            v[key] = value

    return v


class DispatcherModel(BaseModel):
    event: str
    data: dict[str, Any]

    class Config:
        json_encoders = {
            dict: _convert_id_for_js,
        }


class DispatcherEnvelope(BaseModel):
    schema_version: Literal["2"] = "2"
    event_id: str = Field(default_factory=lambda: str(uuid4()))
    event: str
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    data: dict[str, Any]
    cache_key: str | None = None
