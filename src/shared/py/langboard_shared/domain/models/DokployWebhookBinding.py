from sqlalchemy import CheckConstraint, UniqueConstraint
from sqlalchemy.schema import conv
from ...core.db import BaseDbModel, Field, SnowflakeIDField
from .AppConnection import AppConnection
from .BoardAppBinding import BoardAppBinding


class DokployWebhookBinding(BaseDbModel, table=True):
    """Board-owned receiver configuration; credential material stays in the vault."""

    __table_args__ = (
        UniqueConstraint("board_binding_id", "connection_id", name="uq_dokploy_webhook_binding"),
        CheckConstraint("state IN ('enabled','disabled')", name=conv("ck_dokploy_webhook_state")),
    )
    board_binding_id: int = SnowflakeIDField(foreign_key=BoardAppBinding, nullable=False)
    connection_id: int = SnowflakeIDField(foreign_key=AppConnection, nullable=False)
    credential_reference: str = Field(nullable=False)
    secret_revision: int = Field(nullable=False)
    connection_revision: str = Field(nullable=False)
    binding_revision: str = Field(nullable=False)
    resource_revision: str = Field(nullable=False)
    notification_id: str | None = Field(default=None, nullable=True)
    config_revision: int = Field(default=1, nullable=False)
    state: str = Field(default="enabled", nullable=False)

    def notification_data(self):
        return {}

    def _get_repr_keys(self):
        return ["board_binding_id", "connection_id", "state", "config_revision"]
