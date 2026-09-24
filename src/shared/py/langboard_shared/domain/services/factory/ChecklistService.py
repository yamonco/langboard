from typing import Any
from ....core.domain import BaseDomainService
from ....core.types import SafeDateTime
from ....core.types.ParamTypes import TCardParam, TChecklistParam, TProjectParam, TUserOrBot
from ....helpers import InfraHelper
from ....publishers import ChecklistPublisher
from ....tasks.activities import CardChecklistActivityTask
from ....tasks.bots import CardChecklistBotTask
from ...models import Card, Checklist, Project
from ...models.Checkitem import CheckitemStatus
from .CheckitemService import CheckitemService
from .NotificationService import NotificationService


class ChecklistService(BaseDomainService):
    @staticmethod
    def name() -> str:
        """DO NOT EDIT THIS METHOD"""
        return "checklist"

    def _mark_card_changed_for_unread(self, card, target_type: str, target_id=None) -> None:
        """Stamp the unread cursor for this card change (lazy import avoids cycles)."""
        from .CardService import CardService

        card_service = self._get_service(CardService)
        card_service.mark_card_changed(card, target_type, target_id)

    def get_by_id_like(self, checklist: TChecklistParam | None) -> Checklist | None:
        checklist = InfraHelper.get_by_id_like(Checklist, checklist)
        return checklist

    def get_api_list_by_card(
        self,
        card: TCardParam | None,
        limit: int | None = None,
        checkitems_limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """Return checklists, optionally bounding both nesting levels in the repository query."""

        card = InfraHelper.get_by_id_like(Card, card)
        if not card:
            return []

        raw_checklists = self.repo.checklist.get_all_by_card(card, limit=limit, is_system=False)
        if not raw_checklists:
            return []

        checkitem_service = self._get_service(CheckitemService)
        checkitems_map = (
            checkitem_service.get_api_map_by_card(card)
            if checkitems_limit is None
            else {
                checklist.id: checkitem_service.get_api_list_by_checklist(card, checklist, limit=checkitems_limit)
                for checklist in raw_checklists
            }
        )
        checklists = []
        for raw_checklist in raw_checklists:
            checkitems = checkitems_map.get(raw_checklist.id, [])
            checklists.append(
                {
                    **raw_checklist.api_response(),
                    "checkitems": checkitems,
                }
            )

        return checklists

    def get_api_list_only_by_card(self, card: TCardParam | None) -> list[dict[str, Any]]:
        card = InfraHelper.get_by_id_like(Card, card)
        if not card:
            return []

        checklists = self.repo.checklist.get_all_by_card(card, is_system=False)
        return [checklist.api_response() for checklist in checklists]

    def get_api_list_only_by_project(
        self,
        project: TProjectParam | None,
        archive_visible_since: SafeDateTime | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        project = InfraHelper.get_by_id_like(Project, project)
        if not project:
            return []

        checklists = self.repo.checklist.get_all_by_project(
            project,
            archive_visible_since=archive_visible_since,
            limit=limit,
            is_system=False,
        )
        return [checklist.api_response() for checklist in checklists]

    def create(
        self,
        user_or_bot: TUserOrBot,
        project: TProjectParam | None,
        card: TCardParam | None,
        title: str,
        *,
        dispatch_effects: bool = True,
        order_override: int | None = None,
    ) -> Checklist | None:
        params = InfraHelper.get_records_with_foreign_by_params((Project, project), (Card, card))
        if not params:
            return None
        project, card = params
        if card.is_linked_resource:
            return None

        checklist = Checklist(
            card_id=card.id,
            title=title,
            order=order_override if order_override is not None else self.repo.checklist.get_next_order(card),
        )
        self.repo.checklist.insert(checklist)

        card_service = self._get_service_by_name("card")
        card_service.remove_completion_checklist(card)

        self._mark_card_changed_for_unread(card, "checklist", checklist.id)
        if dispatch_effects:
            self.dispatch_created(user_or_bot, project, card, checklist)

        return checklist

    def dispatch_created(
        self, user_or_bot: TUserOrBot, project: Project, card: Card, checklist: Checklist, *, include_bot: bool = True
    ) -> None:
        ChecklistPublisher.created(card, checklist)
        CardChecklistActivityTask.card_checklist_created(user_or_bot, project, card, checklist)
        if include_bot:
            CardChecklistBotTask.card_checklist_created(user_or_bot, project, card, checklist)

    def change_title(
        self,
        user_or_bot: TUserOrBot,
        project: TProjectParam | None,
        card: TCardParam | None,
        checklist: TChecklistParam | None,
        title: str,
    ) -> bool | None:
        params = InfraHelper.get_records_with_foreign_by_params(
            (Project, project), (Card, card), (Checklist, checklist)
        )
        if not params:
            return None
        project, card, checklist = params

        if checklist.title == title:
            return True

        old_title = checklist.title
        checklist.title = title

        self.repo.checklist.update(checklist)

        ChecklistPublisher.title_changed(card, checklist)
        self._mark_card_changed_for_unread(card, "checklist", checklist.id)
        CardChecklistActivityTask.card_checklist_title_changed(user_or_bot, project, card, old_title, checklist)
        CardChecklistBotTask.card_checklist_title_changed(user_or_bot, project, card, checklist)

        return True

    def change_order(
        self,
        project: TProjectParam | None,
        card: TCardParam | None,
        checklist: TChecklistParam | None,
        order: int,
    ) -> bool | None:
        params = InfraHelper.get_records_with_foreign_by_params(
            (Project, project), (Card, card), (Checklist, checklist)
        )
        if not params:
            return None
        project, card, checklist = params

        old_order = checklist.order
        checklist.order = order

        self.repo.checklist.update_column_order(checklist, card, old_order, order)

        ChecklistPublisher.order_changed(card, checklist)

        return True

    def toggle_checked(
        self,
        user_or_bot: TUserOrBot,
        project: TProjectParam | None,
        card: TCardParam | None,
        checklist: TChecklistParam | None,
    ) -> bool | None:
        params = InfraHelper.get_records_with_foreign_by_params(
            (Project, project), (Card, card), (Checklist, checklist)
        )
        if not params:
            return None
        project, card, checklist = params

        checklist.is_checked = not checklist.is_checked
        self.repo.checklist.update(checklist)

        ChecklistPublisher.checked_changed(card, checklist)
        if not checklist.is_system:
            self._mark_card_changed_for_unread(card, "checklist", checklist.id)

        if checklist.is_checked:
            CardChecklistActivityTask.card_checklist_checked(user_or_bot, project, card, checklist)
            CardChecklistBotTask.card_checklist_checked(user_or_bot, project, card, checklist)
        else:
            CardChecklistActivityTask.card_checklist_unchecked(user_or_bot, project, card, checklist)
            CardChecklistBotTask.card_checklist_unchecked(user_or_bot, project, card, checklist)

        return True

    def notify(
        self,
        user_or_bot: TUserOrBot,
        project: TProjectParam | None,
        card: TCardParam | None,
        checklist: TChecklistParam | None,
        user_uids: list[str],
    ) -> bool | None:
        params = InfraHelper.get_records_with_foreign_by_params(
            (Project, project), (Card, card), (Checklist, checklist)
        )
        if not params:
            return None
        project, card, checklist = params

        assigned_users = self.repo.project_assigned_user.get_all_by_project(project, where_users_in=user_uids)

        for user, _ in assigned_users:
            notification_service = self._get_service(NotificationService)
            notification_service.notify_checklist(user_or_bot, user, project, card, checklist)

        return True

    def delete(
        self,
        user_or_bot: TUserOrBot,
        project: TProjectParam | None,
        card: TCardParam | None,
        checklist: TChecklistParam | None,
    ) -> bool | None:
        params = InfraHelper.get_records_with_foreign_by_params(
            (Project, project), (Card, card), (Checklist, checklist)
        )
        if not params:
            return None
        project, card, checklist = params

        checkitem_service = self._get_service(CheckitemService)
        checkitems = self.repo.checkitem.get_all_by_checklist(checklist)
        current_time = SafeDateTime.now()
        for checkitem, _, _ in checkitems:
            checkitem_service.change_status(
                user_or_bot,
                project,
                card,
                checkitem,
                CheckitemStatus.Stopped,
                current_time,
                should_publish=False,
            )

        self.repo.checklist.delete(checklist)

        ChecklistPublisher.deleted(card, checklist)
        self._mark_card_changed_for_unread(card, "checklist")
        CardChecklistActivityTask.card_checklist_deleted(user_or_bot, project, card, checklist)
        CardChecklistBotTask.card_checklist_deleted(user_or_bot, project, card, checklist)

        if not checklist.is_system:
            card_service = self._get_service_by_name("card")
            if card_service.is_check_card(card):
                card_service.ensure_completion_checklist(card)

        return True
