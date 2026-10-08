"""One server-owned, revision-bound graph/cardification/checklist work plan."""

from hashlib import sha256
from json import dumps, loads
from typing import Annotated, Any
from langboard_shared.core.db import DbSession
from langboard_shared.core.routing import SocketTopic
from langboard_shared.core.security.CollaborationChannel import CollaborationChannel
from langboard_shared.domain.constants.CardPresentation import CARD_PRESENTATION_KEY, validate_card_presentation
from langboard_shared.domain.models import (
    Card,
    CardMetadata,
    Checkitem,
    Checklist,
    GlobalCardRelationshipType,
    Project,
    ProjectColumn,
)
from langboard_shared.publishers import MetadataPublisher
from pydantic import BaseModel, ConfigDict, Field, TypeAdapter, field_validator, model_serializer, model_validator
from sqlalchemy import select


Text = Annotated[str, Field(min_length=1, max_length=500)]
Ref = Annotated[str, Field(min_length=1, max_length=80)]


class PlanModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class PlanCard(PlanModel):
    client_ref: Ref
    title: Text
    description: Annotated[str, Field(max_length=16000)] | None = None
    presentation: dict[str, Any] | None = Field(
        default=None,
        description=(
            "Optional card.presentation.v1 display metadata: version=1, key=app.<app>.<kind>, "
            "axis=type or origin, English name/description, optional icon/translations. Never changes policy."
        ),
    )

    @field_validator("presentation")
    @classmethod
    def validate_presentation(cls, value):
        if value is not None:
            validate_card_presentation(dumps(value, ensure_ascii=False, separators=(",", ":")))
        return value

    @model_serializer(mode="wrap")
    def serialize_card(self, handler):
        result = handler(self)
        # Preserve revisions/receipt digests for pre-existing plans without traits.
        if self.presentation is None:
            result.pop("presentation", None)
        return result


class PlanEdge(PlanModel):
    parent_ref: Ref
    child_ref: Ref
    relationship_type_uid: Ref


class PlanCardification(PlanModel):
    client_ref: Ref
    source_card_uid: Ref
    checkitem_uid: Ref
    project_column_uid: Ref
    title: Text


class PlanChecklist(PlanModel):
    target_card_ref: Ref
    title: Text
    items: Annotated[list[Text], Field(min_length=1, max_length=25)]


class WorkPlan(PlanModel):
    project_uid: Ref
    anchor_card_uid: Ref
    new_cards: Annotated[list[PlanCard], Field(max_length=7)] = Field(default_factory=list)
    add_edges: Annotated[list[PlanEdge], Field(max_length=25)] = Field(default_factory=list)
    remove_relationship_uids: Annotated[list[Ref], Field(max_length=25)] = Field(default_factory=list)
    cardify_checkitems: Annotated[list[PlanCardification], Field(max_length=7)] = Field(default_factory=list)
    new_checklists: Annotated[list[PlanChecklist], Field(max_length=12)] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_plan(self):
        if not any(
            (
                self.new_cards,
                self.add_edges,
                self.remove_relationship_uids,
                self.cardify_checkitems,
                self.new_checklists,
            )
        ):
            raise ValueError("Work plan contains no changes")
        refs = [c.client_ref for c in self.new_cards] + [c.client_ref for c in self.cardify_checkitems]
        if len(refs) != len(set(refs)):
            raise ValueError("Duplicate created card reference")
        if any(not c.client_ref.startswith("new:") or not c.client_ref[4:] for c in self.new_cards):
            raise ValueError("New card references must start with new:")
        if any(not c.client_ref.startswith("cardify:") or not c.client_ref[8:] for c in self.cardify_checkitems):
            raise ValueError("Cardification references must start with cardify:")
        ids = [c.checkitem_uid for c in self.cardify_checkitems]
        if len(ids) != len(set(ids)):
            raise ValueError("A checkitem may be cardified only once")
        if len(self.add_edges) + len(self.remove_relationship_uids) > 25:
            raise ValueError("Too many relationship changes")
        declared = set(refs)
        referenced = {c.target_card_ref for c in self.new_checklists}
        referenced |= {r for e in self.add_edges for r in (e.parent_ref, e.child_ref)}
        if any(r.startswith(("new:", "cardify:")) and r not in declared for r in referenced):
            raise ValueError("Unknown created card reference")
        edges = [(e.parent_ref, e.child_ref, e.relationship_type_uid) for e in self.add_edges]
        if len(edges) != len(set(edges)) or len(self.remove_relationship_uids) != len(
            set(self.remove_relationship_uids)
        ):
            raise ValueError("Duplicate relationship change")
        return self


