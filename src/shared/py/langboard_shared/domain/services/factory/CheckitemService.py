from typing import Any, cast, overload
from ....core.domain import BaseDomainService
from ....core.schema import TimeBasedPagination
from ....core.types import SafeDateTime
from ....core.types.ParamTypes import TCardParam, TCheckitemParam, TChecklistParam, TProjectParam, TUserOrBot
from ....helpers import InfraHelper
from ....publishers import CheckitemPublisher
from ....tasks.activities import CardCheckitemActivityTask
from ....tasks.bots import CardBotTask, CardCheckitemBotTask
from ...models import Card, Checkitem, CheckitemTimerRecord, Checklist, Project, ProjectColumn, User
from ...models.Checkitem import CheckitemStatus


class CheckitemService(BaseDomainService):
    @staticmethod
    def name() -> str:
        """DO NOT EDIT THIS METHOD"""
        return "checkitem"

    def get_by_id_like(self, checkitem: TCheckitemParam | None) -> Checkitem | None:
        checkitem = InfraHelper.get_by_id_like(Checkitem, checkitem)
        return checkitem

    def get_api_list_by_checklist(
        self, card: TCardParam, checklist: TChecklistParam, limit: int | None = None
    ) -> list[dict[str, Any]]:
        """Return checkitems, optionally enforcing a repository row limit."""

        params = InfraHelper.get_records_with_foreign_by_params((Card, card), (Checklist, checklist))
        if not params:
            return []
        card, checklist = params

        records = self.repo.checkitem.get_all_by_checklist(checklist, limit=limit)

        checkitems = [self.__convert_api_response(card, record) for record in records]
        return checkitems

    def get_api_map_by_card(self, card: TCardParam | None) -> dict[int, list[dict[str, Any]]]:
        card = InfraHelper.get_by_id_like(Card, card)
        if not card:
            return {}

        records = self.repo.checkitem.get_all_by_card(card)

        checkitems_map: dict[int, list[dict[str, Any]]] = {}
        for record in records:
            checkitem, _, _ = record
            api_checkitem = self.__convert_api_response(card, record)
            if checkitem.checklist_id not in checkitems_map:
                checkitems_map[checkitem.checklist_id] = []
            checkitems_map[checkitem.checklist_id].append(api_checkitem)
        return checkitems_map

    def get_tracking_list(
        self, user: User, pagination: TimeBasedPagination
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
        records = self.repo.checkitem.get_all_tracking_scroller(user, pagination)
        checkitems = [checkitem for checkitem, _, _ in records]
        timer_arcs = self.repo.checkitem_timer_record.get_arc_map_by_checkitems(checkitems)

        api_checkitems = []
        api_cards: dict[int, dict[str, Any]] = {}
        api_projects: dict[int, dict[str, Any]] = {}
        for checkitem, card, project in records:
            api_checkitem = checkitem.api_response()
            api_checkitem["card_uid"] = card.get_uid()
            timer_arc = timer_arcs.get(checkitem.id, {})
            first_timer = timer_arc.get("first")
            if first_timer:
                api_checkitem["initial_timer_started_at"] = first_timer.created_at
            last_timer = timer_arc.get("last")
            if last_timer and last_timer.status == CheckitemStatus.Started:
                api_checkitem["timer_started_at"] = last_timer.created_at

            if card.id not in api_cards:
                api_cards[card.id] = card.api_response()

            if project.id not in api_projects:
                api_projects[project.id] = project.api_response()
            api_checkitems.append(api_checkitem)

        return api_checkitems, list(api_cards.values()), list(api_projects.values())

    def create(
        self, user_or_bot: TUserOrBot, project: TProjectParam, card: TCardParam, checklist: TChecklistParam, title: str
    ) -> Checkitem | None:
        params = InfraHelper.get_records_with_foreign_by_params(
            (Project, project), (Card, card), (Checklist, checklist)
        )
        if not params:
            return None
        project, card, checklist = params

        checkitem = Checkitem(
            checklist_id=checklist.id, title=title, order=self.repo.checkitem.get_next_order(checklist)
        )
        self.repo.checkitem.insert(checkitem)

        CheckitemPublisher.created(card, checklist, checkitem)
        CardCheckitemActivityTask.card_checkitem_created(user_or_bot, project, card, checkitem)
        CardCheckitemBotTask.card_checkitem_created(user_or_bot, project, card, checkitem)

        return checkitem

    def change_title(
        self,
        user_or_bot: TUserOrBot,
        project: TProjectParam,
        card: TCardParam,
        checkitem: TCheckitemParam,
        title: str,
    ) -> bool | None:
        params = self.__get_records_by_params(project, card, checkitem)
        if not params:
            return None
        project, card, checkitem = params

        old_title = checkitem.title
        checkitem.title = title
        cardified_card = None
        if checkitem.cardified_id:
            cardified_card = InfraHelper.get_by(Card, "id", checkitem.cardified_id)
            if not cardified_card:
                checkitem.cardified_id = None
            else:
                cardified_card.title = title
                self.repo.card.update(cardified_card)

        self.repo.checkitem.update(checkitem)

        CheckitemPublisher.title_changed(project, card, checkitem, cardified_card)
        CardCheckitemActivityTask.card_checkitem_title_changed(user_or_bot, project, card, old_title, checkitem)
        CardCheckitemBotTask.card_checkitem_title_changed(user_or_bot, project, card, checkitem)

        return True

    def change_deadline(
        self,
        project: TProjectParam,
        card: TCardParam,
        checkitem: TCheckitemParam,
        deadline_at: SafeDateTime | None,
    ) -> bool | None:
        params = self.__get_records_by_params(project, card, checkitem)
        if not params:
            return None
        project, card, checkitem = params

        checkitem.deadline_at = deadline_at
        self.repo.checkitem.update(checkitem)

        CheckitemPublisher.deadline_changed(project, card, checkitem)

        return True

    def change_order(
        self,
        project: TProjectParam,
        card: TCardParam,
        checkitem: TCheckitemParam,
        order: int,
        checklist_uid: str = "",
    ) -> bool | None:
        params = self.__get_records_by_params(project, card, checkitem)
        if not params:
            return None
        project, card, checkitem = params

        old_checklist = InfraHelper.get_by_id_like(Checklist, checkitem.checklist_id)
        if not old_checklist:
            return None

        new_checklist = None
        if checklist_uid:
            new_checklist = InfraHelper.get_by_id_like(Checklist, checklist_uid)
            if not new_checklist or old_checklist.card_id != card.id or new_checklist.card_id != card.id:
                return None

        old_order = checkitem.order
        checkitem.order = order
        self.repo.checkitem.update_row_order(checkitem, old_checklist, old_order, order, new_checklist)

        CheckitemPublisher.order_changed(card, checkitem, old_checklist, new_checklist)

        return True

    def change_status(
        self,
        user_or_bot: TUserOrBot,
        project: TProjectParam,
        card: TCardParam,
        checkitem: TCheckitemParam,
        status: CheckitemStatus,
        current_time: SafeDateTime | None = None,
        should_publish: bool = True,
        from_api: bool = False,
    ) -> bool | None:
        params = self.__get_records_by_params(project, card, checkitem)
        if not params:
            return None
        project, card, checkitem = params
        if checkitem.cardified_id:
            return False

        if checkitem.status == status:
            return True

        if not current_time:
            current_time = SafeDateTime.now()

        if status != CheckitemStatus.Started:
            if not checkitem.user_id:
                return False

            if checkitem.status == CheckitemStatus.Started:
                last_timer_record = cast(
                    CheckitemTimerRecord,
                    self.repo.checkitem_timer_record.get_by_checkitem_and_arc_type(checkitem, "last"),
                )
                accumulated_seconds = int((current_time - last_timer_record.created_at).total_seconds())
                checkitem.accumulated_seconds += accumulated_seconds
                self.repo.checkitem.update(checkitem)
        else:
            if not checkitem.user_id:
                if not isinstance(user_or_bot, User):
                    return False
                checkitem.user_id = user_or_bot.id
            if isinstance(user_or_bot, User):
                started_checkitem = self.repo.checkitem.find_started_checkitem_by_user(user_or_bot)
                if started_checkitem:
                    self.change_status(
                        user_or_bot,
                        project,
                        card,
                        started_checkitem,
                        CheckitemStatus.Paused,
                        current_time,
                    )
            checkitem.is_checked = False

        if status == CheckitemStatus.Stopped and from_api:
            checkitem.is_checked = True

        checkitem.status = status
        self.repo.checkitem.update(checkitem)

        timer_record = CheckitemTimerRecord(checkitem_id=checkitem.id, status=status, created_at=current_time)
        self.repo.checkitem_timer_record.insert(timer_record)

        target_user = None
        if checkitem.user_id:
            target_user = InfraHelper.get_by(User, "id", checkitem.user_id)

        if should_publish:
            CheckitemPublisher.status_changed(project, card, checkitem, timer_record, target_user)

        if status == CheckitemStatus.Started:
            CardCheckitemActivityTask.card_checkitem_timer_started(user_or_bot, project, card, checkitem)
            CardCheckitemBotTask.card_checkitem_timer_started(user_or_bot, project, card, checkitem)
        elif status == CheckitemStatus.Paused:
            CardCheckitemActivityTask.card_checkitem_timer_paused(user_or_bot, project, card, checkitem)
            CardCheckitemBotTask.card_checkitem_timer_paused(user_or_bot, project, card, checkitem)
        elif status == CheckitemStatus.Stopped:
            CardCheckitemActivityTask.card_checkitem_timer_stopped(user_or_bot, project, card, checkitem)
            CardCheckitemBotTask.card_checkitem_timer_stopped(user_or_bot, project, card, checkitem)

        return True

    def toggle_checked(
        self, user_or_bot: TUserOrBot, project: TProjectParam, card: TCardParam, checkitem: TCheckitemParam
    ) -> bool | None:
        params = self.__get_records_by_params(project, card, checkitem)
        if not params:
            return None
        project, card, checkitem = params

        checkitem.is_checked = not checkitem.is_checked

        if checkitem.status != CheckitemStatus.Stopped:
            self.change_status(user_or_bot, project, card, checkitem, CheckitemStatus.Stopped)
        else:
            self.repo.checkitem.update(checkitem)

            CheckitemPublisher.checked_changed(project, card, checkitem)

        if checkitem.is_checked:
            CardCheckitemActivityTask.card_checkitem_checked(user_or_bot, project, card, checkitem)
            CardCheckitemBotTask.card_checkitem_checked(user_or_bot, project, card, checkitem)
        else:
            CardCheckitemActivityTask.card_checkitem_unchecked(user_or_bot, project, card, checkitem)
            CardCheckitemBotTask.card_checkitem_unchecked(user_or_bot, project, card, checkitem)

        return True

    def cardify(
        self,
        user_or_bot: TUserOrBot,
        project: TProjectParam,
        card: TCardParam,
        checkitem: TCheckitemParam,
        column_uid: str | None = None,
    ) -> bool | None:
        params = self.__get_records_by_params(project, card, checkitem)
        if not params:
            return None
        project, card, checkitem = params

        if checkitem.cardified_id or (card.archived_at and not column_uid):
            return False

        target_column = InfraHelper.get_by_id_like(ProjectColumn, column_uid or card.project_column_id)
        if not target_column or target_column.is_archive:
            return False

        if checkitem.status != CheckitemStatus.Stopped:
            self.change_status(user_or_bot, project, card, checkitem, CheckitemStatus.Stopped)

        new_card = Card(
            project_id=card.project_id,
            project_column_id=target_column.id,
            title=checkitem.title,
            order=self.repo.card.get_next_order(target_column, where_clauses={"project_id": card.project_id}),
        )
        self.repo.card.insert(new_card)

        checkitem.cardified_id = new_card.id
        self.repo.checkitem.update(checkitem)

        api_card = new_card.board_api_response(0, [], [], [])
        CheckitemPublisher.cardified(card, checkitem, target_column, api_card)
        CardCheckitemActivityTask.card_checkitem_cardified(user_or_bot, project, card, checkitem)
        CardCheckitemBotTask.card_checkitem_cardified(user_or_bot, project, card, checkitem, new_card)
        CardBotTask.card_created(user_or_bot, project, new_card)

        return True

    def delete(
        self,
        user_or_bot: TUserOrBot,
        project: TProjectParam,
        card: TCardParam,
        checkitem: TCheckitemParam,
    ) -> bool | None:
        params = self.__get_records_by_params(project, card, checkitem)
        if not params:
            return None
        project, card, checkitem = params

        if checkitem.status != CheckitemStatus.Stopped:
            self.change_status(user_or_bot, project, card, checkitem, CheckitemStatus.Stopped)

        self.repo.checkitem.delete(checkitem)

        CheckitemPublisher.deleted(project, card, checkitem)
        CardCheckitemActivityTask.card_checkitem_deleted(user_or_bot, project, card, checkitem)
        CardCheckitemBotTask.card_checkitem_deleted(user_or_bot, project, card, checkitem)

        return True

    def __convert_api_response(self, card: Card, record: tuple[Checkitem, Card | None, User | None]):
        checkitem, cardified_card, user = record

        api_checkitem = checkitem.api_response()
        api_checkitem["card_uid"] = card.get_uid()
        last_timer = self.repo.checkitem_timer_record.get_by_checkitem_and_arc_type(checkitem, "last")
        if last_timer and last_timer.status == CheckitemStatus.Started:
            api_checkitem["timer_started_at"] = last_timer.created_at
        if cardified_card:
            api_checkitem["cardified_card"] = cardified_card.api_response()
        if user:
            api_checkitem["user"] = user.api_response()
        return api_checkitem

    @overload
    def __get_records_by_params(
        self, project: TProjectParam, card: TCardParam
    ) -> tuple[Project, Card, None] | None: ...
    @overload
    def __get_records_by_params(
        self, project: TProjectParam, card: TCardParam, checkitem: TCheckitemParam
    ) -> tuple[Project, Card, Checkitem] | None: ...
    def __get_records_by_params(
        self,
        project: TProjectParam,
        card: TCardParam,
        checkitem: TCheckitemParam | None = None,
    ) -> tuple[Project, Card, Checkitem | None] | None:
        if checkitem:
            checkitem = InfraHelper.get_by_id_like(Checkitem, checkitem)
            if not checkitem:
                return None
            params = InfraHelper.get_records_with_foreign_by_params(
                (Project, project),
                (Card, card),
                (Checklist, checkitem.checklist_id),
                (Checkitem, checkitem),
            )
            if not params:
                return None
            project, card, _, checkitem = params
        else:
            params = InfraHelper.get_records_with_foreign_by_params((Project, project), (Card, card))
            if not params:
                return None
            project, card = params
            checkitem = None

        return project, card, checkitem
