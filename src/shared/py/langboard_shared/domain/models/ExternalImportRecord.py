from typing import Any
from sqlalchemy import TEXT
from ...core.db import BaseDbModel, Field, SnowflakeIDField
from ...core.types import SafeDateTime, SnowflakeID
from .Project import Project


class ExternalImportRecord(BaseDbModel, table=True):
    """Durable, provider-neutral lineage for one imported record."""

    project_id: SnowflakeID = SnowflakeIDField(
        foreign_key=Project,
        nullable=False,
        index=True,
        unique_groups=("source_record",),
    )
    source_namespace: str = Field(nullable=False, index=True, unique_groups=("source_record",))
    source_container_id: str = Field(nullable=False, unique_groups=("source_record",))
    record_type: str = Field(nullable=False, index=True, unique_groups=("source_record",))
    source_record_id: str = Field(nullable=False, unique_groups=("source_record",))
    target_type: str = Field(nullable=False)
    target_uid: str = Field(nullable=False)
    source_fingerprint: str = Field(nullable=False)
    batch_id: str = Field(nullable=False, index=True)
    provenance: str = Field(default="{}", nullable=False, sa_type=TEXT)
    effects_dispatched_at: SafeDateTime | None = Field(default=None, nullable=True)
    effects_attempts: int = Field(default=0, nullable=False)
    effects_error: str | None = Field(default=None, nullable=True, sa_type=TEXT)

    def notification_data(self) -> dict[str, Any]:
        return {}

    def _get_repr_keys(self) -> list[str | tuple[str, str]]:
        return [
            "project_id",
            "source_namespace",
            "source_container_id",
            "record_type",
            "source_record_id",
            "target_type",
            "target_uid",
            "batch_id",
        ]
