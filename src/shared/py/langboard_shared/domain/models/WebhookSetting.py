from typing import Any
from sqlalchemy import TEXT
from ...core.db import ApiField, BaseDbModel, DateTimeField, Field
from ...core.types import SafeDateTime


class WebhookSetting(BaseDbModel, table=True):
    name: str = Field(nullable=False, api_field=ApiField())
    url: str = Field(nullable=False, sa_type=TEXT, api_field=ApiField())
    secret_id: str | None = Field(default=None, nullable=True)
    last_used_at: SafeDateTime | None = DateTimeField(default=None, nullable=True, api_field=ApiField())
    total_used_count: int = Field(default=0, nullable=False, api_field=ApiField())

    def notification_data(self) -> dict[str, Any]:
        return {}

    def _get_repr_keys(self) -> list[str | tuple[str, str]]:
        return []
