from typing import Literal, Mapping, Sequence
from ....core.db import DbSession, SqlBuilder
from ....core.domain import BaseRepository
from ....core.types.ParamTypes import TCardParam, TGlobalCardRelationshipTypeParam, TProjectParam
from ....domain.models import Card, CardRelationship, GlobalCardRelationshipType, Project
from ....helpers import InfraHelper


class CardRelationshipRepository(BaseRepository[CardRelationship]):
    @staticmethod
    def model_cls():
        return CardRelationship

    @staticmethod
    def name() -> str:
        return "card_relationship"

    def get_all_by_card(
        self, card: TCardParam, limit: int | None = None
    ) -> list[tuple[CardRelationship, GlobalCardRelationshipType]]:
        """Return card relationships, optionally enforcing a database row limit."""

        card_id = InfraHelper.convert_id(card)

        relationships = []
        query = (
            SqlBuilder.select.tables(CardRelationship, GlobalCardRelationshipType)
            .join(
                GlobalCardRelationshipType,
                CardRelationship.column("relationship_type_id") == GlobalCardRelationshipType.column("id"),
            )
            .where(
                (CardRelationship.column("card_id_parent") == card_id)
                | (CardRelationship.column("card_id_child") == card_id)
            )
            .order_by(CardRelationship.column("id").asc())
        )
        if limit is not None:
            query = query.limit(limit)
        with DbSession.use(readonly=True) as db:
            result = db.exec(query)
            relationships = result.all()
        return relationships

    def get_all_by_project(self, project: TProjectParam) -> list[tuple[CardRelationship, GlobalCardRelationshipType]]:
        project_id = InfraHelper.convert_id(project)

        relationships = []
        with DbSession.use(readonly=True) as db:
            result = db.exec(
                SqlBuilder.select.tables(CardRelationship, GlobalCardRelationshipType)
                .join(
                    GlobalCardRelationshipType,
                    CardRelationship.column("relationship_type_id") == GlobalCardRelationshipType.column("id"),
                )
                .join(
                    Card,
                    CardRelationship.column("card_id_parent") == Card.column("id"),
                )
                .join(Project, (Card.column("project_id") == Project.column("id")))
                .where(Project.column("id") == project_id)
            )
            relationships = result.all()
        return relationships

    def get_graph_snapshot(self, project: TProjectParam) -> list[tuple[int, int, int]]:
        """Return only relationship and endpoint IDs needed for graph validation."""

        project_id = InfraHelper.convert_id(project)
        query = (
            SqlBuilder.select.columns(
                CardRelationship.column("id"),
                CardRelationship.column("card_id_parent"),
                CardRelationship.column("card_id_child"),
            )
            .join(Card, CardRelationship.column("card_id_parent") == Card.column("id"))
            .where(Card.column("project_id") == project_id)
        )
        with DbSession.use(readonly=True) as db:
            return db.exec(query).all()

    def get_all_by_card_and_relation(
        self, card: TCardParam, relation: Literal["parent", "child"]
    ) -> list[tuple[CardRelationship, GlobalCardRelationshipType, Card]]:
        card_id = InfraHelper.convert_id(card)
        is_parent = relation == "parent"

        records = []
        with DbSession.use(readonly=True) as db:
            result = db.exec(
                SqlBuilder.select.tables(CardRelationship, GlobalCardRelationshipType, Card)
                .join(
                    GlobalCardRelationshipType,
                    CardRelationship.column("relationship_type_id") == GlobalCardRelationshipType.column("id"),
                )
                .join(
                    Card,
                    (CardRelationship.column("card_id_parent" if is_parent else "card_id_child") == Card.column("id")),
                )
                .where(
                    (CardRelationship.column("card_id_child" if is_parent else "card_id_parent") == card_id)
                    & (Card.column("id") != card_id)
                )
            )
            records = result.all()

        return records

    def get_all_related_card_ids(self, project: TProjectParam, cards: Sequence[TCardParam] | None = None):
        project_id = InfraHelper.convert_id(project)
        query = SqlBuilder.select.column(Card.id).where(Card.column("project_id") == project_id)

        if cards is not None:
            if not isinstance(cards, Sequence) or isinstance(cards, str):
                cards = [cards]
            converted_ids = [InfraHelper.convert_id(card) for card in cards]
            query = query.where(Card.column("id").in_(converted_ids))

        card_ids = set()
        with DbSession.use(readonly=True) as db:
            result = db.exec(query)
            card_ids = set(result.all())
        return list(card_ids)

    def get_global_relationship_types_map(self, relationship_types: Sequence[TGlobalCardRelationshipTypeParam]):
        converted_ids = [InfraHelper.convert_id(relationship_type) for relationship_type in relationship_types]
        types_map = {}
        with DbSession.use(readonly=True) as db:
            result = db.exec(
                SqlBuilder.select.table(GlobalCardRelationshipType).where(
                    GlobalCardRelationshipType.column("id").in_(converted_ids)
                )
            )
            types_map = {relationship_type.id: relationship_type for relationship_type in result.all()}
        return types_map

    def delete_all_by_card_and_relation(self, card: TCardParam, relation: Literal["parent", "child"]) -> None:
        card_id = InfraHelper.convert_id(card)
        is_parent = relation == "parent"

        with DbSession.use(readonly=False) as db:
            db.exec(
                SqlBuilder.delete.table(CardRelationship).where(
                    CardRelationship.column("card_id_child" if is_parent else "card_id_parent") == card_id
                )
            )

    def delete_all_by_card(self, card: TCardParam) -> None:
        card_id = InfraHelper.convert_id(card)

        with DbSession.use(readonly=False) as db:
            db.exec(
                SqlBuilder.delete.table(CardRelationship).where(
                    (CardRelationship.column("card_id_parent") == card_id)
                    | (CardRelationship.column("card_id_child") == card_id)
                )
            )

    def apply_graph_patch(
        self,
        new_cards: Mapping[str, Card],
        existing_card_ids: Mapping[str, int],
        add_edges: Sequence[tuple[str, str, int]],
        remove_relationship_ids: Sequence[int],
    ) -> list[CardRelationship]:
        """Persist one validated card-and-relationship patch in one transaction."""

        created_relationships: list[CardRelationship] = []
        with DbSession.use(readonly=False) as db:
            if remove_relationship_ids:
                db.exec(
                    SqlBuilder.delete.table(CardRelationship).where(
                        CardRelationship.column("id").in_(remove_relationship_ids)
                    )
                )
            if new_cards:
                db.insert_all(new_cards.values())

            card_ids = {**existing_card_ids, **{ref: card.id for ref, card in new_cards.items()}}
            created_relationships = [
                CardRelationship(
                    relationship_type_id=relationship_type_id,
                    card_id_parent=card_ids[parent_ref],
                    card_id_child=card_ids[child_ref],
                )
                for parent_ref, child_ref, relationship_type_id in add_edges
            ]
            if created_relationships:
                db.insert_all(created_relationships)
        return created_relationships
