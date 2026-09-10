from ....core.db import DbSession, SqlBuilder
from ....core.domain import BaseRepository
from ....core.types import SafeDateTime
from ....domain.models import WebhookSetting
from ....helpers import InfraHelper


class WebhookSettingRepository(BaseRepository[WebhookSetting]):
    @staticmethod
    def model_cls():
        return WebhookSetting

    @staticmethod
    def name() -> str:
        return "webhook_setting"

    def record_delivery_success(
        self,
        webhook: str,
        delivered_at: SafeDateTime,
    ) -> WebhookSetting | None:
        webhook_id = InfraHelper.convert_id(webhook)
        with DbSession.use(readonly=False) as db:
            updated_count = db.exec(
                SqlBuilder.update.table(WebhookSetting)
                .values(
                    {
                        WebhookSetting.column("last_used_at"): delivered_at,
                        WebhookSetting.column("total_used_count"): WebhookSetting.column("total_used_count") + 1,
                        WebhookSetting.column("updated_at"): delivered_at,
                    }
                )
                .where(WebhookSetting.column("id") == webhook_id)
            )
            if updated_count == 0:
                return None
            return db.exec(
                SqlBuilder.select.table(WebhookSetting).where(WebhookSetting.column("id") == webhook_id)
            ).first()