class WorkPlanService:
    def __init__(self, actor, service):
        self.actor, self.service = actor, service

    def _card(self, uid, project):
        resolved = self.service.card.resolve_readable_card(project, uid, self.actor, CollaborationChannel.Mcp)
        card = resolved[1] if resolved else None
        if not card or card.project_id != project.id or card.archived_at or card.deleted_at or card.is_linked_resource:
            raise ValueError("Work plan card is unavailable")
        return card

    def _preview(self, plan):
        service = self.service
        project = service.project.get_by_id_like(plan.project_uid)
        if not project:
            raise ValueError("Project is unavailable")
        with DbSession.use(readonly=False) as db:
            if (
                db.exec(
                    select(Project.column("id")).where(Project.column("id") == project.id).with_for_update()
                ).first()
                is None
            ):
                raise ValueError("Project is unavailable")
        symbolic = {c.client_ref for c in plan.new_cards} | {c.client_ref for c in plan.cardify_checkitems}
        refs = {plan.anchor_card_uid} | {c.source_card_uid for c in plan.cardify_checkitems}
        refs |= {c.target_card_ref for c in plan.new_checklists if c.target_card_ref not in symbolic}
        refs |= {ref for e in plan.add_edges for ref in (e.parent_ref, e.child_ref) if ref not in symbolic}
        cards = {uid: self._card(uid, project) for uid in refs}
        with DbSession.use(readonly=False) as db:
            card_ids = sorted(c.id for c in cards.values())
            db.exec(
                select(Card.column("id"))
                .where(Card.column("id").in_(card_ids))
                .order_by(Card.column("id"))
                .with_for_update()
            ).all()
            checklist_rows = db.exec(
                select(Checklist.column("id"))
                .where(Checklist.column("card_id").in_(card_ids))
                .order_by(Checklist.column("id"))
                .with_for_update()
            ).all()
            checklist_ids = [r[0] if isinstance(r, tuple) else r for r in checklist_rows]
            if checklist_ids:
                db.exec(
                    select(Checkitem.column("id"))
                    .where(Checkitem.column("checklist_id").in_(checklist_ids))
                    .order_by(Checkitem.column("id"))
                    .with_for_update()
                ).all()
        # Re-read after any lock wait; pre-lock objects may describe an older revision.
        cards = {uid: self._card(uid, project) for uid in refs}
        state = {
            uid: {"card": c.api_response(), "checklists": service.checklist.get_api_list_by_card(c)}
            for uid, c in cards.items()
        }
        column_ids = {cards[plan.anchor_card_uid].project_column_id} if plan.new_cards else set()
        for proposed in plan.cardify_checkitems:
            column = service.project_column.get_by_id_like(proposed.project_column_uid)
            if not column or column.project_id != project.id:
                raise ValueError("Cardification changed after review")
            column_ids.add(column.id)
        if column_ids:
            with DbSession.use(readonly=False) as db:
                db.exec(
                    select(ProjectColumn.column("id"))
                    .where(ProjectColumn.column("id").in_(sorted(column_ids)))
                    .order_by(ProjectColumn.column("id"))
                    .with_for_update()
                ).all()
        columns = []
        if plan.new_cards:
            anchor_column = service.project_column.get_by_id_like(cards[plan.anchor_card_uid].project_column_id)
            if (
                not anchor_column
                or anchor_column.project_id != project.id
                or anchor_column.is_archive
                or anchor_column.deleted_at
            ):
                raise ValueError("Anchor column is unavailable")
            columns.append(anchor_column.api_response())
        cardification_items = []
        for proposed in plan.cardify_checkitems:
            item = service.checkitem.get_by_id_like(proposed.checkitem_uid)
            checklist = service.checklist.get_by_id_like(item.checklist_id) if item else None
            column = service.project_column.get_by_id_like(proposed.project_column_uid)
            if (
                not item
                or not checklist
                or checklist.card_id != cards[proposed.source_card_uid].id
                or item.cardified_id
            ):
                raise ValueError("Cardification source is unavailable")
            if (
                item.title != proposed.title
                or not column
                or column.project_id != project.id
                or column.is_archive
                or column.deleted_at
            ):
                raise ValueError("Cardification changed after review")
            columns.append(column.api_response())
            cardification_items.append(item.api_response())
        graph = self._graph_args(plan, preview=True)
        graph_snapshot = sorted(service.card_relationship.repo.card_relationship.get_graph_snapshot(project))
        type_uids = [e.relationship_type_uid for e in plan.add_edges] + [row[3] for row in graph_snapshot]
        types = service.card_relationship.repo.card_relationship.get_global_relationship_types_map(type_uids)
        if types:
            with DbSession.use(readonly=False) as db:
                db.exec(
                    select(GlobalCardRelationshipType.column("id"))
                    .where(GlobalCardRelationshipType.column("id").in_(sorted(t.id for t in types.values())))
                    .order_by(GlobalCardRelationshipType.column("id"))
                    .with_for_update()
                ).all()
            types = service.card_relationship.repo.card_relationship.get_global_relationship_types_map(type_uids)
        if plan.new_cards or plan.add_edges or plan.remove_relationship_uids:
            service.card_relationship.preview_graph_patch(self.actor, *graph)
        snapshot = {
            "relationship_types": [t.api_response() for _, t in sorted(types.items())],
            "cardification_items": cardification_items,
            "plan": plan.model_dump(mode="json"),
            "cards": state,
            "columns": columns,
            "graph": graph_snapshot,
        }
        revision = sha256(dumps(snapshot, sort_keys=True, default=str, separators=(",", ":")).encode()).hexdigest()
        return (
            {
                "revision": revision,
                "plan": plan.model_dump(mode="json"),
                "counts": {
                    "cards": len(plan.new_cards),
                    "cardifications": len(plan.cardify_checkitems),
                    "checklists": len(plan.new_checklists),
                },
            },
            cards,
            project,
        )

    @staticmethod
    def _graph_args(plan, mapped=None, *, preview=False):
        promoted = {c.client_ref: c for c in plan.cardify_checkitems}
        referenced = {r for e in plan.add_edges for r in (e.parent_ref, e.child_ref)}
        aliases = {}
        used = {c.client_ref for c in plan.new_cards}
        for ref in sorted(set(promoted) & referenced):
            alias = "new:promoted:" + ref[8:]
            while alias in used:
                alias += ":"
            used.add(alias)
            aliases[ref] = alias

        def resolve(ref):
            if ref not in promoted:
                return ref
            return aliases[ref] if preview else mapped[ref].get_uid()

        new_cards = [(c.client_ref, c.title, c.description) for c in plan.new_cards]
        if preview:
            new_cards.extend((alias, promoted[ref].title, None) for ref, alias in aliases.items())
        return (
            plan.project_uid,
            plan.anchor_card_uid,
            new_cards,
            [(resolve(e.parent_ref), resolve(e.child_ref), e.relationship_type_uid) for e in plan.add_edges],
            plan.remove_relationship_uids,
        )

    def preview(self, plan: WorkPlan):
        with DbSession.atomic():
            return self._preview(plan)[0]

    def apply(self, plan: WorkPlan, expected_revision: str, request_id: str):
        if (
            not request_id
            or len(request_id) > 80
            or any(not (c.isascii() and (c.isalnum() or c in "-_")) for c in request_id)
        ):
            raise ValueError("Invalid work plan request ID")
        if len(expected_revision) != 64 or any(c not in "0123456789abcdef" for c in expected_revision):
            raise ValueError("Invalid work plan revision")
        actor_uid = self.actor.get_uid()
        receipt_key = "internal.work_plan." + sha256((actor_uid + ":" + request_id).encode()).hexdigest()
        payload_digest = sha256(dumps(plan.model_dump(mode="json"), sort_keys=True).encode()).hexdigest()
        with DbSession.atomic() as db:
            project = self.service.project.get_by_id_like(plan.project_uid)
            if (
                not project
                or db.exec(
                    select(Project.column("id")).where(Project.column("id") == project.id).with_for_update()
                ).first()
                is None
            ):
                raise ValueError("Project is unavailable")
            anchor = self._card(plan.anchor_card_uid, project)
            receipt = self.service.metadata.get_by_key_as_api(CardMetadata, anchor, receipt_key, internal=True)
            if receipt:
                stored = loads(receipt["value"])
                if stored.get("payload_digest") != payload_digest or stored.get("revision") != expected_revision:
                    raise ValueError("Work plan request ID reused with another plan")
                result = stored["result"]
                graph = result.get("graph") or {}
                visible_refs = {card["uid"] for card in graph.get("created_cards", [])}
                visible_refs.update(item["card"]["uid"] for item in result.get("cardifications", []))
                visible_refs.update(item["target_card_uid"] for item in result.get("checklists", []))
                for edge in graph.get("created_relationships", []):
                    visible_refs.update((edge["parent_card_uid"], edge["child_card_uid"]))
                for uid in visible_refs:
                    self._card(uid, project)
                return {**result, "replayed": True}
            preview, cards, project = self._preview(plan)
            if preview["revision"] != expected_revision:
                raise ValueError("Work plan changed after review; preview again")
            service = self.service
            mapped = dict(cards)
            result = {"graph": None, "cardifications": [], "checklists": []}
            for proposed in plan.cardify_checkitems:
                item = service.checkitem.get_by_id_like(proposed.checkitem_uid)
                if not service.checkitem.cardify(
                    self.actor, project, cards[proposed.source_card_uid], item, proposed.project_column_uid
                ):
                    raise ValueError("Cardification failed")
                persisted = service.checkitem.get_by_id_like(proposed.checkitem_uid)
                card = service.card.get_by_id_like(persisted.cardified_id)
                if card is None:
                    raise ValueError("Cardification readback failed")
                mapped[proposed.client_ref] = card
                result["cardifications"].append(
                    {"card": card.api_response(), "source_checkitem_uid": proposed.checkitem_uid}
                )
            if plan.new_cards or plan.add_edges or plan.remove_relationship_uids:
                graph = service.card_relationship.apply_graph_patch(self.actor, *self._graph_args(plan, mapped))
                if graph is None:
                    raise ValueError("Graph application failed")
                result["graph"] = graph
                for proposed, created in zip(plan.new_cards, graph["created_cards"], strict=True):
                    mapped[proposed.client_ref] = self._card(created["uid"], project)
                    if proposed.presentation is not None:
                        card = mapped[proposed.client_ref]
                        value = dumps(proposed.presentation, ensure_ascii=False, separators=(",", ":"))
                        if service.metadata.save(CardMetadata, card, CARD_PRESENTATION_KEY, value) is None:
                            raise ValueError("Card presentation persistence failed")
                        db.after_commit(
                            lambda uid=card.get_uid(), value=value: MetadataPublisher.updated_metadata(
                                SocketTopic.BoardCard, uid, CARD_PRESENTATION_KEY, value
                            )
                        )
            for proposed in plan.new_checklists:
                card = mapped[proposed.target_card_ref]
                checklist = service.checklist.create(self.actor, project, card, proposed.title, dispatch_effects=False)
                if not checklist:
                    raise ValueError("Checklist creation failed")
                items = []
                for title in proposed.items:
                    item = service.checkitem.create(self.actor, project, card, checklist, title, dispatch_effects=False)
                    if item is None:
                        raise ValueError("Checkitem creation failed")
                    items.append(item)
                frozen_card, frozen_list = card.model_copy(deep=True), checklist.model_copy(deep=True)
                frozen_items = [i.model_copy(deep=True) for i in items]

                def publish(card=frozen_card, checklist=frozen_list, items=frozen_items):
                    service.checklist.dispatch_created(self.actor, project, card, checklist)
                    for item in items:
                        service.checkitem.dispatch_created(self.actor, project, card, checklist, item)

                db.after_commit(publish)
                result["checklists"].append(
                    {
                        "target_card_uid": card.get_uid(),
                        "checklist": checklist.api_response(),
                        "checkitems": [i.api_response() for i in items],
                    }
                )
            result["applied_revision"] = expected_revision
            result["all_succeeded"] = True
            result["replayed"] = False
            result = TypeAdapter(dict).dump_python(result, mode="json")
            value = dumps(
                {"version": 1, "payload_digest": payload_digest, "revision": expected_revision, "result": result},
                default=str,
            )
            if self.service.metadata.save(CardMetadata, anchor, receipt_key, value, internal=True) is None:
                raise ValueError("Work plan receipt persistence failed")
            return result
