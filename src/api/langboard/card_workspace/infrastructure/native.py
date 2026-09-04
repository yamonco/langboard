"""Adapter from card workspace ports to Langboard's native domain services."""

from __future__ import annotations
import json
from typing import Any
from langboard_shared.core.db import EditorContentModel
from langboard_shared.core.types import SafeDateTime
from langboard_shared.domain.models import Bot, CardMetadata, User
from langboard_shared.domain.services import DomainService
from langboard_shared.Env import Env
from ..application.ports import (
    CardBundleSource,
    CardWorkspaceCommandPort,
    CardWorkspaceQueryPort,
    CommentPageSource,
    ProjectCardPageSource,
)
from ..domain import (
    MAX_METADATA_VALUE_CHARS,
    CardDescriptionPatch,
    CardGraphEdge,
    CardGraphNewCard,
    ChecklistProjectionItem,
    projection_revision,
    require_public_metadata_key,
)


MAX_NATIVE_SECTION_SOURCE = 100
_SOURCE_QUERY_LIMIT = MAX_NATIVE_SECTION_SOURCE + 1


class NativeCardWorkspaceAdapter(CardWorkspaceQueryPort, CardWorkspaceCommandPort):
    """Implement card workspace ports using native services and native validation."""

    def __init__(self, actor: User | Bot, service: DomainService) -> None:
        self._actor = actor
        self._service = service

    def get_card_bundle_source(
        self,
        project_uid: str,
        card_uid: str,
        requested_sections: frozenset[str],
    ) -> CardBundleSource | None:
        try:
            project, card = self._ensure_project_card(project_uid, card_uid)
        except ValueError:
            return None
        column = self._service.project_column.get_by_id_like(card.project_column_id)
        if column is None or column.project_id != project.id:
            return None
        details = card.api_response()
        # Native REST wraps Markdown in EditorContentModel; MCP projects the
        # editable text so read revisions match the patch command's input.
        description = details.get("description")
        if isinstance(description, dict) and isinstance(description.get("content"), str):
            details["description"] = description["content"]
        details["project_column_name"] = column.name

        if "people" in requested_sections:
            people = self._bounded_source(
                self._service.card.get_api_assigned_user_list(card, limit=_SOURCE_QUERY_LIMIT),
                "assigned people",
            )
            details["project_members"] = people
            details["member_uids"] = [person["uid"] for person in people]
        else:
            details["project_members"] = []
            details["member_uids"] = []

        if "classification.labels" in requested_sections:
            details["labels"] = self._bounded_source(
                self._service.project_label.get_api_list_by_card(card, limit=_SOURCE_QUERY_LIMIT),
                "labels",
            )
        else:
            details["labels"] = []
        if "classification.relationships" in requested_sections:
            details["relationships"] = self._bounded_source(
                self._service.card_relationship.get_api_list_by_card(card, limit=_SOURCE_QUERY_LIMIT),
                "relationships",
            )
        else:
            details["relationships"] = []

        wants_checklists = "checklists" in requested_sections or any(
            section.startswith("checkitems:") for section in requested_sections
        )
        checklists = (
            self._bounded_source(
                self._service.checklist.get_api_list_by_card(
                    card,
                    limit=_SOURCE_QUERY_LIMIT,
                    checkitems_limit=_SOURCE_QUERY_LIMIT,
                ),
                "checklists",
            )
            if wants_checklists
            else []
        )
        for checklist in checklists:
            checklist["checkitems"] = self._bounded_source(checklist.get("checkitems", []), "checkitems")

        attachments = (
            self._bounded_source(
                self._service.card_attachment.get_api_list_by_card(card, limit=_SOURCE_QUERY_LIMIT),
                "attachments",
            )
            if "attachments" in requested_sections
            else []
        )
        metadata = (
            self._bounded_mapping(
                self._service.metadata.get_all_as_api(
                    CardMetadata,
                    card,
                    as_dict=True,
                    limit=_SOURCE_QUERY_LIMIT,
                ),
                "metadata",
            )
            if "metadata" in requested_sections
            else {}
        )
        bot_scopes = (
            self._bounded_source(
                self._service.card.get_api_bot_scope_list(project, card, limit=_SOURCE_QUERY_LIMIT),
                "bot scopes",
            )
            if "automation.bot_scopes" in requested_sections
            else []
        )
        bot_schedules = (
            self._bounded_source(
                self._service.card.get_api_bot_schedule_list(project, card, limit=_SOURCE_QUERY_LIMIT),
                "bot schedules",
            )
            if "automation.bot_schedules" in requested_sections
            else []
        )
        return CardBundleSource(
            details=details,
            checklists=checklists,
            attachments=attachments,
            metadata={str(key): value for key, value in metadata.items()},
            bot_scopes=bot_scopes,
            bot_schedules=bot_schedules,
        )

    def get_comment_page(
        self,
        card_uid: str,
        limit: int,
        before_created_at: str | None,
        before_comment_uid: str | None,
    ) -> CommentPageSource:
        before = SafeDateTime.fromisoformat(before_created_at) if before_created_at else None
        items, total_count, next_fields = self._service.card_comment.get_api_page_by_card(
            card_uid, limit, before, before_comment_uid
        )
        return CommentPageSource(items, total_count, next_fields)

    def get_project_identity(self, project_uid: str) -> dict[str, Any] | None:
        project = self._service.project.get_by_id_like(project_uid)
        if project is None:
            return None
        uid = project.get_uid()
        columns = sorted(
            (
                {
                    "uid": str(column["uid"]),
                    "name": str(column["name"]),
                    "order": int(column["order"]),
                }
                for column in self._bounded_source(
                    self._service.project_column.get_api_list_by_project(project),
                    "project columns",
                )
                if not column.get("is_archive")
            ),
            key=lambda column: (column["order"], column["uid"]),
        )
        return {
            "uid": uid,
            "title": project.title,
            "project_type": project.project_type,
            "url": f"{Env.PUBLIC_UI_URL}/board/{uid}",
            "columns": {
                "items": columns,
                "total_count": len(columns),
                "next_cursor": None,
                "limit": MAX_NATIVE_SECTION_SOURCE,
            },
        }

    def get_project_card_page(
        self,
        project_uid: str,
        limit: int,
        before_updated_at: str | None,
        before_card_uid: str | None,
    ) -> ProjectCardPageSource:
        before = SafeDateTime.fromisoformat(before_updated_at) if before_updated_at else None
        result = self._service.card.get_api_page_by_project(project_uid, limit, before, before_card_uid)
        if result is None:
            raise ValueError("Project not found")
        items, total_count, next_fields = result
        return ProjectCardPageSource(items, total_count, next_fields)

    def get_public_card_metadata(self, project_uid: str, card_uid: str) -> dict[str, str] | None:
        card = self._ensure_card(project_uid, card_uid, required=False)
        if card is None:
            return None
        metadata = self._bounded_mapping(
            self._service.metadata.get_all_as_api(CardMetadata, card, as_dict=True, limit=_SOURCE_QUERY_LIMIT),
            "metadata",
        )
        return {str(key): str(value) for key, value in metadata.items()}

    def create_project_board(
        self,
        title: str,
        description: str | None,
        template_name: str | None = None,
        infer_template_prefix: bool = False,
    ) -> dict[str, Any]:
        if not isinstance(self._actor, User):
            raise PermissionError("Only users can create projects")
        project, created_columns, template = self._service.project_template.create_project(
            self._actor,
            title,
            description,
            "Other",
            template_name,
            infer_template_prefix,
        )
        columns = [{**column.api_response(), "count": 0} for column in created_columns]
        uid = project.get_uid()
        return {
            "project": {
                "uid": uid,
                "title": project.title,
                "project_type": project.project_type,
                "url": f"{Env.PUBLIC_UI_URL}/board/{uid}",
                "template": template.name,
            },
            "columns": columns,
        }

    def create_card_in_leftmost_column(
        self,
        project_uid: str,
        title: str,
        description: str | None,
        assign_user_uids: list[str] | None,
    ) -> dict[str, Any]:
        project = self._service.project.get_by_id_like(project_uid)
        if project is None:
            raise ValueError("Project not found")
        if assign_user_uids is not None:
            self._require_members(project, assign_user_uids)
        columns = sorted(
            (
                column
                for column in self._service.project_column.get_api_list_by_project(project)
                if not column["is_archive"]
            ),
            key=lambda column: (column["order"], column["uid"]),
        )
        if not columns:
            raise ValueError("Project has no active column")
        result = self._service.card.create(
            self._actor,
            project,
            columns[0]["uid"],
            title,
            EditorContentModel(content=description or ""),
            assign_user_uids,
        )
        if result is None:
            raise RuntimeError("Failed to create card")
        _, card = result
        return {"card": card, "column": {"uid": columns[0]["uid"], "name": columns[0]["name"]}}

    def apply_card_graph_patch(
        self,
        project_uid: str,
        anchor_card_uid: str,
        new_cards: list[CardGraphNewCard],
        add_edges: list[CardGraphEdge],
        remove_relationship_uids: list[str],
    ) -> dict[str, Any]:
        """Apply one native card relationship graph transaction."""

        result = self._service.card_relationship.apply_graph_patch(
            self._actor,
            project_uid,
            anchor_card_uid,
            [(card.client_ref, card.title, card.description) for card in new_cards],
            [(edge.parent_ref, edge.child_ref, edge.relationship_type_uid) for edge in add_edges],
            remove_relationship_uids,
        )
        if result is None:
            raise ValueError("Anchor card not found in project")
        return result

    def patch_card_description(
        self,
        project_uid: str,
        card_uid: str,
        patch: CardDescriptionPatch,
    ) -> str:
        project, card = self._ensure_project_card(project_uid, card_uid)
        current = card.description.content if card.description is not None else ""
        patched = patch.apply(current)
        result = self._service.card.update(
            self._actor,
            project,
            card,
            {"description": EditorContentModel(content=patched)},
        )
        if not result:
            raise RuntimeError("Validated card description patch failed")
        return patched

    def add_card_comment(self, project_uid: str, card_uid: str, content: str) -> dict[str, Any]:
        comment = self._service.card_comment.create(
            self._actor, project_uid, card_uid, EditorContentModel(content=content)
        )
        if comment is None:
            raise ValueError("Card not found in project")
        return comment.api_response()

    def update_card_comment(self, project_uid: str, card_uid: str, comment_uid: str, content: str) -> dict[str, Any]:
        comment = self._service.card_comment.update(
            self._actor, project_uid, card_uid, comment_uid, EditorContentModel(content=content)
        )
        if comment is None:
            raise PermissionError("Comment not found or not owned by current actor")
        return comment.api_response()

    def delete_card_comment(self, project_uid: str, card_uid: str, comment_uid: str) -> None:
        if not self._service.card_comment.delete(self._actor, project_uid, card_uid, comment_uid):
            raise PermissionError("Comment not found or not owned by current actor")

    def create_card_checklist(self, project_uid: str, card_uid: str, title: str) -> dict[str, Any]:
        checklist = self._service.checklist.create(self._actor, project_uid, card_uid, title)
        if checklist is None:
            raise ValueError("Card not found in project")
        return {**checklist.api_response(), "checkitems": []}

    def update_card_checklist(
        self,
        project_uid: str,
        card_uid: str,
        checklist_uid: str,
        title: str | None,
        is_checked: bool | None,
    ) -> list[dict[str, Any]]:
        checklist = self._ensure_checklist(project_uid, card_uid, checklist_uid)
        if title is not None and checklist.title != title:
            if not self._service.checklist.change_title(self._actor, project_uid, card_uid, checklist, title):
                raise ValueError("Checklist not found in card")
        if is_checked is not None and checklist.is_checked != is_checked:
            if not self._service.checklist.toggle_checked(self._actor, project_uid, card_uid, checklist):
                raise ValueError("Checklist not found in card")
        return self._service.checklist.get_api_list_by_card(card_uid, limit=26, checkitems_limit=26)

    def delete_card_checklist(self, project_uid: str, card_uid: str, checklist_uid: str) -> None:
        self._ensure_checklist(project_uid, card_uid, checklist_uid)
        if not self._service.checklist.delete(self._actor, project_uid, card_uid, checklist_uid):
            raise ValueError("Checklist not found in card")

    def create_card_checkitem(self, project_uid: str, card_uid: str, checklist_uid: str, title: str) -> dict[str, Any]:
        self._ensure_checklist(project_uid, card_uid, checklist_uid)
        item = self._service.checkitem.create(self._actor, project_uid, card_uid, checklist_uid, title)
        if item is None:
            raise ValueError("Checklist not found in card")
        return item.api_response()

    def cardify_card_checkitem(
        self,
        project_uid: str,
        card_uid: str,
        checkitem_uid: str,
        project_column_uid: str,
    ) -> dict[str, Any]:
        """Cardify an existing item and return the created native card."""

        project, _ = self._ensure_project_card(project_uid, card_uid)
        item = self._ensure_checkitem(project_uid, card_uid, checkitem_uid)
        if item.cardified_id:
            raise ValueError("Checkitem is already cardified")
        column = self._service.project_column.get_by_id_like(project_column_uid)
        if column is None or column.project_id != project.id or column.is_archive:
            raise ValueError("Destination column is not active in the source project")
        if not self._service.checkitem.cardify(
            self._actor,
            project_uid,
            card_uid,
            item,
            project_column_uid,
        ):
            raise ValueError("Checkitem could not be cardified in the requested column")
        # The native service resolves its own model instance before persisting.
        # Re-read the source instead of relying on mutation of our stale object.
        item = self._ensure_checkitem(project_uid, card_uid, checkitem_uid)
        card = self._service.card.get_by_id_like(item.cardified_id)
        if card is None:
            raise RuntimeError("Cardified card could not be read back")
        return card.board_api_response(0, [], [], [])

    def update_card_checkitem(
        self,
        project_uid: str,
        card_uid: str,
        checkitem_uid: str,
        title: str | None,
        deadline_at: str | None,
        is_checked: bool | None,
    ) -> list[dict[str, Any]]:
        item = self._ensure_checkitem(project_uid, card_uid, checkitem_uid)
        deadline = None
        if deadline_at is not None and deadline_at != "":
            deadline = SafeDateTime.fromisoformat(deadline_at)
            if deadline.tzinfo is None:
                deadline = deadline.replace(tzinfo=SafeDateTime.now().astimezone().tzinfo)
        if title is not None and item.title != title:
            if not self._service.checkitem.change_title(self._actor, project_uid, card_uid, item, title):
                raise ValueError("Checkitem not found in card")
        if deadline_at is not None and not self._service.checkitem.change_deadline(
            project_uid, card_uid, item, deadline
        ):
            raise ValueError("Checkitem not found in card")
        if is_checked is not None and item.is_checked != is_checked:
            if not self._service.checkitem.toggle_checked(self._actor, project_uid, card_uid, item):
                raise ValueError("Checkitem not found in card")
        return self._service.checklist.get_api_list_by_card(card_uid, limit=26, checkitems_limit=26)

    def delete_card_checkitem(self, project_uid: str, card_uid: str, checkitem_uid: str) -> None:
        self._ensure_checkitem(project_uid, card_uid, checkitem_uid)
        if not self._service.checkitem.delete(self._actor, project_uid, card_uid, checkitem_uid):
            raise ValueError("Checkitem not found in card")

    def replace_card_people_and_labels(
        self,
        project_uid: str,
        card_uid: str,
        assign_user_uids: list[str] | None,
        label_uids: list[str] | None,
    ) -> dict[str, Any]:
        project, card = self._ensure_project_card(project_uid, card_uid)
        if assign_user_uids is not None:
            self._require_members(project, assign_user_uids)
        if label_uids is not None:
            available = {
                label["uid"]
                for label in self._service.project_label.get_api_list_by_project(project, where_in=label_uids)
            }
            self._require_known("label", label_uids, available)
        response: dict[str, Any] = {}
        if assign_user_uids is not None:
            users = self._service.card.update_assigned_users(self._actor, project, card, assign_user_uids)
            if users is None:
                raise RuntimeError("Validated member replacement failed")
            response["member_uids"] = [user.get_uid() for user in users]
        if label_uids is not None:
            if not self._service.card.update_labels(self._actor, project, card, label_uids):
                raise RuntimeError("Validated label replacement failed")
            response["labels"] = self._service.project_label.get_api_list_by_card(card)
        return response

    def replace_card_relationships(
        self,
        project_uid: str,
        card_uid: str,
        is_parent: bool,
        relationships: list[tuple[str, str]],
    ) -> list[dict[str, Any]]:
        project, card = self._ensure_project_card(project_uid, card_uid)
        type_uids = {item["uid"] for item in self._service.app_setting.get_api_global_relationship_list()}
        related_uids: set[str] = set()
        for related_uid, relationship_type_uid in relationships:
            if related_uid == card_uid:
                raise ValueError("A card cannot relate to itself")
            related = self._service.card.get_by_id_like(related_uid)
            if related is None or related.project_id != project.id:
                raise ValueError(f"Unknown related card: {related_uid}")
            if relationship_type_uid not in type_uids:
                raise ValueError(f"Unknown relationship type: {relationship_type_uid}")
            if related_uid in related_uids:
                raise ValueError(f"Duplicate related card: {related_uid}")
            related_uids.add(related_uid)
        for existing in self._service.card_relationship.get_api_list_by_card(card):
            parent_uid = existing.get("parent_card_uid")
            child_uid = existing.get("child_card_uid")
            opposite_uid = child_uid if parent_uid == card_uid else parent_uid
            card_is_parent = parent_uid == card_uid
            if opposite_uid in related_uids and card_is_parent == is_parent:
                raise ValueError(f"Opposite relationship already exists: {opposite_uid}")
        result = self._service.card_relationship.update(self._actor, project, card, is_parent, relationships)
        if result is None:
            raise RuntimeError("Validated relationship replacement failed")
        return result

    def update_card_attachment(
        self,
        project_uid: str,
        card_uid: str,
        attachment_uid: str,
        name: str | None,
        order: int | None,
    ) -> list[dict[str, Any]]:
        if not isinstance(self._actor, User):
            raise PermissionError("Only users can update attachments")
        attachment = self._ensure_attachment(project_uid, card_uid, attachment_uid)
        if name is not None and not self._service.card_attachment.change_name(
            self._actor, project_uid, card_uid, attachment, name
        ):
            raise ValueError("Attachment not found in card")
        if order is not None and not self._service.card_attachment.change_order(
            project_uid, card_uid, attachment, order
        ):
            raise ValueError("Attachment not found in card")
        return self._service.card_attachment.get_api_list_by_card(card_uid, limit=26)

    def delete_card_attachment(self, project_uid: str, card_uid: str, attachment_uid: str) -> None:
        if not isinstance(self._actor, User):
            raise PermissionError("Only users can delete attachments")
        attachment = self._ensure_attachment(project_uid, card_uid, attachment_uid)
        if not self._service.card_attachment.delete(self._actor, project_uid, card_uid, attachment):
            raise ValueError("Attachment not found in card")

    def save_public_card_metadata(
        self,
        project_uid: str,
        card_uid: str,
        key: str,
        value: str,
        old_key: str | None,
    ) -> dict[str, str]:
        key = require_public_metadata_key(key)
        if old_key is not None:
            old_key = require_public_metadata_key(old_key)
        card = self._ensure_card(project_uid, card_uid)
        metadata = self._service.metadata.save(CardMetadata, card, key, value, old_key)
        if metadata is None:
            raise RuntimeError("Failed to save metadata")
        return self.get_public_card_metadata(project_uid, card_uid) or {}

    def delete_public_card_metadata(self, project_uid: str, card_uid: str, keys: list[str]) -> None:
        normalized = [require_public_metadata_key(key) for key in keys]
        card = self._ensure_card(project_uid, card_uid)
        if not self._service.metadata.delete(CardMetadata, card, normalized):
            raise ValueError("Metadata not found")

    def reconcile_card_checklist_projection(
        self,
        project_uid: str,
        card_uid: str,
        projection_key: str,
        title: str,
        items: list[ChecklistProjectionItem],
        expected_receipt: str | None,
    ) -> dict[str, Any]:
        """Converge one checklist projection, checkpointing identities before the receipt."""

        card = self._ensure_card(project_uid, card_uid)
        metadata_key = require_public_metadata_key(f"projection.checklist.{projection_key}")
        metadata = self.get_public_card_metadata(project_uid, card_uid) or {}
        state = self._checklist_projection_state(metadata.get(metadata_key))
        if expected_receipt is not None and state.get("receipt") != expected_receipt:
            raise ValueError("Checklist projection changed after review")
        desired_payload = {
            "projection_key": projection_key,
            "title": title,
            "items": [
                {
                    "key": item.key,
                    "title": item.title.strip(),
                    "is_checked": item.is_checked,
                    "deadline_at": item.deadline_at,
                }
                for item in items
            ],
        }
        receipt = projection_revision(desired_payload)
        changed = False
        checklists = self._service.checklist.get_api_list_by_card(card_uid, limit=26, checkitems_limit=26)
        checklist = next(
            (item for item in checklists if item["uid"] == state.get("checklist_uid")),
            None,
        )
        if checklist is None:
            created = self._service.checklist.create(self._actor, project_uid, card_uid, title)
            if created is None:
                raise ValueError("Card not found in project")
            checklist = {**created.api_response(), "checkitems": []}
            state = {"version": 1, "checklist_uid": checklist["uid"], "items": {}}
            self._save_checklist_projection_state(card, metadata_key, state)
            changed = True
        elif checklist["title"] != title:
            native = self._ensure_checklist(project_uid, card_uid, checklist["uid"])
            if not self._service.checklist.change_title(self._actor, project_uid, card_uid, native, title):
                raise ValueError("Checklist not found in card")
            changed = True

        item_uids = state.setdefault("items", {})
        actual_items = {item["uid"]: item for item in checklist.get("checkitems", [])}
        desired_keys = {item.key for item in items}
        for item in items:
            item_uid = item_uids.get(item.key)
            actual = actual_items.get(item_uid)
            if actual is None:
                created = self._service.checkitem.create(
                    self._actor, project_uid, card_uid, checklist["uid"], item.title.strip()
                )
                if created is None:
                    raise ValueError("Checklist not found in card")
                item_uid = created.get_uid()
                item_uids[item.key] = item_uid
                actual = created.api_response()
                self._save_checklist_projection_state(card, metadata_key, state)
                changed = True
            native_item = self._ensure_checkitem(project_uid, card_uid, item_uid)
            if actual.get("title") != item.title.strip():
                if not self._service.checkitem.change_title(
                    self._actor, project_uid, card_uid, native_item, item.title.strip()
                ):
                    raise ValueError("Checkitem not found in card")
                changed = True
            if item.deadline_at is not None and not self._same_deadline(actual.get("deadline_at"), item.deadline_at):
                deadline = SafeDateTime.fromisoformat(item.deadline_at)
                if deadline.tzinfo is None:
                    deadline = deadline.replace(tzinfo=SafeDateTime.now().astimezone().tzinfo)
                if not self._service.checkitem.change_deadline(project_uid, card_uid, native_item, deadline):
                    raise ValueError("Checkitem not found in card")
                changed = True
            if bool(actual.get("is_checked")) != item.is_checked:
                if not self._service.checkitem.toggle_checked(self._actor, project_uid, card_uid, native_item):
                    raise ValueError("Checkitem not found in card")
                changed = True

        for stale_key in sorted(set(item_uids) - desired_keys):
            stale_uid = item_uids.pop(stale_key)
            if stale_uid in actual_items:
                self.delete_card_checkitem(project_uid, card_uid, stale_uid)
            self._save_checklist_projection_state(card, metadata_key, state)
            changed = True

        state.update({"version": 1, "receipt": receipt, "target_receipt": receipt})
        self._save_checklist_projection_state(card, metadata_key, state)
        checklists = self._service.checklist.get_api_list_by_card(card_uid, limit=26, checkitems_limit=26)
        result = next(item for item in checklists if item["uid"] == checklist["uid"])
        return {"changed": changed, "receipt": receipt, "checklist": result}

    def _save_checklist_projection_state(
        self,
        card: Any,
        metadata_key: str,
        state: dict[str, Any],
    ) -> None:
        encoded = json.dumps(state, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
        if len(encoded) > MAX_METADATA_VALUE_CHARS:
            raise ValueError("Checklist projection state exceeds metadata capacity")
        if self._service.metadata.save(CardMetadata, card, metadata_key, encoded) is None:
            raise RuntimeError("Failed to save checklist projection state")

    @staticmethod
    def _checklist_projection_state(raw: str | None) -> dict[str, Any]:
        if raw is None:
            return {"version": 1, "items": {}}
        try:
            state = json.loads(raw)
        except (TypeError, json.JSONDecodeError) as error:
            raise ValueError("Checklist projection state is malformed") from error
        if (
            not isinstance(state, dict)
            or state.get("version") != 1
            or not isinstance(state.get("items"), dict)
            or any(not isinstance(key, str) or not isinstance(value, str) for key, value in state["items"].items())
        ):
            raise ValueError("Checklist projection state is malformed")
        return state

    @staticmethod
    def _same_deadline(actual: object, desired: str) -> bool:
        if not isinstance(actual, str):
            return False
        return SafeDateTime.fromisoformat(actual) == SafeDateTime.fromisoformat(desired)

    def _ensure_project_card(self, project_uid: str, card_uid: str) -> tuple[Any, Any]:
        project = self._service.project.get_by_id_like(project_uid)
        card = self._service.card.get_by_id_like(card_uid)
        if project is None or card is None or card.project_id != project.id:
            raise ValueError("Card not found in project")
        return project, card

    def _ensure_card(self, project_uid: str, card_uid: str, required: bool = True) -> Any:
        try:
            return self._ensure_project_card(project_uid, card_uid)[1]
        except ValueError:
            if required:
                raise
            return None

    def _ensure_checklist(self, project_uid: str, card_uid: str, checklist_uid: str) -> Any:
        _, card = self._ensure_project_card(project_uid, card_uid)
        checklist = self._service.checklist.get_by_id_like(checklist_uid)
        if checklist is None or checklist.card_id != card.id:
            raise ValueError("Checklist not found in card")
        return checklist

    def _ensure_checkitem(self, project_uid: str, card_uid: str, checkitem_uid: str) -> Any:
        _, card = self._ensure_project_card(project_uid, card_uid)
        item = self._service.checkitem.get_by_id_like(checkitem_uid)
        checklist = self._service.checklist.get_by_id_like(item.checklist_id) if item is not None else None
        if item is None or checklist is None or checklist.card_id != card.id:
            raise ValueError("Checkitem not found in card")
        return item

    def _ensure_attachment(self, project_uid: str, card_uid: str, attachment_uid: str) -> Any:
        _, card = self._ensure_project_card(project_uid, card_uid)
        attachment = self._service.card_attachment.get_by_id_like(attachment_uid)
        if attachment is None or attachment.card_id != card.id:
            raise ValueError("Attachment not found in card")
        return attachment

    def _require_members(self, project: Any, requested: list[str]) -> None:
        available = {
            member["uid"]
            for member in self._service.project.get_api_assigned_user_list(project, where_user_in=requested)
        }
        self._require_known("project member", requested, available)

    @staticmethod
    def _require_known(label: str, requested: list[str], available: set[str]) -> None:
        unknown = [uid for uid in requested if uid not in available]
        if unknown:
            raise ValueError(f"Unknown {label}: {unknown[0]}")

    @staticmethod
    def _bounded_source(items: list[Any], label: str) -> list[Any]:
        """Enforce the adapter's hard native source cardinality contract."""

        if len(items) > MAX_NATIVE_SECTION_SOURCE:
            raise ValueError(f"{label} exceeds the safe {MAX_NATIVE_SECTION_SOURCE}-item MCP source bound")
        return items

    @staticmethod
    def _bounded_mapping(items: dict[str, Any], label: str) -> dict[str, Any]:
        """Enforce the adapter's hard native mapping cardinality contract."""

        if len(items) > MAX_NATIVE_SECTION_SOURCE:
            raise ValueError(f"{label} exceeds the safe {MAX_NATIVE_SECTION_SOURCE}-item MCP source bound")
        return items
