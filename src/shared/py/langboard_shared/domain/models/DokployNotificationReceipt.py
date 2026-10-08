from sqlalchemy import UniqueConstraint
from ...core.db import BaseDbModel, Field, SnowflakeIDField
from .DokployWebhookBinding import DokployWebhookBinding


class DokployNotificationReceipt(BaseDbModel, table=True):
    """Append-only local channel evidence, without provider deployment identity."""

    __table_args__ = (
        UniqueConstraint("config_id", "config_revision", "payload_digest", name="uq_dokploy_notification_receipt"),
    )
    config_id: int = SnowflakeIDField(foreign_key=DokployWebhookBinding, nullable=False)
    config_revision: int = Field(nullable=False)
    payload_digest: str = Field(nullable=False)
    received_at: str = Field(nullable=False)
    notification_type: str = Field(nullable=False)
    status: str = Field(nullable=False)

    def notification_data(self):
        return {}

    def _get_repr_keys(self):
        return ["config_id", "config_revision", "notification_type", "status"]
