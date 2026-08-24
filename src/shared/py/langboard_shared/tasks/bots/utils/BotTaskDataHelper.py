from typing import Any, cast
from ....core.db import DbSession, SqlBuilder
from ....core.utils.decorators import staticclass
from ....domain.models import Bot, Card, CardRelationship, GlobalCardRelationshipType, Project, ProjectColumn, User


@staticclass
class BotTaskDataHelper:
    @staticmethod
    def create_executor(user_or_bot: User | Bot) -> dict[str, Any]:
        return {
            "executor": BotTaskDataHelper.create_user_or_bot(user_or_bot),
        }

    @staticmethod
    def create_project(user_or_bot: User | Bot, project: Project, data: dict | None = None) -> dict[str, Any]:
        return {
            "project_uid": project.get_uid(),
            "project_title": project.title,
            **BotTaskDataHelper.create_executor(user_or_bot),
            **(data or {}),
        }

    @staticmethod
    def create_project_column(user_or_bot: User | Bot, project: Project, column: ProjectColumn) -> dict[str, Any]:
        return BotTaskDataHelper.create_project(
            user_or_bot,
            project,
            {
                "project_column_uid": column.get_uid(),
                "project_column_name": column.name,
                "project_column_is_archive": column.is_archive,
            },
        )

    @staticmethod
    def create_card(
        user_or_bot: User | Bot, project: Project, card: Card, column: ProjectColumn | None = None
    ) -> dict[str, Any]:
        if not column:
            with DbSession.use(readonly=True) as db:
                result = db.exec(
                    SqlBuilder.select.table(ProjectColumn, with_deleted=True).where(
                        ProjectColumn.column("id") == card.project_column_id
                    )
                )
                column = cast(ProjectColumn, result.first())
        if not column:
            raise ValueError(f"Column with ID {card.project_column_id} not found in project {project.id}")
        return {
            **BotTaskDataHelper.create_project_column(user_or_bot, project, column),
            "card_uid": card.get_uid(),
            "card_title": card.title,
            "related_cards": BotTaskDataHelper.create_card_relationship_context(card),
        }

    @staticmethod
    def create_card_relationship_context(card: Card) -> dict[str, list[dict[str, Any]]]:
        return {
            "parents": BotTaskDataHelper.__create_related_card_list(card, "parent"),
            "children": BotTaskDataHelper.__create_related_card_list(card, "child"),
        }

    @staticmethod
    def __create_related_card_list(card: Card, relation: str) -> list[dict[str, Any]]:
        is_parent = relation == "parent"
        records: list[tuple[CardRelationship, GlobalCardRelationshipType, Card]] = []
        with DbSession.use(readonly=True) as db:
            records = db.exec(
                SqlBuilder.select.tables(CardRelationship, GlobalCardRelationshipType, Card)
                .join(
                    GlobalCardRelationshipType,
                    CardRelationship.column("relationship_type_id") == GlobalCardRelationshipType.column("id"),
                )
                .join(
                    Card,
                    CardRelationship.column("card_id_parent" if is_parent else "card_id_child") == Card.column("id"),
                )
                .where(
                    (CardRelationship.column("card_id_child" if is_parent else "card_id_parent") == card.id)
                    & (Card.column("id") != card.id)
                )
                .order_by(Card.column("created_at").asc(), Card.column("id").asc())
            ).all()

        return [
            {
                "card_uid": related_card.get_uid(),
                "title": related_card.title,
                "project_column_uid": related_card.project_column_id.to_short_code(),
                "archived_at": related_card.archived_at,
                "relationship_type_uid": relationship.relationship_type_id.to_short_code(),
                "relationship_name": relationship_type.parent_name if is_parent else relationship_type.child_name,
                "relationship_description": relationship_type.description,
            }
            for relationship, relationship_type, related_card in records
        ]

    @staticmethod
    def create_user_or_bot(user_or_bot: User | Bot) -> dict[str, Any]:
        response = user_or_bot.api_response()
        response["type"] = "bot" if isinstance(user_or_bot, Bot) else "user"
        return response

    @staticmethod
    def get_updated_assigned_bots(old_bot_ids: list[int], new_bot_ids: list[int]):
        first_time_assigned: list[int] = []
        for bot_id in new_bot_ids:
            if bot_id not in old_bot_ids:
                first_time_assigned.append(bot_id)

        records = []
        with DbSession.use(readonly=True) as db:
            result = db.exec(SqlBuilder.select.table(Bot).where(Bot.column("id").in_(first_time_assigned)))
            records = result.all()
        return records

    @staticmethod
    def get_column_by_card(card: Card) -> ProjectColumn | None:
        column = None
        with DbSession.use(readonly=True) as db:
            column = db.exec(
                SqlBuilder.select.table(ProjectColumn, with_deleted=True).where(
                    ProjectColumn.column("id") == card.project_column_id
                )
            )
            column = cast(ProjectColumn, column.first())
        return column
