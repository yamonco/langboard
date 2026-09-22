from typing import Any, Mapping
from ..core.publisher import BaseSocketPublisher, SocketPublishModel
from ..core.routing import SettingSocketTopicID, SocketTopic
from ..core.types import SnowflakeID
from ..core.utils.decorators import staticclass
from ..domain.models import User


@staticclass
class UserPublisher(BaseSocketPublisher):
    @staticmethod
    def updated(user: User, model: dict[str, Any]):
        topic_id = user.get_uid()
        publish_model = SocketPublishModel(
            topic=SocketTopic.User,
            topic_id=topic_id,
            event="user:updated",
            data_keys=list(model.keys()),
        )

        UserPublisher.put_dispather(model, publish_model)

    @staticmethod
    def deactivated(user: User):
        topic_id = user.get_uid()
        publish_model = SocketPublishModel(
            topic=SocketTopic.UserPrivate,
            topic_id=topic_id,
            event=f"user:deactivated:{topic_id}",
            data_keys=[],
        )

        UserPublisher.put_dispather({}, publish_model)

    @staticmethod
    def notified(user: User, notification: dict[str, Any]):
        publish_model = SocketPublishModel(
            topic=SocketTopic.UserPrivate,
            topic_id=user.get_uid(),
            event="user:notified",
            data_keys=["notification"],
        )
        UserPublisher.put_dispather({"notification": notification}, publish_model)

    @staticmethod
    def notification_mutated(user: User, mutation: Mapping[str, Any]):
        data = dict(mutation)
        publish_model = SocketPublishModel(
            topic=SocketTopic.UserPrivate,
            topic_id=user.get_uid(),
            event="user:notification:mutated",
            data_keys=list(data),
        )
        UserPublisher.put_dispather(data, publish_model)

    @staticmethod
    def api_key_roles_updated(user_uid: str, roles: list[str]):
        publish_models = [
            SocketPublishModel(
                topic=SocketTopic.UserPrivate,
                topic_id=user_uid,
                event=f"user:api-key-roles:updated:{user_uid}",
                data_keys=["roles"],
            ),
            SocketPublishModel(
                topic=SocketTopic.AppSettings,
                topic_id=SettingSocketTopicID.User.value,
                event=f"user:api-key-roles:updated:{user_uid}",
                data_keys=["roles"],
            ),
        ]

        UserPublisher.put_dispather({"roles": roles}, publish_models)

    @staticmethod
    def setting_roles_updated(user_uid: str, roles: list[str]):
        publish_models = [
            SocketPublishModel(
                topic=SocketTopic.UserPrivate,
                topic_id=user_uid,
                event=f"user:setting-roles:updated:{user_uid}",
                data_keys=["roles"],
            ),
            SocketPublishModel(
                topic=SocketTopic.AppSettings,
                topic_id=SettingSocketTopicID.User.value,
                event=f"user:setting-roles:updated:{user_uid}",
                data_keys=["roles"],
            ),
        ]

        UserPublisher.put_dispather({"roles": roles}, publish_models)

    @staticmethod
    def mcp_roles_updated(user_uid: str, roles: list[str]):
        publish_models = [
            SocketPublishModel(
                topic=SocketTopic.UserPrivate,
                topic_id=user_uid,
                event=f"user:mcp-roles:updated:{user_uid}",
                data_keys=["roles"],
            ),
            SocketPublishModel(
                topic=SocketTopic.AppSettings,
                topic_id=SettingSocketTopicID.User.value,
                event=f"user:mcp-roles:updated:{user_uid}",
                data_keys=["roles"],
            ),
        ]

        UserPublisher.put_dispather({"roles": roles}, publish_models)

    @staticmethod
    def deleted(user: User | SnowflakeID):
        if isinstance(user, User):
            topic_id = user.get_uid()
        else:
            topic_id = user.to_short_code()
        publish_models = [
            SocketPublishModel(
                topic=SocketTopic.UserPrivate,
                topic_id=topic_id,
                event=f"user:deleted:{topic_id}",
                data_keys=[],
            ),
            SocketPublishModel(
                topic=SocketTopic.User,
                topic_id=topic_id,
                event=f"user:deleted:{topic_id}",
                data_keys=[],
            ),
        ]

        UserPublisher.put_dispather({}, publish_models)
