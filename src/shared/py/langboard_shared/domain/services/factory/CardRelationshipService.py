from typing import Any
from ....core.domain import BaseDomainService
from ....core.types import SnowflakeID
from ....core.types.ParamTypes import TCardParam, TProjectParam, TUserOrBot
from ....helpers import InfraHelper
from ....publishers import CardRelationshipPublisher
from ....tasks.activities import CardRelationshipActivityTask
from ....tasks.bots import CardBotTask
from ...models import Card, CardRelationship, Project


class CardRelationshipService(BaseDomainService):
    @staticmethod
    def name() -> str:
        """DO NOT EDIT THIS METHOD"""
        return "card_relationship"

    def get_api_list_by_card(self, card: TCardParam | None, limit: int | None = None) -> list[dict[str, Any]]:
        """Return relationships, optionally enforcing a repository row limit."""

        card = InfraHelper.get_by_id_like(Card, card)
        if not card:
            return []

        raw_relationships = self.repo.card_relationship.get_all_by_card(card, limit=limit)
        relationships = [relationship.api_response() for relationship, _ in raw_relationships]
        return relationships

    def get_api_list_by_by_project(self, project: TProjectParam | None) -> list[dict[str, Any]]:
        project = InfraHelper.get_by_id_like(Project, project)
        if not project:
            return []

        raw_relationships = self.repo.card_relationship.get_all_by_project(project)
        relationships = [relationship.api_response() for relationship, _ in raw_relationships]
        return relationships

    def update(
        self,
        user_or_bot: TUserOrBot,
        project: TProjectParam | None,
        card: TCardParam | None,
        is_parent: bool,
        relationships: list[tuple[str, str]],
    ) -> list[dict[str, Any]] | None:
        params = InfraHelper.get_records_with_foreign_by_params((Project, project), (Card, card))
        if not params:
            return None
        project, card = params

        old_relationships = self.repo.card_relationship.get_all_by_card_and_relation(
            card, relation="parent" if is_parent else "child"
        )
        old_relationship_ids = [relationship.id for relationship, _, _ in old_relationships]

        opposite_relationships = self.repo.card_relationship.get_all_by_card_and_relation(
            card, relation="child" if is_parent else "parent"
        )
        opposite_relationship_ids = [related_card.id for _, _, related_card in opposite_relationships]

        self.repo.card_relationship.delete_all_by_card_and_relation(card, relation="parent" if is_parent else "child")

        converted_related_card_ids: set[SnowflakeID] = set()
        relationship_type_ids: set[SnowflakeID] = set()
        converted_relationships: list[tuple[SnowflakeID, SnowflakeID]] = []
        for related_card_uid, relationship_type_uid in relationships:
            related_card_id = SnowflakeID.from_short_code(related_card_uid)
            relationship_type_id = SnowflakeID.from_short_code(relationship_type_uid)
            converted_related_card_ids.add(related_card_id)
            relationship_type_ids.add(relationship_type_id)
            converted_relationships.append((related_card_id, relationship_type_id))

        related_card_ids = self.repo.card_relationship.get_all_related_card_ids(
            project, list(converted_related_card_ids)
        )

        relationship_types = self.repo.card_relationship.get_global_relationship_types_map(list(relationship_type_ids))

        new_relationships_dict: dict[SnowflakeID, bool] = {}
        for related_card_id, relationship_type_id in converted_relationships:
            if (
                related_card_id not in related_card_ids
                or relationship_type_id not in relationship_types
                or related_card_id in new_relationships_dict
                or related_card_id in opposite_relationship_ids
            ):
                continue

            new_relationship = CardRelationship(
                relationship_type_id=relationship_type_id,
                card_id_parent=related_card_id if is_parent else card.id,
                card_id_child=card.id if is_parent else related_card_id,
            )
            self.repo.card_relationship.insert(new_relationship)
            api_relationship = relationship_types[relationship_type_id].api_response()
            api_relationship.pop("uid")
            new_relationships_dict[related_card_id] = True

        new_relationships = self.get_api_list_by_card(card)

        CardRelationshipPublisher.updated(project, card, new_relationships)
        CardRelationshipActivityTask.card_relationship_updated(
            user_or_bot,
            project,
            card,
            old_relationship_ids,
            list(new_relationships_dict.keys()),
            is_parent,
        )
        CardBotTask.card_relationship_updated(user_or_bot, project, card)

        return new_relationships
