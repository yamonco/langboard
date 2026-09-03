from typing import Any
from ....core.db import EditorContentModel
from ....core.domain import BaseDomainService
from ....core.types import SnowflakeID
from ....core.types.ParamTypes import TCardParam, TProjectParam, TUserOrBot
from ....helpers import InfraHelper
from ....publishers import CardPublisher, CardRelationshipPublisher
from ....tasks.activities import CardActivityTask, CardRelationshipActivityTask
from ....tasks.bots import CardBotTask
from ...models import Card, CardRelationship, Project, ProjectColumn


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

    def apply_graph_patch(
        self,
        user_or_bot: TUserOrBot,
        project: TProjectParam | None,
        anchor_card: TCardParam | None,
        new_cards: list[tuple[str, str, str | None]],
        add_edges: list[tuple[str, str, str]],
        remove_relationship_uids: list[str],
    ) -> dict[str, Any] | None:
        """Atomically create cards and patch typed relationships around an anchor card."""

        params = InfraHelper.get_records_with_foreign_by_params((Project, project), (Card, anchor_card))
        if not params:
            return None
        project, anchor_card = params
        if anchor_card.project_id != project.id:
            return None
        column = InfraHelper.get_by_id_like(ProjectColumn, anchor_card.project_column_id)
        if not column or column.project_id != project.id or column.is_archive:
            raise ValueError("Anchor card must be in an active project column")

        new_refs = {client_ref for client_ref, _, _ in new_cards}
        referenced = {ref for edge in add_edges for ref in edge[:2]}
        unknown_new_refs = sorted(ref for ref in referenced if ref.startswith("new:") and ref not in new_refs)
        if unknown_new_refs:
            raise ValueError(f"Unknown new card reference: {unknown_new_refs[0]}")

        existing_refs = {ref for ref in referenced if not ref.startswith("new:")}
        existing_refs.add(anchor_card.get_uid())
        existing_cards: dict[str, Card] = {}
        for card_uid in existing_refs:
            card = InfraHelper.get_by_id_like(Card, card_uid)
            if not card or card.project_id != project.id:
                raise ValueError(f"Unknown project card: {card_uid}")
            existing_cards[card_uid] = card

        raw_relationships = self.repo.card_relationship.get_all_by_project(project)
        relationship_by_uid = {relationship.get_uid(): relationship for relationship, _ in raw_relationships}
        remove_relationships: list[CardRelationship] = []
        for relationship_uid in remove_relationship_uids:
            relationship = relationship_by_uid.get(relationship_uid)
            if not relationship:
                raise ValueError(f"Unknown project relationship: {relationship_uid}")
            remove_relationships.append(relationship)

        relationship_type_ids = {
            SnowflakeID.from_short_code(relationship_type_uid) for _, _, relationship_type_uid in add_edges
        }
        relationship_types = self.repo.card_relationship.get_global_relationship_types_map(list(relationship_type_ids))
        if len(relationship_types) != len(relationship_type_ids):
            raise ValueError("Unknown relationship type")

        removed_ids = {relationship.id for relationship in remove_relationships}
        current_edges = {
            (relationship.card_id_parent, relationship.card_id_child)
            for relationship, _ in raw_relationships
            if relationship.id not in removed_ids
        }
        ref_ids = {uid: card.id for uid, card in existing_cards.items()}
        symbolic_edges: set[tuple[str | int, str | int]] = set(current_edges)
        for parent_ref, child_ref, _ in add_edges:
            parent: str | int = parent_ref if parent_ref in new_refs else ref_ids[parent_ref]
            child: str | int = child_ref if child_ref in new_refs else ref_ids[child_ref]
            if (parent, child) in symbolic_edges:
                raise ValueError("Relationship already exists")
            if self._has_path(symbolic_edges, child, parent):
                raise ValueError("Graph patch would create a relationship cycle")
            symbolic_edges.add((parent, child))

        anchor_id = anchor_card.id
        if new_refs and not self._all_connected(symbolic_edges, anchor_id, new_refs):
            raise ValueError("Every new card must connect to the anchor card")

        next_order = self.repo.card.get_next_order(column, {"project_id": project.id})
        cards_to_create = {
            client_ref: Card(
                project_id=project.id,
                project_column_id=column.id,
                title=title,
                description=EditorContentModel(content=description or ""),
                order=next_order + index,
            )
            for index, (client_ref, title, description) in enumerate(new_cards)
        }
        converted_edges = [
            (parent_ref, child_ref, SnowflakeID.from_short_code(relationship_type_uid))
            for parent_ref, child_ref, relationship_type_uid in add_edges
        ]
        created_relationships = self.repo.card_relationship.apply_graph_patch(
            cards_to_create,
            {uid: card.id for uid, card in existing_cards.items()},
            converted_edges,
            list(removed_ids),
        )

        created_cards = []
        for card in cards_to_create.values():
            api_card = card.board_api_response(0, [], [], [])
            created_cards.append(api_card)
            CardPublisher.created(project, column, {"card": api_card})
            CardActivityTask.card_created(user_or_bot, project, card)
            CardBotTask.card_created(user_or_bot, project, card)

        affected_ids = {
            relationship.card_id_parent for relationship in remove_relationships + created_relationships
        } | {relationship.card_id_child for relationship in remove_relationships + created_relationships}
        affected_cards = [
            card for card in [*existing_cards.values(), *cards_to_create.values()] if card.id in affected_ids
        ]
        for card in {card.id: card for card in affected_cards}.values():
            relationships = self.get_api_list_by_card(card)
            CardRelationshipPublisher.updated(project, card, relationships)
            CardBotTask.card_relationship_updated(user_or_bot, project, card)

        return {
            "anchor_card_uid": anchor_card.get_uid(),
            "created_cards": created_cards,
            "created_relationships": [relationship.api_response() for relationship in created_relationships],
            "removed_relationship_uids": remove_relationship_uids,
        }

    @staticmethod
    def _has_path(edges: set[tuple[str | int, str | int]], start: str | int, target: str | int) -> bool:
        """Return whether a directed path already reaches the target."""

        pending = [start]
        visited: set[str | int] = set()
        while pending:
            node = pending.pop()
            if node == target:
                return True
            if node in visited:
                continue
            visited.add(node)
            pending.extend(child for parent, child in edges if parent == node)
        return False

    @staticmethod
    def _all_connected(edges: set[tuple[str | int, str | int]], anchor: str | int, required: set[str]) -> bool:
        """Return whether every new request-local node joins the anchor component."""

        pending = [anchor]
        visited: set[str | int] = set()
        while pending:
            node = pending.pop()
            if node in visited:
                continue
            visited.add(node)
            pending.extend(right if left == node else left for left, right in edges if node in (left, right))
        return required <= visited
