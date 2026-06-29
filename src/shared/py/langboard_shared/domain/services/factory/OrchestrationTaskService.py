from __future__ import annotations
from json import dumps, loads
from typing import Any
from ....core.db import EditorContentModel
from ....core.domain import BaseDomainService
from ....core.routing import SocketTopic
from ....core.types import SafeDateTime
from ....core.types.ParamTypes import TCardParam, TColumnParam, TProjectParam, TUserOrBot
from ....helpers import InfraHelper
from ....publishers import MetadataPublisher
from ....tasks.bots import BotDefaultTask
from ...constants.TaskMetadata import (
    AUTO_FIX_COLUMN_NAME,
    BYPASS_APPROVAL_ACTION_TYPES,
    FAILED_COLUMN_NAME,
    ORCHESTRATION_AI_GENERATED_SOURCE,
    READY_TO_MERGE_COLUMN_NAME,
    SYSTEM_TASK_METADATA_KEYS,
    TASK_METADATA_KEYS,
    TASK_RELATIONSHIP_CHILD_NAME,
    TASK_RELATIONSHIP_DESCRIPTION,
    TASK_RELATIONSHIP_PARENT_NAME,
    TODO_COLUMN_NAME,
    WORKFLOW_COLUMN_NAMES,
)
from ...models import Bot, Card, CardMetadata, GlobalCardRelationshipType, Project, ProjectColumn, User
from ...models.GraphApprovalRequest import GraphApprovalOriginType
from .AppSettingService import AppSettingService
from .CardCommentService import CardCommentService
from .CardRelationshipService import CardRelationshipService
from .CardService import CardService
from .GraphApprovalRequestService import GraphApprovalRequestService
from .MetadataService import MetadataService
from .ProjectColumnService import ProjectColumnService


