from typing import Any, ClassVar
from sqlalchemy import TEXT
from ...core.db import ApiField, Field, SnowflakeIDField, SoftDeleteModel
from ...core.types import SnowflakeID
from .Project import Project


class ProjectColumn(SoftDeleteModel, table=True):
    DEFAULT_ARCHIVE_COLUMN_NAME: ClassVar[str] = "Archive"
    project_id: SnowflakeID = SnowflakeIDField(
        foreign_key=Project, nullable=False, index=True, api_field=ApiField(name="project_uid")
    )
    name: str = Field(nullable=False, api_field=ApiField())
    description: str = Field(default="", nullable=False, sa_type=TEXT, api_field=ApiField())
    order: int = Field(default=0, nullable=False, api_field=ApiField())
    is_archive: bool = Field(default=False, nullable=False, api_field=ApiField())

    def notification_data(self) -> dict[str, Any]:
        return {}

    def _get_repr_keys(self) -> list[str | tuple[str, str]]:
        return ["project_id", "name", "order", "is_archive"]
