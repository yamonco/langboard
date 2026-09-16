from ....core.domain import BaseRepository
from ....domain.models import WebhookSetting


class WebhookSettingRepository(BaseRepository[WebhookSetting]):
    @staticmethod
    def model_cls():
        return WebhookSetting

    @staticmethod
    def name() -> str:
        return "webhook_setting"