class OrchestrationTaskService(BaseDomainService):
    @staticmethod
    def name() -> str:
        return "orchestration_task"

    def apply_workflow_template(
        self, user_or_bot: TUserOrBot, project: TProjectParam | None
    ) -> list[dict[str, Any]] | None:
        project = InfraHelper.get_by_id_like(Project, project)
        if not project:
            return None

        existing_columns = self.repo.project_column.get_all_by_project(project)
        existing_names = {column.name.strip().lower() for column, _ in existing_columns}
        column_service = self._get_service(ProjectColumnService)
        for name in WORKFLOW_COLUMN_NAMES:
            if name.strip().lower() in existing_names:
                continue
            column_service.create(user_or_bot, project, name)
            existing_names.add(name.strip().lower())

        self.__get_or_create_task_relationship_type()

        return column_service.get_api_list_by_project(project)

    def create_task(
        self,
        user_or_bot: TUserOrBot,
        project: TProjectParam | None,
        title: str,
        *,
        column: TColumnParam | None = None,
        description: EditorContentModel | None = None,
        assign_user_uids: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], dict[str, str]] | None:
        project = InfraHelper.get_by_id_like(Project, project)
        if not project:
            return None

        target_column = self.__get_or_create_workflow_column(user_or_bot, project, column, TODO_COLUMN_NAME)
        if not target_column:
            return None

        card_service = self._get_service(CardService)
        created = card_service.create(user_or_bot, project, target_column, title, description, assign_user_uids)
        if not created:
            return None

        card, api_card = created
        saved_metadata = self.save_task_metadata(project, card, metadata or {})
        self.__dispatch_assigned_bot(user_or_bot, project, card, metadata or {})
        return api_card, saved_metadata

    def save_task_metadata(
        self,
        project: TProjectParam | None,
        card: TCardParam | None,
        metadata: dict[str, Any],
    ) -> dict[str, str]:
        params = InfraHelper.get_records_with_foreign_by_params((Project, project), (Card, card))
        if not params:
            return {}
        _, card = params

        metadata_service = self._get_service(MetadataService)
        saved: dict[str, str] = {}
        for field_name, key in TASK_METADATA_KEYS.items():
            value = metadata.get(field_name)
            serialized = self.__serialize_metadata_value(value)
            if serialized is None:
                continue
            metadata_service.save(CardMetadata, card, key, serialized)
            MetadataPublisher.updated_metadata(SocketTopic.BoardCard, card.get_uid(), key, serialized)
            saved[key] = serialized

        return saved

    def record_verification(
        self,
        user_or_bot: TUserOrBot,
        project: TProjectParam | None,
        card: TCardParam | None,
        verification: dict[str, Any],
        failure: dict[str, Any] | None = None,
        target_column_name: str | None = None,
    ) -> dict[str, str] | None:
        params = InfraHelper.get_records_with_foreign_by_params((Project, project), (Card, card))
        if not params:
            return None
        project, card = params

        metadata_service = self._get_service(MetadataService)
        verification = {**verification}
        verification.setdefault("checked_at", SafeDateTime.now().isoformat())
        serialized_verification = dumps(verification, ensure_ascii=False)
        metadata_service.save(CardMetadata, card, SYSTEM_TASK_METADATA_KEYS["verification"], serialized_verification)
        MetadataPublisher.updated_metadata(
            SocketTopic.BoardCard,
            card.get_uid(),
            SYSTEM_TASK_METADATA_KEYS["verification"],
            serialized_verification,
        )

        saved = {
            SYSTEM_TASK_METADATA_KEYS["verification"]: serialized_verification,
        }

        if failure is not None:
            failure = {**failure}
            failure.setdefault("checked_at", verification["checked_at"])
            serialized_failure = dumps(failure, ensure_ascii=False)
            metadata_service.save(CardMetadata, card, SYSTEM_TASK_METADATA_KEYS["failure"], serialized_failure)
            MetadataPublisher.updated_metadata(
                SocketTopic.BoardCard,
                card.get_uid(),
                SYSTEM_TASK_METADATA_KEYS["failure"],
                serialized_failure,
            )
            saved[SYSTEM_TASK_METADATA_KEYS["failure"]] = serialized_failure
            self.__create_failure_comment(user_or_bot, project, card, verification, failure)
        else:
            metadata_service.delete(CardMetadata, card, SYSTEM_TASK_METADATA_KEYS["failure"])
            MetadataPublisher.deleted_metadata(
                SocketTopic.BoardCard, card.get_uid(), [SYSTEM_TASK_METADATA_KEYS["failure"]]
            )

        transition_column_name = self.__get_verification_target_column_name(verification, failure, target_column_name)
        if transition_column_name:
            target_column = self.__find_project_column_by_name(project, transition_column_name)
            if target_column:
                self._get_service(CardService).change_order(user_or_bot, project, card, 0, target_column)

        return saved

    def record_run(
        self,
        project: TProjectParam | None,
        card: TCardParam | None,
        run: dict[str, Any],
    ) -> dict[str, str] | None:
        params = InfraHelper.get_records_with_foreign_by_params((Project, project), (Card, card))
        if not params:
            return None
        _, card = params

        run = {**run}
        run.setdefault("recorded_at", SafeDateTime.now().isoformat())
        serialized = dumps(run, ensure_ascii=False)
        key = SYSTEM_TASK_METADATA_KEYS["run"]
        self._get_service(MetadataService).save(CardMetadata, card, key, serialized)
        MetadataPublisher.updated_metadata(SocketTopic.BoardCard, card.get_uid(), key, serialized)
        return {key: serialized}

    def record_suggestions(
        self,
        project: TProjectParam | None,
        card: TCardParam | None,
        suggestions: list[dict[str, Any]],
    ) -> dict[str, str] | None:
        params = InfraHelper.get_records_with_foreign_by_params((Project, project), (Card, card))
        if not params:
            return None
        _, card = params

        serialized = dumps(suggestions, ensure_ascii=False)
        key = SYSTEM_TASK_METADATA_KEYS["suggestions"]
        self._get_service(MetadataService).save(CardMetadata, card, key, serialized)
        MetadataPublisher.updated_metadata(SocketTopic.BoardCard, card.get_uid(), key, serialized)
        return {key: serialized}

    def record_bypass_decision(
        self,
        user_or_bot: TUserOrBot,
        project: TProjectParam | None,
        card: TCardParam | None,
        bypass: dict[str, Any],
    ) -> tuple[dict[str, str], dict[str, Any] | None] | None:
        params = InfraHelper.get_records_with_foreign_by_params((Project, project), (Card, card))
        if not params:
            return None
        project, card = params

        bypass = self.__evaluate_bypass_policy(bypass)
        bypass.setdefault("checked_at", SafeDateTime.now().isoformat())
        approval_request_response = None
        if bypass["requires_approval"] and not bypass["allowed"]:
            approval_request = self.__create_bypass_approval_request(user_or_bot, project, card, bypass)
            if approval_request:
                bypass["approval_request_uid"] = approval_request.get_uid()
                approval_request_response = self._get_service(GraphApprovalRequestService).get_api_response(
                    approval_request
                )

        bypass_metadata = self.__get_bypass_metadata(bypass)
        serialized = dumps(bypass_metadata, ensure_ascii=False)
        key = SYSTEM_TASK_METADATA_KEYS["bypass"]
        self._get_service(MetadataService).save(CardMetadata, card, key, serialized)
        MetadataPublisher.updated_metadata(SocketTopic.BoardCard, card.get_uid(), key, serialized)
        return {key: serialized}, approval_request_response

    def create_child_task_from_suggestion(
        self,
        user_or_bot: TUserOrBot,
        project: TProjectParam | None,
        parent_card: TCardParam | None,
        suggestion: dict[str, Any],
        *,
        column_name: str | None = None,
        relationship_type: str | None = None,
    ) -> tuple[dict[str, Any], dict[str, str], list[dict[str, Any]]] | None:
        params = InfraHelper.get_records_with_foreign_by_params((Project, project), (Card, parent_card))
        if not params:
            return None
        project, parent_card = params

        title = str(suggestion.get("title") or "").strip()
        if not title:
            return None

        relationship = self.__get_or_create_task_relationship_type(relationship_type)
        if not relationship:
            return None

        column = self.__find_project_column_by_name(project, column_name) if column_name else None
        metadata = {
            "source": ORCHESTRATION_AI_GENERATED_SOURCE,
            "type": suggestion.get("type"),
            "assigned_agent": suggestion.get("assigned_agent"),
            "assigned_bot_uid": suggestion.get("assigned_bot_uid"),
            "risk_level": suggestion.get("risk_level"),
            "acceptance_criteria": suggestion.get("acceptance_criteria"),
            "related_files": suggestion.get("related_files"),
        }
        created = self.create_task(
            user_or_bot,
            project,
            title,
            column=column,
            metadata=metadata,
        )
        if not created:
            return None

        api_card, saved_metadata = created
        existing_child_relationships = self.repo.card_relationship.get_all_by_card_and_relation(
            parent_card, relation="child"
        )
        relationships = [
            (related_card.get_uid(), relationship_type.get_uid())
            for _, relationship_type, related_card in existing_child_relationships
        ]
        relationships.append((api_card["uid"], relationship.get_uid()))
        updated_relationships = self._get_service(CardRelationshipService).update(
            user_or_bot,
            project,
            parent_card,
            False,
            relationships,
        )
        if updated_relationships is None:
            return None

        self.__mark_suggestion_created(parent_card, suggestion, api_card["uid"])
        return api_card, saved_metadata, updated_relationships

    def __get_or_create_workflow_column(
        self,
        user_or_bot: TUserOrBot,
        project: Project,
        column: TColumnParam | None,
        fallback_name: str,
    ) -> ProjectColumn | None:
        if column:
            target_column = InfraHelper.get_by_id_like(ProjectColumn, column)
            if target_column and target_column.project_id == project.id and not target_column.is_archive:
                return target_column
            return None

        existing_column = self.__find_project_column_by_name(project, fallback_name)
        if existing_column:
            return existing_column

        return self._get_service(ProjectColumnService).create(user_or_bot, project, fallback_name)

    def __find_project_column_by_name(self, project: Project, name: str) -> ProjectColumn | None:
        target_name = name.strip().lower()
        for column, _ in self.repo.project_column.get_all_by_project(project):
            if column.name.strip().lower() == target_name:
                return column
        return None

    def __get_task_relationship_type(
        self, relationship_type_uid: str | None = None
    ) -> GlobalCardRelationshipType | None:
        if relationship_type_uid:
            relationship_type = InfraHelper.get_by_id_like(GlobalCardRelationshipType, relationship_type_uid)
            if relationship_type:
                return relationship_type

        for relationship_type in InfraHelper.get_all(GlobalCardRelationshipType):
            if (
                relationship_type.parent_name.strip().lower() == TASK_RELATIONSHIP_PARENT_NAME.lower()
                and relationship_type.child_name.strip().lower() == TASK_RELATIONSHIP_CHILD_NAME.lower()
            ):
                return relationship_type

        return None

    def __get_or_create_task_relationship_type(
        self, relationship_type_uid: str | None = None
    ) -> GlobalCardRelationshipType | None:
        relationship_type = self.__get_task_relationship_type(relationship_type_uid)
        if relationship_type:
            return relationship_type

        return self._get_service(AppSettingService).create_global_relationship(
            TASK_RELATIONSHIP_PARENT_NAME,
            TASK_RELATIONSHIP_CHILD_NAME,
            TASK_RELATIONSHIP_DESCRIPTION,
        )

    def __get_verification_target_column_name(
        self,
        verification: dict[str, Any],
        failure: dict[str, Any] | None,
        target_column_name: str | None,
    ) -> str | None:
        if target_column_name:
            return target_column_name

        status = str(verification.get("status") or "").strip().lower()
        if failure is not None and bool(failure.get("auto_fix")):
            return AUTO_FIX_COLUMN_NAME
        if failure is not None or status == "failed":
            return FAILED_COLUMN_NAME
        if status == "passed":
            return READY_TO_MERGE_COLUMN_NAME
        return None

    def __evaluate_bypass_policy(self, bypass: dict[str, Any]) -> dict[str, Any]:
        evaluated = {**bypass}
        risk_level = str(evaluated.get("risk_level") or "").strip().lower()
        action_type = str(evaluated.get("action_type") or "").strip().lower()
        requires_approval = bool(evaluated.get("requires_approval"))

        if risk_level == "high" or action_type in BYPASS_APPROVAL_ACTION_TYPES:
            requires_approval = True

        requested_allowed = bool(evaluated.get("allowed"))
        allowed = requested_allowed if requires_approval else True
        evaluated["allowed"] = allowed
        evaluated["requires_approval"] = requires_approval
        if not evaluated.get("reason"):
            evaluated["reason"] = (
                "High-risk orchestration work was approved for bypass."
                if requires_approval and allowed
                else "Approval required for high-risk orchestration work."
                if requires_approval
                else "Low-risk orchestration work can continue without manual approval."
            )
        return evaluated

    def __create_bypass_approval_request(
        self,
        user_or_bot: TUserOrBot,
        project: Project,
        card: Card,
        bypass: dict[str, Any],
    ):
        thread_id = self.__string_or_none(bypass.get("thread_id"))
        if not thread_id:
            return None

        interrupt = {
            "type": "approval_request",
            "thread_id": thread_id,
            "session_id": self.__string_or_none(bypass.get("session_id")),
            "run_id": self.__string_or_none(bypass.get("run_id")),
            "origin_type": self.__string_or_none(bypass.get("origin_type"))
            or GraphApprovalOriginType.ManualScopeRun.value,
            "scope_table": self.__string_or_none(bypass.get("scope_table")) or Card.__tablename__,
            "scope_uid": self.__string_or_none(bypass.get("scope_uid")) or card.get_uid(),
            "document_name": self.__string_or_none(bypass.get("document_name")),
            "action_type": "api_call",
            "permission": self.__string_or_none(bypass.get("permission")) or "edit",
            "tool_name": self.__string_or_none(bypass.get("tool_name")) or "record_orchestration_bypass",
            "api_name": self.__string_or_none(bypass.get("api_name")) or "record_orchestration_bypass",
            "message": bypass["reason"],
            "preview": self.__dict_or_default(
                bypass.get("preview"),
                {
                    "title": "Orchestration approval required",
                    "summary": bypass["reason"],
                    "details": f"{bypass.get('risk_level') or 'unknown'}: {bypass.get('action_type') or 'unknown'}",
                },
            ),
            "request_payload": self.__dict_or_default(
                bypass.get("request_payload"),
                {
                    "api_name": "record_orchestration_bypass",
                    "project_uid": project.get_uid(),
                    "card_uid": card.get_uid(),
                    "risk_level": bypass.get("risk_level"),
                    "action_type": bypass.get("action_type"),
                },
            ),
        }

        return self._get_service(GraphApprovalRequestService).create_from_interrupt(
            project,
            interrupt,
            user=user_or_bot if isinstance(user_or_bot, User) else None,
            bot=user_or_bot if isinstance(user_or_bot, Bot) else None,
        )

    def __get_bypass_metadata(self, bypass: dict[str, Any]) -> dict[str, Any]:
        return {
            key: bypass[key]
            for key in (
                "allowed",
                "requires_approval",
                "reason",
                "risk_level",
                "action_type",
                "checked_at",
                "approval_request_uid",
            )
            if key in bypass
        }

    @staticmethod
    def __string_or_none(value: Any) -> str | None:
        if value is None:
            return None
        value = str(value).strip()
        return value or None

    @staticmethod
    def __dict_or_default(value: Any, default: dict[str, Any]) -> dict[str, Any]:
        return value if isinstance(value, dict) else default

    def __dispatch_assigned_bot(
        self,
        user_or_bot: TUserOrBot,
        project: Project,
        card: Card,
        metadata: dict[str, Any],
    ) -> None:
        bot_uid = self.__string_or_none(metadata.get("assigned_bot_uid"))
        if not bot_uid:
            return

        target_bot = InfraHelper.get_by_id_like(Bot, bot_uid)
        if not target_bot or target_bot.id == user_or_bot.id:
            return

        dumped_models = [
            (Project.__tablename__, project.model_dump()),
            (Card.__tablename__, card.model_dump()),
        ]
        BotDefaultTask.bot_mentioned(user_or_bot, target_bot, "card", dumped_models)

    def __mark_suggestion_created(self, card: Card, suggestion: dict[str, Any], child_card_uid: str) -> None:
        key = SYSTEM_TASK_METADATA_KEYS["suggestions"]
        serialized: str | None = None

        def update_suggestions(value: str | None) -> str | None:
            nonlocal serialized
            if not value:
                return None

            try:
                suggestions = loads(value)
            except ValueError:
                return None

            if not isinstance(suggestions, list):
                return None

            for item in suggestions:
                if not isinstance(item, dict) or item.get("created_card_uid"):
                    continue
                if not self.__is_same_suggestion(item, suggestion):
                    continue

                item["created_card_uid"] = child_card_uid
                serialized = dumps(suggestions, ensure_ascii=False)
                return serialized

            return None

        self.repo.metadata.update_value_by_key(CardMetadata, card, key, update_suggestions)
        if serialized is not None:
            MetadataPublisher.updated_metadata(SocketTopic.BoardCard, card.get_uid(), key, serialized)

    def __is_same_suggestion(self, left: dict[str, Any], right: dict[str, Any]) -> bool:
        return all(
            left.get(key) == right.get(key)
            for key in ("title", "type", "assigned_agent", "risk_level")
            if left.get(key) or right.get(key)
        )

    def __create_failure_comment(
        self,
        user_or_bot: TUserOrBot,
        project: Project,
        card: Card,
        verification: dict[str, Any],
        failure: dict[str, Any],
    ) -> None:
        content = self.__format_failure_comment(verification, failure)
        if not content:
            return
        self._get_service(CardCommentService).create(user_or_bot, project, card, EditorContentModel(content=content))

    def __format_failure_comment(self, verification: dict[str, Any], failure: dict[str, Any]) -> str:
        lines = ["Verification failed"]
        summary = failure.get("summary") or verification.get("summary")
        if summary:
            lines.extend(["", f"Summary: {summary}"])
        if failure.get("cause"):
            lines.append(f"Cause: {failure['cause']}")

        reproduction = self.__metadata_string_list(failure.get("reproduction"))
        if reproduction:
            lines.extend(["", "Reproduction:"])
            lines.extend(f"{index}. {item}" for index, item in enumerate(reproduction, start=1))

        recommendation = self.__metadata_string_list(failure.get("recommendation"))
        if recommendation:
            lines.extend(["", "Recommendation:"])
            lines.extend(f"- {item}" for item in recommendation)

        checked_at = failure.get("checked_at") or verification.get("checked_at")
        if checked_at:
            lines.extend(["", f"Checked at: {checked_at}"])

        return "\n".join(lines)

    def __metadata_string_list(self, value: Any) -> list[str]:
        if not isinstance(value, list):
            return []
        return [str(item).strip() for item in value if str(item).strip()]

    def __serialize_metadata_value(self, value: Any) -> str | None:
        if value is None:
            return None
        if isinstance(value, str):
            value = value.strip()
            return value or None
        if isinstance(value, bool | int | float):
            return str(value).lower() if isinstance(value, bool) else str(value)
        if isinstance(value, list | dict):
            if not value:
                return None
            return dumps(value, ensure_ascii=False)
        return str(value)
