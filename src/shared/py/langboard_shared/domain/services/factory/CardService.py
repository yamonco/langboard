import base64
import json
from binascii import Error as Base64Error
from datetime import datetime, timedelta
from typing import Any, Literal, Sequence, cast, overload
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from ....ai import BotScheduleHelper, BotScopeHelper
from ....core.db import DbSession, EditorContentModel, SqlBuilder
from ....core.domain import BaseDomainService
from ....core.domain.BaseDomainService import TMutableValidatorMap
from ....core.exceptions.CardDeleteForbidden import CardDeleteForbidden
from ....core.exceptions.CardDescriptionConflict import CardDescriptionConflict
from ....core.schema import TimeBasedPagination
from ....core.types import SafeDateTime, SnowflakeID
from ....core.types.ParamTypes import (
    TCardParam,
    TColumnParam,
    TProjectLabelParam,
    TProjectParam,
    TUserOrBot,
    TWikiParam,
)
from ....core.utils.Converter import convert_python_data
from ....helpers import InfraHelper
from ....publishers import CardPublisher
from ....tasks.activities import CardActivityTask
from ....tasks.bots import CardBotTask
from ....tasks.webhooks.ExecutionReadinessUow import execution_readiness_uow
from ...models import (
    Bot,
    Card,
    CardAssignedProjectLabel,
    CardAssignedUser,
    CardBotSchedule,
    CardBotScope,
    CardRelationship,
    CardVerificationRecord,
    Checkitem,
    Checklist,
    GlobalCardRelationshipType,
    Project,
    ProjectColumn,
    ProjectWiki,
    User,
)
from ...models.Checkitem import CheckitemStatus
from ...models.ProjectRole import ProjectRoleAction
from ..CardVerification import VerificationConflict, VerificationSubmission
from ..CardWorkState import project_work_state
from ..DependencyPolicy import dependency_blockers
from ..ExecutionGeneration import execution_generations
from .CardContentBlockService import CardContentBlockService
from .CardRelationshipService import CardRelationshipService
from .CheckitemService import CheckitemService
from .GraphApprovalRequestService import GraphApprovalRequestService
from .NotificationService import NotificationService
from .ProjectLabelService import ProjectLabelService
from .ProjectService import ProjectService
from .ProjectWikiService import ProjectWikiService
from .WorkflowStagePolicyService import WorkflowStagePolicyService


