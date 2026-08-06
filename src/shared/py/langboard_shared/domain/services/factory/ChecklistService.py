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

        raw_checklists = self.repo.checklist.get_all_by_card(card, limit=limit)
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

        checklists = self.repo.checklist.get_all_by_card(card)
        return [checklist.api_response() for checklist in checklists]

    def get_api_list_only_by_project(self, project: TProjectParam | None) -> list[dict[str, Any]]:
        project = InfraHelper.get_by_id_like(Project, project)
        if not project:
            return []

        checklists = self.repo.checklist.get_all_by_project(project)
        return [checklist.api_response() for checklist in checklists]

    def create(
        self, user_or_bot: TUserOrBot, project: TProjectParam | None, card: TCardParam | None, title: str
    ) -> Checklist | None:
        params = InfraHelper.get_records_with_foreign_by_params((Project, project), (Card, card))
        if not params:
            return None
        project, card = params

        checklist = Checklist(card_id=card.id, title=title, order=self.repo.checklist.get_next_order(card))
        self.repo.checklist.insert(checklist)

        ChecklistPublisher.created(card, checklist)
        CardChecklistActivityTask.card_checklist_created(user_or_bot, project, card, checklist)
        CardChecklistBotTask.card_checklist_created(user_or_bot, project, card, checklist)

        return checklist

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
        CardChecklistActivityTask.card_checklist_deleted(user_or_bot, project, card, checklist)
        CardChecklistBotTask.card_checklist_deleted(user_or_bot, project, card, checklist)

        return True
