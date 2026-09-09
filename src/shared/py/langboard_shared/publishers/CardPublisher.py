from typing import Any, Literal
from ..core.publisher import BaseSocketPublisher, SocketPublishModel
from ..core.routing import SocketTopic
from ..core.utils.decorators import staticclass
from ..domain.models import Card, Checkitem, Project, ProjectColumn, ProjectLabel, User


@staticclass
class CardPublisher(BaseSocketPublisher):
    @staticmethod
    def linked_resource_changed(project: Project, card: Card):
        """Invalidate a linked card without publishing protected source data."""

        model = {"uid": card.get_uid()}
        event = f"board:card:linked-resource:changed:{card.get_uid()}"
        CardPublisher.put_dispather(
            model,
            [
                SocketPublishModel(
                    topic=SocketTopic.Board,
                    topic_id=project.get_uid(),
                    event=event,
                    data_keys="uid",
                ),
                SocketPublishModel(
                    topic=SocketTopic.BoardCard,
                    topic_id=card.get_uid(),
                    event=event,
                    data_keys="uid",
                ),
            ],
        )

    @staticmethod
    def created(project: Project, column: ProjectColumn, model: dict[str, Any]):
        topic_id = project.get_uid()
        publish_models = [
            SocketPublishModel(
                topic=SocketTopic.Board,
                topic_id=topic_id,
                event=f"board:card:created:{column.get_uid()}",
                data_keys="card",
            ),
            SocketPublishModel(
                topic=SocketTopic.Dashboard,
                topic_id=topic_id,
                event=f"dashboard:card:created:{topic_id}",
                custom_data={"project_column_uid": column.get_uid()},
            ),
        ]

        CardPublisher.put_dispather(model, publish_models)

    @staticmethod
    def updated(
        project: Project,
        card: Card,
        checkitem_cardified_from: Checkitem | None,
        model: dict[str, Any],
    ):
        topic_id = project.get_uid()
        card_uid = card.get_uid()
        publish_models = [
            SocketPublishModel(
                topic=SocketTopic.Board,
                topic_id=topic_id,
                event=f"board:card:details:changed:{card_uid}",
                data_keys=list(model.keys()),
            ),
        ]
        if checkitem_cardified_from:
            checkitem_uid = checkitem_cardified_from.get_uid()
            publish_models.extend(
                [
                    SocketPublishModel(
                        topic=SocketTopic.Dashboard,
                        topic_id=topic_id,
                        event=f"dashboard:card:title:changed:{topic_id}",
                        data_keys="title",
                        custom_data={"uid": card_uid},
                    ),
                    SocketPublishModel(
                        topic=SocketTopic.BoardCard,
                        topic_id=card_uid,
                        event=f"board:card:checkitem:title:changed:{checkitem_uid}",
                        data_keys="title",
                    ),
                    SocketPublishModel(
                        topic=SocketTopic.Dashboard,
                        topic_id=topic_id,
                        event=f"dashboard:checkitem:title:changed:{topic_id}",
                        data_keys="title",
                        custom_data={"uid": checkitem_uid},
                    ),
                ]
            )

        CardPublisher.put_dispather(model, publish_models)

    @staticmethod
    def order_changed(
        project: Project,
        card: Card,
        old_column: ProjectColumn,
        new_column: ProjectColumn | None,
    ):
        model = {
            "uid": card.get_uid(),
            "order": card.order,
            "archived_at": card.archived_at,
        }

        old_column_uid = old_column.get_uid()

        if new_column:
            new_column_uid = new_column.get_uid()
            model["to_column_uid"] = new_column_uid
            model["project_column_name"] = new_column.name

        publish_models: list[SocketPublishModel] = []
        topic_id = project.get_uid()
        card_uid = model["uid"]
        if new_column:
            publish_models.extend(
                [
                    SocketPublishModel(
                        topic=SocketTopic.Board,
                        topic_id=topic_id,
                        event=f"board:card:order:changed:{new_column_uid}",
                        data_keys=["uid", "order", "archived_at"],
                        custom_data={
                            "move_type": "to_column",
                            "column_uid": new_column_uid,
                        },
                    ),
                    SocketPublishModel(
                        topic=SocketTopic.Board,
                        topic_id=topic_id,
                        event=f"board:card:order:changed:{old_column_uid}",
                        custom_data={
                            "move_type": "from_column",
                            "column_uid": old_column_uid,
                        },
                    ),
                    SocketPublishModel(
                        topic=SocketTopic.BoardCard,
                        topic_id=card_uid,
                        event=f"board:card:order:changed:{card_uid}",
                        data_keys=["to_column_uid", "project_column_name", "archived_at"],
                    ),
                    SocketPublishModel(
                        topic=SocketTopic.Dashboard,
                        topic_id=topic_id,
                        event=f"dashboard:card:order:changed:{topic_id}",
                        data_keys=["to_column_uid", "project_column_name", "archived_at"],
                        custom_data={
                            "uid": card_uid,
                            "from_column_uid": old_column_uid,
                        },
                    ),
                ]
            )
        else:
            publish_models.append(
                SocketPublishModel(
                    topic=SocketTopic.Board,
                    topic_id=topic_id,
                    event=f"board:card:order:changed:{old_column_uid}",
                    data_keys=["uid", "order"],
                    custom_data={
                        "move_type": "in_column",
                        "column_uid": old_column_uid,
                    },
                )
            )

        CardPublisher.put_dispather(model, publish_models)

    @staticmethod
    def assigned_users_updated(project: Project, card: Card, users: list[User]):
        model = {"member_uids": [user.get_uid() for user in users]}
        publish_model = SocketPublishModel(
            topic=SocketTopic.Board,
            topic_id=project.get_uid(),
            event=f"board:card:assigned-users:updated:{card.get_uid()}",
            data_keys="member_uids",
        )

        CardPublisher.put_dispather(model, publish_model)

    @staticmethod
    def labels_updated(project: Project, card: Card, labels: list[ProjectLabel]):
        model = {"labels": [label.api_response() for label in labels]}
        publish_model = SocketPublishModel(
            topic=SocketTopic.Board,
            topic_id=project.get_uid(),
            event=f"board:card:labels:updated:{card.get_uid()}",
            data_keys="labels",
        )

        CardPublisher.put_dispather(model, publish_model)

    @staticmethod
    def deleted(project: Project, card: Card):
        topic_id = project.get_uid()
        card_uid = card.get_uid()
        column_uid = card.project_column_id.to_short_code()
        publish_models: list[SocketPublishModel] = [
            SocketPublishModel(
                topic=SocketTopic.Board,
                topic_id=topic_id,
                event=f"board:card:deleted:{card_uid}",
            ),
            SocketPublishModel(
                topic=SocketTopic.Dashboard,
                topic_id=topic_id,
                event=f"dashboard:card:deleted:{topic_id}",
                custom_data={
                    "uid": card_uid,
                    "project_column_uid": column_uid,
                },
            ),
        ]

        CardPublisher.put_dispather({}, publish_models)

    @staticmethod
    def bot_status_changed(project_uid: str, bot_uid: str, card_uid: str, status: Literal["running", "stopped"]):
        data = {
            "bot_uid": bot_uid,
            "card_uid": card_uid,
            "status": status,
        }

        publish_model = SocketPublishModel(
            topic=SocketTopic.Board,
            topic_id=project_uid,
            event=f"board:bot:status:changed:{project_uid}",
            data_keys=list(data.keys()),
        )

        CardPublisher.put_dispather(data, publish_model)