class CardService(BaseDomainService):
    CONTEXT_DESCRIPTION_MAX_LENGTH = 1200
    LINKED_RESOURCE_PREVIEW_MAX_LENGTH = 240

    @staticmethod
    def _contains_relationship_type() -> GlobalCardRelationshipType:
        """Choose a system containment type instead of relying on query order."""

        relation_type = next(
            (
                candidate
                for candidate in InfraHelper.get_all(GlobalCardRelationshipType)
                if candidate.is_system_default and candidate.machine_semantic == "contains" and candidate.is_active
            ),
            None,
        )
        if relation_type is None:
            raise ValueError("System contains relationship type is missing")
        return relation_type

    UNREAD_TARGET_DESCRIPTION = "description"
    UNREAD_TARGET_COMMENT = "comment"
    UNREAD_TARGET_CARD = "card"

    @staticmethod
    def name() -> str:
        """DO NOT EDIT THIS METHOD"""
        return "card"

    @staticmethod
    def next_change_seq() -> int:
        """Draw the next monotonic cursor from the global change sequence."""

        with DbSession.use(readonly=False) as db:
            row = db.exec(select(func.nextval("content_change_seq"))).first()
            return int((row[0] if isinstance(row, tuple) else row) or 0)

    def mark_card_changed(
        self,
        card: Card,
        target_type: str,
        target_id: SnowflakeID | None = None,
    ) -> None:
        """Stamp the newest change snapshot on a card (O(1), no member fan-out)."""

        card.last_change_seq = self.next_change_seq()
        card.last_change_target_type = target_type
        card.last_change_target_id = target_id
        card.last_change_at = SafeDateTime.now()
        self.repo.card.update(card)
        changed_card = card.model_copy(deep=True)
        with DbSession.use(readonly=False) as db:
            db.after_commit(lambda: CardPublisher.metadata_changed(changed_card))

    def get_card_read_state(self, project: TProjectParam, card: TCardParam) -> dict[str, Any] | None:
        records = InfraHelper.get_records_with_foreign_by_params((Project, project), (Card, card))
        if not records:
            return None
        project, card = records
        if card.project_id != project.id:
            return None
        return {"car…14180 tokens truncated…       items.append({"title": title, "is_checked": is_checked})

        if not items:
            return {"checklist_uid": None, "item_count": 0, "message": "No valid checkbox titles"}

        # Create the native checklist via ChecklistService
        checklist_service = self._get_service_by_name("checklist")
        checklist = checklist_service.create(user_or_bot, project, card.get_uid(), "Converted checklist")
        if not checklist:
            return None

        # Create checkitems with completion state
        checkitem_service = self._get_service_by_name("checkitem")
        for item in items:
            created = checkitem_service.create(user_or_bot, project, card.get_uid(), checklist.get_uid(), item["title"])
            if created and item["is_checked"]:
                created.is_checked = True
                self.repo.checkitem.update(created)

        # Remove checkbox lines from the description
        lines = markdown.split("\n")
        kept = [line for line in lines if not pattern.match(line)]
        new_markdown = "\n".join(kept)
        new_markdown = re.sub(r"\n{3,}", "\n\n", new_markdown).strip()

        card.description = EditorContentModel(content=new_markdown)
        self.repo.card.update(card)
        CardPublisher.updated(project, card, None, {"description": "checkboxes converted"})

        return {
            "checklist_uid": checklist.get_uid(),
            "item_count": len(items),
            "checked_count": sum(1 for item in items if item["is_checked"]),
            "remaining_markdown": new_markdown,
        }

    def get_section_comment_counts(
        self,
        project: TProjectParam | None,
        card: TCardParam | None,
    ) -> list[dict[str, Any]] | None:
        """Return comment counts grouped by section_anchor for the gutter UI."""

        params = InfraHelper.get_records_with_foreign_by_params((Project, project), (Card, card))
        if not params:
            return None
        project, card = params

        raw_comments = self.repo.card_comment.get_all_by_card(card)
        counts: dict[str, int] = {}
        for comment, _ in raw_comments:
            anchor_value = getattr(comment, "section_anchor", None)
            if anchor_value:
                counts[anchor_value] = counts.get(anchor_value, 0) + 1

        return [{"anchor": anchor_value, "count": count} for anchor_value, count in sorted(counts.items())]

    def copy_selection_to_wiki(
        self,
        user_or_bot: TUserOrBot,
        project: TProjectParam | None,
        card: TCardParam | None,
        selected_markdown: str,
        wiki_title: str | None = None,
    ) -> dict[str, Any] | None:
        """Copy the selected body fragment into a new project wiki.

        The original card body is preserved unchanged; no relationship or link
        is created between the card and the wiki.
        """
        params = InfraHelper.get_records_with_foreign_by_params((Project, project), (Card, card))
        if not params:
            return None
        project, card = params

        selected_markdown = selected_markdown.strip()
        if not selected_markdown:
            return None

        # Derive title from the first meaningful line or use the provided one
        if not wiki_title:
            wiki_title = next(
                (line.lstrip("#-*> ").strip() for line in selected_markdown.split("\n") if line.strip()),
                "Untitled wiki",
            )
            wiki_title = wiki_title[:300]

        wiki_service = self._get_service_by_name("project_wiki")
        result = wiki_service.create(user_or_bot, project, wiki_title, EditorContentModel(content=selected_markdown))
        if not result:
            return None

        wiki, api_wiki = result
        return {
            "wiki_uid": wiki.get_uid(),
            "wiki_title": wiki_title,
            "card_body_unchanged": True,
        }

    def get_change_feed(
        self,
        project: TProjectParam | None,
        limit: int = 50,
        before_activity_uid: str | None = None,
    ) -> dict[str, Any] | None:
        """Return a cursor-based board change feed for external orchestrators.

        Each entry contains the activity type, actor, affected card, and a
        stable cursor for pagination. Consumers use the cursor for idempotent
        incremental polling.
        """
        from ...models import ProjectActivity

        project = InfraHelper.get_by_id_like(Project, project)
        if not project:
            return None

        raw_activities = self.repo.activity.get_list_by_project(
            project,
            TimeBasedPagination(page=1, limit=limit + 1),
        )
        activities, _ = raw_activities if isinstance(raw_activities, tuple) else (raw_activities, 0)

        # Filter to card-level activities only (external orchestrators care about cards)
        card_activities = []
        for activity in activities:
            if not isinstance(activity, ProjectActivity):
                continue
            if not hasattr(activity, "card_id") or activity.card_id is None:
                continue
            card_activities.append(activity)

        has_more = len(card_activities) > limit
        page = card_activities[:limit]

        entries = []
        for activity in page:
            entry = {
                "activity_uid": activity.get_uid(),
                "activity_type": activity.activity_type.value
                if hasattr(activity.activity_type, "value")
                else str(activity.activity_type),
                "card_uid": activity.card_id.to_short_code() if activity.card_id else None,
                "project_uid": project.get_uid(),
                "created_at": str(activity.created_at),
            }
            if hasattr(activity, "user_id") and activity.user_id:
                entry["actor_user_uid"] = activity.user_id.to_short_code()
            elif hasattr(activity, "bot_id") and activity.bot_id:
                entry["actor_bot_uid"] = activity.bot_id.to_short_code()
            entries.append(entry)

        next_cursor = page[-1].get_uid() if has_more and page else None
        return {"entries": entries, "has_more": has_more, "next_cursor": next_cursor}

    def update(
        self,
        user_or_bot: TUserOrBot,
        project: TProjectParam | None,
        card: TCardParam | None,
        form: dict[str, Any],
        *,
        expected_description: str | None = None,
    ) -> dict[str, Any] | Literal[True] | None:
        """Update a card, optionally guarding a description-only edit against concurrent writes."""

        if expected_description is not None and set(form) != {"description"}:
            raise ValueError("Conditional description updates cannot change other card fields")
        params = InfraHelper.get_records_with_foreign_by_params((Project, project), (Card, card))
        if not params:
            return None
        project, card = params
        if card.is_linked_resource:
            return None

        validators: TMutableValidatorMap = {
            "title": "not_empty",
            "deadline_at": "nullable",
            "description": "default",
        }
        old_record = self.apply_mutates(card, form, validators)
        if not old_record:
            return True

        checkitem_cardified_from = None
        if "title" in old_record:
            checkitem_cardified_from = InfraHelper.get_by(Checkitem, "cardified_id", card.id)
            if checkitem_cardified_from:
                checkitem_cardified_from.title = card.title
                self.repo.checkitem.update(checkitem_cardified_from)
            self.sync_completion_checkitem_title(card)

        target_type = self.UNREAD_TARGET_DESCRIPTION if "description" in old_record else self.UNREAD_TARGET_CARD
        card.last_change_seq = self.next_change_seq()
        card.last_change_target_type = target_type
        card.last_change_target_id = None
        card.last_change_at = SafeDateTime.now()

        if expected_description is None:
            self.repo.card.update(card)
        elif not self.repo.card.update_description_if_current(card, expected_description):
            raise CardDescriptionConflict("Card description changed after review: concurrent update")

        if "description" in old_record or "deadline_at" in old_record:
            if self.is_check_card(card):
                self.ensure_completion_checklist(card)
            else:
                self.remove_completion_checklist(card)

        model: dict[str, Any] = {}
        for key in form:
            if key not in validators or key not in old_record:
                continue
            model[key] = convert_python_data(getattr(card, key))

        CardPublisher.updated(project, card, checkitem_cardified_from, model)

        if "description" in model and card.description:
            notification_service = self._get_service(NotificationService)
            notification_service.notify_mentioned_in_card(user_or_bot, project, card)

        CardActivityTask.card_updated(user_or_bot, project, old_record, card)
        CardBotTask.card_updated(user_or_bot, project, card)

        return model

    def change_order(
        self,
        user_or_bot: TUserOrBot,
        project: TProjectParam | None,
        card: TCardParam | None,
        order: int,
        new_column: TColumnParam | None | None,
    ) -> bool | None:
        params = InfraHelper.get_records_with_foreign_by_params((Project, project), (Card, card))
        if not params:
            return None
        project, card = params

        with execution_readiness_uow() as execution:
            card = execution.db.exec(
                SqlBuilder.select.table(Card)
                .where(Card.column("id") == card.id)
                .where(Card.column("project_id") == project.id)
                .with_for_update()
            ).first()
            if card is None or card.deleted_at is not None:
                return None
            old_column = InfraHelper.get_by_id_like(ProjectColumn, card.project_column_id)
            if not old_column or old_column.project_id != project.id:
                return None
            if new_column:
                new_column = InfraHelper.get_by_id_like(ProjectColumn, new_column)
                if not new_column or new_column.project_id != project.id or new_column.deleted_at is not None:
                    return None
                if card.is_linked_resource and new_column.is_archive:
                    if not self.can_delete(user_or_bot, card):
                        raise CardDeleteForbidden("Only the original card author or an administrator can delete this card")
                    return self._delete_card(user_or_bot, project, card)
            execution.watch_card_and_dependents(card.id)
            old_order = card.order
            if new_column:
                card.project_column_id = new_column.id
                card.archived_at = SafeDateTime.now() if new_column.is_archive else None
            card.order = order
            self.repo.card.update_row_order(card, old_column, old_order, order, new_column, preserve_shifted_updated_at=True)
            self.repo.card.update(card)
            self._get_service(WorkflowStagePolicyService).apply_transition(user_or_bot, project, card, old_column, new_column)
            if new_column is not None:
                card.last_change_seq = self.next_change_seq()
                card.last_change_target_type = self.UNREAD_TARGET_CARD
                card.last_change_target_id = None
                card.last_change_at = SafeDateTime.now()
                self.repo.card.update(card)
            execution.db.after_commit(lambda: self.notify_order_changed(user_or_bot, project, card, old_column, new_column))
        return True

    def notify_order_changed(
        self,
        user_or_bot: TUserOrBot,
        project: Project,
        card: Card,
        old_column: ProjectColumn,
        new_column: ProjectColumn | None,
    ) -> None:
        CardPublisher.order_changed(project, card, old_column, cast(ProjectColumn, new_column))
        if new_column is not None:
            self.publish_work_states(project, [card.id, *self._dependency_children(card)])

        if new_column and not card.is_linked_resource:
            CardBotTask.enqueue_card_moved_webhook(
                user_or_bot, project, card, old_column, cast(ProjectColumn, new_column)
            )
            CardActivityTask.card_moved(user_or_bot, project, card, old_column)
            CardBotTask.card_moved(user_or_bot, project, card, old_column, False)

    def assign_self(self, user: User, project: TProjectParam, card: TCardParam) -> dict[str, Any]:
        """Assign the authenticated project member additively; never infer an identity."""
        params = InfraHelper.get_records_with_foreign_by_params((Project, project), (Card, card))
        if not params:
            raise ValueError("Card not found in project")
        project, card = params
        member = self.repo.project_assigned_user.find_by_user_and_project(user, project)
        if member is None:
            raise ValueError("Current user must first be onboarded to this project")
        previous = self.repo.card_assigned_user.get_all_by_card(card, only_ids=True)
        changed = self.repo.card_assigned_user.add_member(card, member)
        if changed:
            users = [assigned for assigned, _ in self.repo.card_assigned_user.get_all_by_card(card)]
            CardPublisher.assigned_users_updated(project, card, users)
            CardActivityTask.card_assigned_users_updated(
                user, project, card, [uid for uid, _ in previous], [item.id for item in users]
            )
        return {"card_uid": card.get_uid(), "assigned_user_uid": user.get_uid(), "changed": changed}

    def assign_member(
        self, actor: TUserOrBot, project: TProjectParam, card: TCardParam, assignee_uid: str
    ) -> dict[str, Any]:
        """Add an existing active project member; never invite or replace other assignees."""
        params = InfraHelper.get_records_with_foreign_by_params((Project, project), (Card, card))
        if not params:
            raise LookupError("Card not found in project")
        project, card = params
        assignee = InfraHelper.get_by_id_like(User, assignee_uid)
        if assignee is None or assignee.deleted_at is not None or assignee.activated_at is None:
            raise ValueError("Select an active member of this project")
        member = self.repo.project_assigned_user.find_by_user_and_project(assignee, project)
        if member is None:
            raise ValueError("Select an active member of this project")
        previous = self.repo.card_assigned_user.get_all_by_card(card, only_ids=True)
        changed = self.repo.card_assigned_user.add_member(card, member)
        users = [assigned for assigned, _ in self.repo.card_assigned_user.get_all_by_card(card)]
        if changed:
            CardPublisher.assigned_users_updated(project, card, users)
            CardActivityTask.card_assigned_users_updated(
                actor, project, card, [uid for uid, _ in previous], [item.id for item in users]
            )
            self._get_service(NotificationService).notify_assigned_to_card(actor, assignee, project, card)
        return {"changed": changed, "member_uids": [assigned.get_uid() for assigned in users]}

    def update_assigned_users(
        self,
        user_or_bot: TUserOrBot,
        project: TProjectParam | None,
        card: TCardParam | None,
        assign_user_uids: list[str] | None = None,
    ) -> list[User] | None:
        params = InfraHelper.get_records_with_foreign_by_params((Project, project), (Card, card))
        if not params:
            return None
        project, card = params
        if card.is_linked_resource:
            return None

        old_assigned_users = self.repo.card_assigned_user.get_all_by_card(card, only_ids=True)
        old_assigned_user_ids = [user_id for user_id, _ in old_assigned_users]

        if old_assigned_user_ids:
            self.repo.card_assigned_user.delete_all_by_card(card)

        raw_users = []
        if assign_user_uids:
            raw_users = self.repo.project_assigned_user.get_all_by_project(project, where_users_in=assign_user_uids)

        new_users: list[User] = []
        if raw_users:
            for user, project_assigned_user in raw_users:
                card_assigned_user = CardAssignedUser(
                    project_assigned_id=project_assigned_user.id,
                    card_id=card.id,
                    user_id=user.id,
                )
                self.repo.card_assigned_user.insert(card_assigned_user)
                new_users.append(user)

        CardPublisher.assigned_users_updated(project, card, new_users)
        self.mark_card_changed(card, self.UNREAD_TARGET_CARD)

        notification_service = self._get_service(NotificationService)
        for user in new_users:
            if user.id in old_assigned_user_ids:
                continue
            notification_service.notify_assigned_to_card(user_or_bot, user, project, card)

        CardActivityTask.card_assigned_users_updated(
            user_or_bot,
            project,
            card,
            old_assigned_user_ids,
            [user.id for user in new_users],
        )
        return new_users

    def update_labels(
        self,
        user_or_bot: TUserOrBot,
        project: TProjectParam | None,
        card: TCardParam | None,
        labels: Sequence[TProjectLabelParam],
        *,
        dispatch_effects: bool = True,
    ) -> bool | None:
        params = InfraHelper.get_records_with_foreign_by_params((Project, project), (Card, card))
        if not params:
            return None
        project, card = params
        if card.is_linked_resource:
            return None

        old_labels = self.repo.project_label.get_all_by_card(card)

        self.repo.card_assigned_project_label.delete_all_by_card(card)

        new_labels = self.repo.project_label.get_all_by_project(project, where_in=labels)
        for label in new_labels:
            card_assigned_label = CardAssignedProjectLabel(card_id=card.id, project_label_id=label.id)
            self.repo.card_assigned_project_label.insert(card_assigned_label)

        if dispatch_effects:
            CardPublisher.labels_updated(project, card, new_labels)
        self.mark_card_changed(card, self.UNREAD_TARGET_CARD)
        if dispatch_effects:
            CardActivityTask.card_labels_updated(
                user_or_bot,
                project,
                card,
                [label.id for label in old_labels],
                [label.id for label in new_labels],
            )
            CardBotTask.card_labels_updated(user_or_bot, project, card)

        return True

    def archive(self, user_or_bot: TUserOrBot, project: TProjectParam | None, card: TCardParam | None) -> bool | None:
        params = InfraHelper.get_records_with_foreign_by_params((Project, project), (Card, card))
        if not params:
            return None
        project, card = params

        if card.is_linked_resource:
            if not self.can_delete(user_or_bot, card):
                raise CardDeleteForbidden("Only the original card author or an administrator can delete this card")
            return self._delete_card(user_or_bot, project, card)
        if card.archived_at:
            return True

        column_archive = self.repo.project_column.get_or_create_archive_if_not_exists(project.id)

        self.change_order(user_or_bot, project, card, 0, column_archive)

        return True

    def delete(self, user_or_bot: TUserOrBot, project: TProjectParam | None, card: TCardParam | None) -> bool:
        params = InfraHelper.get_records_with_foreign_by_params((Project, project), (Card, card))
        if not params:
            return False
        project, card = params

        if not card.archived_at and not card.is_linked_resource:
            return False

        if not self.can_delete(user_or_bot, card):
            raise CardDeleteForbidden("Only the original card author or an administrator can delete this card")

        return self._delete_card(user_or_bot, project, card)

    def _delete_card(self, user_or_bot: TUserOrBot, project: Project, card: Card) -> bool:
        """Delete only the board-side card and its dependent work records."""

        dependency_children = self._dependency_children(card)
        started_checkitems = self.repo.checkitem.get_all_started_checkitem_by_card(card)

        checkitem_service = self._get_service(CheckitemService)
        current_time = SafeDateTime.now()
        for checkitem in started_checkitems:
            checkitem_service.change_status(
                user_or_bot,
                project,
                card,
                checkitem,
                CheckitemStatus.Stopped,
                current_time,
                should_publish=False,
            )

        with execution_readiness_uow() as execution:
            execution.watch_card_and_dependents(card.id)
            self.repo.card_assigned_user.delete_all_by_card(card)
            self.repo.card_relationship.delete_all_by_card(card)

            BotScopeHelper.delete_by_scope(CardBotScope, card)
            BotScheduleHelper.unschedule_by_scope(CardBotSchedule, card)
            self._get_service(GraphApprovalRequestService).cancel_pending_by_scope(
                project,
                Card.__tablename__,
                card.get_uid(),
                reason="card deleted",
            )

            # Linked cards are disposable references. Purging the board-side row
            # allows the same source to be linked again while its Wiki stays intact.
            is_linked_resource = card.is_linked_resource
            self.repo.card.delete(card, purge=is_linked_resource)
            self.repo.card.reoder_after_delete(card.project_column_id, card.order)

        CardPublisher.deleted(project, card)
        self.publish_work_states(project, dependency_children)
        if not is_linked_resource:
            CardActivityTask.card_deleted(user_or_bot, project, card)
            CardBotTask.card_deleted(user_or_bot, project, card)

        return True

    @staticmethod
    def can_delete(user_or_bot: TUserOrBot, card: Card) -> bool:
        """Allow administrators or the immutable creator.

        Legacy cards without any recorded creator are deletable by whoever already
        passed the CardDelete role gate; cards with a known creator stay protected."""

        if card.created_by_user_id is None and card.created_by_bot_id is None:
            return True

        if isinstance(user_or_bot, User):
            return user_or_bot.is_admin or (
                card.created_by_user_id is not None and card.created_by_user_id == user_or_bot.id
            )
        return card.created_by_bot_id is not None and card.created_by_bot_id == user_or_bot.id
