from typing import Literal
from ..core.publisher import BaseSocketPublisher, SocketPublishModel
from ..core.routing import SocketTopic
from ..core.types import SafeDateTime
from ..core.utils.decorators import staticclass
from ..domain.models import Project, ProjectColumn


@staticclass
class ProjectColumnPublisher(BaseSocketPublisher):
    @staticmethod
    def created(project: Project, column: ProjectColumn):
        model = {
            "column": {
                **column.api_response(),
                "count": 0,
            }
        }

        topic_id = project.get_uid()
        publish_models = [
            SocketPublishModel(
                topic=SocketTopic.Board,
                topic_id=topic_id,
                event=f"board:column:created:{topic_id}",
                data_keys="column",
            ),
            SocketPublishModel(
                topic=SocketTopic.Dashboard,
                topic_id=topic_id,
                event=f"dashboard:project:column:created:{topic_id}",
                data_keys="column",
            ),
        ]

        ProjectColumnPublisher.put_dispather(model, publish_models)

    @staticmethod
    def name_changed(project: Project, column: ProjectColumn, name: str):
        model = {
            "uid": column.get_uid(),
            "name": name,
        }

        topic_id = project.get_uid()
        publish_models = [
            SocketPublishModel(
                topic=SocketTopic.Board,
                topic_id=topic_id,
                event=f"board:column:name:changed:{topic_id}",
                data_keys=list(model.keys()),
            ),
            SocketPublishModel(
                topic=SocketTopic.Dashboard,
                topic_id=topic_id,
                event=f"dashboard:project:column:name:changed:{topic_id}",
                data_keys=list(model.keys()),
            ),
        ]

        ProjectColumnPublisher.put_dispather(model, publish_models)

    @staticmethod
    def description_changed(project: Project, column: ProjectColumn) -> None:
        """Publish guidance changes without impersonating a rename or moving cards."""
        model = {"uid": column.get_uid(), "description": column.description}
        topic_id = project.get_uid()
        ProjectColumnPublisher.put_dispather(
            model,
            [
                SocketPublishModel(
                    topic=SocketTopic.Board,
                    topic_id=topic_id,
                    event=f"board:column:description:changed:{topic_id}",
                    data_keys=list(model.keys()),
                ),
                SocketPublishModel(
                    topic=SocketTopic.Dashboard,
                    topic_id=topic_id,
                    event=f"dashboard:project:column:description:changed:{topic_id}",
                    data_keys=list(model.keys()),
                ),
            ],
        )

    @staticmethod
    def order_changed(project: Project, column: ProjectColumn):
        model = {
            "uid": column.get_uid(),
            "order": column.order,
        }

        topic_id = project.get_uid()
        publish_models = [
            SocketPublishModel(
                topic=SocketTopic.Board,
                topic_id=topic_id,
                event=f"board:column:order:changed:{topic_id}",
                data_keys=list(model.keys()),
            ),
            SocketPublishModel(
                topic=SocketTopic.Dashboard,
                topic_id=topic_id,
                event=f"dashboard:project:column:order:changed:{topic_id}",
                data_keys=list(model.keys()),
            ),
        ]

        ProjectColumnPublisher.put_dispather(model, publish_models)

    @staticmethod
    def deleted(
        project: Project,
        column: ProjectColumn,
        archive_column: ProjectColumn,
        archived_at: SafeDateTime,
        count_all_cards_in_column: int,
    ):
        column_uid = column.get_uid()
        model = {
            "uid": column_uid,
            "archive_column_uid": archive_column.get_uid(),
            "archive_column_name": archive_column.name,
            "archived_at": archived_at,
            "count_all_cards_in_column": count_all_cards_in_column,
        }

        topic_id = project.get_uid()
        publish_models = [
            SocketPublishModel(
                topic=SocketTopic.Board,
                topic_id=topic_id,
                event=f"board:column:deleted:{column_uid}",
                data_keys=list(model.keys()),
            ),
            SocketPublishModel(
                topic=SocketTopic.Dashboard,
                topic_id=topic_id,
                event=f"dashboard:project:column:deleted:{topic_id}",
                data_keys=list(model.keys()),
            ),
        ]

        ProjectColumnPublisher.put_dispather(model, publish_models)

    @staticmethod
    def bot_status_changed(project_uid: str, bot_uid: str, column_uid: str, status: Literal["running", "stopped"]):
        data = {
            "bot_uid": bot_uid,
            "project_column_uid": column_uid,
            "status": status,
        }

        publish_model = SocketPublishModel(
            topic=SocketTopic.Board,
            topic_id=project_uid,
            event=f"board:bot:status:changed:{project_uid}",
            data_keys=list(data.keys()),
        )

        ProjectColumnPublisher.put_dispather(data, publish_model)
