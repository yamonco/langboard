from datetime import timezone
from typing import Any, cast, overload
from ....core.db import DbSession, SqlBuilder
from ....core.domain import BaseDomainService
from ....core.schema import TimeBasedPagination
from ....core.types import SafeDateTime
from ....core.types.ParamTypes import TCardParam, TCheckitemParam, TChecklistParam, TProjectParam, TUserOrBot
from ....helpers import InfraHelper
from ....publishers import CheckitemPublisher
from ....tasks.activities import CardCheckitemActivityTask
from ....tasks.bots import CardBotTask, CardCheckitemBotTask
from ....tasks.webhooks.ExecutionReadinessUow import execution_readiness_uow
from ...models import Card, Checkitem, CheckitemTimerRecord, Checklist, Project, ProjectColumn, User
from ...models.Checkitem import CheckitemStatus


class CheckitemService(BaseDomainService):
    @staticmethod
    def name() -> str:
        """DO NOT EDIT THIS METHOD"""
        return "checkitem"

    def _mark_card_changed_for_unread(self, card, target_type: str, target_id=None) -> None:
        """Stamp the unread cursor for this card change (lazy import avoids cycles)."""
        from .CardService import CardService

        card_service = self._get_service(CardService)
        card_service.mark_card_changed(card, target_type, target_id)

    def get_by_id_like(self, checkitem: TCheckitemParam | None) -> Checkitem | None:
        checkitem = InfraHelper.get_by_id_like(Checkitem, checkitem)
        return checkitem

    def get_api_list_by_checklist(
        self,
        card: TCardParam,
        checklist: TChecklistParam,
        limit: int | None = None,
        *,
        open_only: bool = False,
        max_checkitems: int | None = None,
        include_work_tracking: bool = True,
    ) -> list[dict[str, Any]]:
        """Return checkitems, optionally enforcing a repository row limit."""

        self._validate_source_limit(limit, max_checkitems)
        params = InfraHelper.get_records_with_foreign_by_params((Card, card), (Checklist, checklist))
        if not params:
            return []
        card, checklist = params

        open_filter = {"open_only": True} if open_only else {}
        records = self.repo.checkitem.get_all_by_checklist(
            checklist, limit=limit, **open_filter, **({"include_user": False} if not include_work_tracking else {})
        )
        self._check_source_bound(records, max_checkitems)

        timer_arcs = (
            self.repo.checkitem_timer_record.get_arc_map_by_checkitems([record[0] for record in records])
            if include_work_tracking
            else {}
        )
        checkitems = [self.__convert_api_response(card, record, timer_arcs) for record in records]
        return checkitems

    def get_api_map_by_card(self, card: TCardParam | None) -> dict[int, list[dict[str, Any]]]:
        card = InfraHelper.get_by_id_like(Card, card)
        if not card:
            return {}

        records = self.repo.checkitem.get_all_by_card(card)

        timer_arcs = self.repo.checkitem_timer_record.get_arc_map_by_checkitems([record[0] for record in records])
        checkitems_map: dict[int, list[dict[str, Any]]] = {}
        for record in records:
            checkitem, _, _ = record
            api_checkitem = self.__convert_api_response(card, record, timer_arcs)
            if checkitem.checklist_id not in checkitems_map:
                checkitems_map[checkitem.checklist_id] = []
            checkitems_map[checkitem.checklist_id].append(api_checkitem)
        return checkitems_map

    def get_api_map_by_checklists(
        self,
        card: Card,
        checklist_ids: list[int],
        limit: int | None,
        *,
        open_only: bool = False,
        max_checkitems: int | None = None,
        include_work_tracking: bool = True,
    ) -> dict[int, list[dict[str, Any]]]:
        """Project bounded checklist rows with one shared timer batch."""
        self._validate_source_limit(limit, max_checkitems)
        records = self.repo.checkitem.get_all_by_checklists(
            card,
            checklist_ids,
            limit,
            open_only=open_only,
            **({"include_user": False} if not include_work_tracking else {}),
        )
        self._check_source_bound(records, max_checkitems)
        timer_arcs = (
            self.repo.checkitem_timer_record.get_arc_map_by_checkitems([record[0] for record in records])
            if include_work_tracking
            else {}
        )
        result: dict[int, list[dict[str, Any]]] = {}
        for record in records:
            result.setdefault(record[0].checklist_id, []).append(self.__convert_api_response(card, record, timer_arcs))
        return result

    @staticmethod
    def _validate_source_limit(limit: int | None, maximum: int | None) -> None:
        if maximum is not None and (maximum < 1 or limit != maximum + 1):
            raise ValueError("Checkitem source bound requires a positive maximum and sentinel query limit")

    @staticmethod
    def _check_source_bound(records: list, maximum: int | None) -> None:
        if maximum is None:
            return
        counts: dict[int, int] = {}
        for checkitem, _, _ in records:
            counts[checkitem.checklist_id] = counts.get(checkitem.checklist_id, 0) + 1
            if counts[checkitem.checklist_id] > maximum:
                raise ValueError(f"checkitems exceeds the safe {maximum}-item MCP source bound")

    def get_active_work(self, user: User) -> list[dict[str, Any]]:
        records = self.repo.checkitem.get_started_work_by_user(user)
        timer_arcs = self.repo.checkitem_timer_record.get_arc_map_by_checkitems([record[0] for record in records])
        active_work: list[dict[str, Any]] = []
        for checkitem, card, project in records:
            api_checkitem = checkitem.api_response()
            api_checkitem["card_uid"] = card.get_uid()
            last_timer = timer_arcs.get(checkitem.id, {}).get("last")
            if last_timer and last_timer.status == CheckitemStatus.Started:
                api_checkitem["timer_started_at"] = last_timer.created_at
            active_work.append(
                {
                    "checkitem": api_checkitem,
                    "card": card.api_response(),
                    "project": project.api_response(),
                }
            )
        return active_work

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
        self,
        user_or_bot: TUserOrBot,
        project: TProjectParam,
        card: TCardParam,
        checklist: TChecklistParam,
        title: str,
        *,
        dispatch_effects: bool = True,
        order_override: int | None = None,
        initially_checked: bool = False,
    ) -> Checkitem | None:
        params = InfraHelper.get_records_with_foreign_by_params(
            (Project, project), (Card, card), (Checklist, checklist)
        )
        if not params:
            return None
        project, card, checklist = params

        checkitem = Checkitem(
            checklist_id=checklist.id,
            title=title,
            is_checked=initially_checked,
            order=order_override if order_override is not None else self.repo.checkitem.get_next_order(checklist),
        )
        self.repo.checkitem.insert(checkitem)

        self._mark_card_changed_for_unread(card, "checkitem", checkitem.id)
        if dispatch_effects:
            self.dispatch_created(user_or_bot, project, card, checklist, checkitem)

        return checkitem

    def dispatch_created(
        self,
        user_or_bot: TUserOrBot,
        project: Project,
        card: Card,
        checklist: Checklist,
        checkitem: Checkitem,
        *,
        include_bot: bool = True,
    ) -> None:
        CheckitemPublisher.created(card, checklist, checkitem)
        CheckitemPublisher.board_progress_changed(project, card)
        CardCheckitemActivityTask.card_checkitem_created(user_or_bot, project, card, checkitem)
        if include_bot:
            CardCheckitemBotTask.card_checkitem_created(user_or_bot, project, card, checkitem)

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

        with DbSession.atomic() as db:
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
            self._mark_card_changed_for_unread(card, "checkitem", checkitem.id)
            # Freeze this operation before another mutation in the same transaction.
            changed_item = checkitem.model_copy(deep=True)
            changed_card = cardified_card.model_copy(deep=True) if cardified_card else None

            def publish():
                CheckitemPublisher.title_changed(project, card, changed_item, changed_card)
                CardCheckitemActivityTask.card_checkitem_title_changed(
                    user_or_bot, project, card, old_title, changed_item
                )
                CardCheckitemBotTask.card_checkitem_title_changed(user_or_bot, project, card, changed_item)

            db.after_commit(publish)

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
        self._mark_card_changed_for_unread(card, "checkitem", checkitem.id)

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

        if checkitem.order == order and (new_checklist is None or new_checklist.id == old_checklist.id):
            return True
        with DbSession.atomic() as db:
            old_order = checkitem.order
            checkitem.order = order
            self.repo.checkitem.update_row_order(checkitem, old_checklist, old_order, order, new_checklist)
            if new_checklist is not None:
                checkitem.checklist_id = new_checklist.id
                self.repo.checkitem.update(checkitem)
            self._mark_card_changed_for_unread(card, "checkitem", checkitem.id)
            changed_item = checkitem.model_copy(deep=True)
            db.after_commit(lambda: CheckitemPublisher.order_changed(card, changed_item, old_checklist, new_checklist))
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
        with DbSession.atomic():
            return self._change_status(
                user_or_bot, project, card, checkitem, status, current_time, should_publish, from_api
            )

    def _change_status(
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
                for started_checkitem, started_card, started_project in self.repo.checkitem.get_started_work_by_user(
                    user_or_bot
                ):
                    if started_checkitem.id == checkitem.id:
                        continue
                    self.change_status(
                        user_or_bot,
                        started_project,
                        started_card,
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
            self._mark_card_changed_for_unread(card, "checkitem", checkitem.id)
        changed_item = checkitem.model_copy(deep=True)

        def publish():
            if should_publish:
                CheckitemPublisher.status_changed(project, card, changed_item, timer_record, target_user)
                CheckitemPublisher.board_progress_changed(project, card)

            if status == CheckitemStatus.Started:
                CardCheckitemActivityTask.card_checkitem_timer_started(user_or_bot, project, card, changed_item)
                CardCheckitemBotTask.card_checkitem_timer_started(user_or_bot, project, card, changed_item)
            elif status == CheckitemStatus.Paused:
                CardCheckitemActivityTask.card_checkitem_timer_paused(user_or_bot, project, card, changed_item)
                CardCheckitemBotTask.card_checkitem_timer_paused(user_or_bot, project, card, changed_item)
            elif status == CheckitemStatus.Stopped:
                CardCheckitemActivityTask.card_checkitem_timer_stopped(user_or_bot, project, card, changed_item)
                CardCheckitemBotTask.card_checkitem_timer_stopped(user_or_bot, project, card, changed_item)

        with DbSession.use(readonly=False) as db:
            db.after_commit(publish)
        return True

    def complete_unchecked_by_card(
        self,
        user_or_bot: TUserOrBot,
        project: Project,
        card: Card,
        publish_summary: bool = True,
        complete: bool = True,
    ) -> dict[str, int]:
        """Apply native entry effects without inverse toggles or per-item tasks."""
        if card.project_id != project.id or card.is_linked_resource or card.deleted_at is not None:
            raise ValueError("Workflow effect card is not active work in this project")
        changed, completed, stopped = [], 0, 0
        now = SafeDateTime.now()
        with DbSession.atomic() as db:
            # The movement boundary already locks the card. Standalone calls use
            # the same lock so two retries cannot duplicate timer facts.
            current = db.exec(
                SqlBuilder.select.table(Card).where(Card.column("id") == card.id).with_for_update()
            ).first()
            if current is None or current.deleted_at is not None or current.project_id != project.id:
                raise ValueError("Workflow effect card is missing")
            items = db.exec(
                SqlBuilder.select.table(Checkitem)
                .join(Checklist, Checkitem.column("checklist_id") == Checklist.column("id"))
                .where(Checklist.column("card_id") == card.id)
                .where(Checklist.column("deleted_at").is_(None))
                .where(Checkitem.column("deleted_at").is_(None))
                .where(Checkitem.column("cardified_id").is_(None))
                .order_by(Checkitem.column("id"))
                .with_for_update(of=Checkitem)
            ).all()
            running = [item for item in items if item.status != CheckitemStatus.Stopped]
            arcs = self.repo.checkitem_timer_record.get_arc_map_by_checkitems(running)
            for item in items:
                item_changed = False
                if complete and not item.is_checked:
                    item.is_checked = True
                    completed += 1
                    item_changed = True
                if item.status != CheckitemStatus.Stopped:
                    last = arcs.get(item.id, {}).get("last")
                    if last is None or last.status != item.status:
                        raise ValueError("Running checkitem has no matching timer fact")
                    if item.status == CheckitemStatus.Started:
                        started_at = (
                            last.created_at if last.created_at.tzinfo else last.created_at.replace(tzinfo=timezone.utc)
                        )
                        item.accumulated_seconds += max(0, int((now - started_at).total_seconds()))
                    item.status = CheckitemStatus.Stopped
                    db.insert(
                        CheckitemTimerRecord(checkitem_id=item.id, status=CheckitemStatus.Stopped, created_at=now)
                    )
                    stopped += 1
                    item_changed = True
                if item_changed:
                    db.update(item)
                    changed.append(
                        {
                            "uid": item.get_uid(),
                            "is_checked": item.is_checked,
                            "status": item.status.value,
                            "accumulated_seconds": item.accumulated_seconds,
                            "timer_started_at": None,
                        }
                    )
            completion_changed = False
            if complete:
                for checklist in db.exec(
                    SqlBuilder.select.table(Checklist)
                    .where(Checklist.column("card_id") == card.id)
                    .where(Checklist.column("deleted_at").is_(None))
                    .where(Checklist.column("is_system") == True)  # noqa: E712
                ).all():
                    if not checklist.is_checked:
                        checklist.is_checked = True
                        db.update(checklist)
                        completion_changed = True
            if (changed or completion_changed) and publish_summary:
                db.after_commit(lambda: CheckitemPublisher.workflow_effects_applied(project, card, changed))
        return {"completed": completed, "stopped": stopped}

    def toggle_checked(
        self,
        user_or_bot: TUserOrBot,
        project: TProjectParam,
        card: TCardParam,
        checkitem: TCheckitemParam,
        desired_checked: bool | None = None,
    ) -> bool | None:
        with DbSession.atomic():
            return self._toggle_checked(user_or_bot, project, card, checkitem, desired_checked)

    def _toggle_checked(
        self,
        user_or_bot: TUserOrBot,
        project: TProjectParam,
        card: TCardParam,
        checkitem: TCheckitemParam,
        desired_checked: bool | None = None,
    ) -> bool | None:
        params = self.__get_records_by_params(project, card, checkitem)
        if not params:
            return None
        project, card, checkitem = params

        if desired_checked is not None and checkitem.is_checked == desired_checked:
            return True
        checkitem.is_checked = desired_checked if desired_checked is not None else not checkitem.is_checked

        if checkitem.status != CheckitemStatus.Stopped:
            if not self.change_status(user_or_bot, project, card, checkitem, CheckitemStatus.Stopped):
                raise ValueError("Work timer transition failed")
            publish_checked = False
        else:
            self.repo.checkitem.update(checkitem)
            self._mark_card_changed_for_unread(card, "checkitem", checkitem.id)
            publish_checked = True

        changed_item = checkitem.model_copy(deep=True)

        def publish():
            if publish_checked:
                CheckitemPublisher.checked_changed(project, card, changed_item)
                CheckitemPublisher.board_progress_changed(project, card)
            if changed_item.is_checked:
                CardCheckitemActivityTask.card_checkitem_checked(user_or_bot, project, card, changed_item)
                CardCheckitemBotTask.card_checkitem_checked(user_or_bot, project, card, changed_item)
            else:
                CardCheckitemActivityTask.card_checkitem_unchecked(user_or_bot, project, card, changed_item)
                CardCheckitemBotTask.card_checkitem_unchecked(user_or_bot, project, card, changed_item)

        with DbSession.use(readonly=False) as db:
            db.after_commit(publish)

        return True

    def cardify(
        self,
        user_or_bot: TUserOrBot,
        project: TProjectParam,
        card: TCardParam,
        checkitem: TCheckitemParam,
        column_uid: str | None = None,
    ) -> bool | None:
        with DbSession.atomic():
            return self._cardify(user_or_bot, project, card, checkitem, column_uid)

    def _cardify(
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
        if not target_column or target_column.is_archive or target_column.project_id != card.project_id:
            return False

        if checkitem.status != CheckitemStatus.Stopped:
            self.change_status(user_or_bot, project, card, checkitem, CheckitemStatus.Stopped)

        new_card = Card(
            project_id=card.project_id,
            project_column_id=target_column.id,
            title=checkitem.title,
            order=self.repo.card.get_next_order(target_column, where_clauses={"project_id": card.project_id}),
        )
        with execution_readiness_uow() as execution:
            self.repo.card.insert(new_card)
            execution.watch_new(new_card.id)

            checkitem.cardified_id = new_card.id
            self.repo.checkitem.update(checkitem)

            card_service = self._get_service_by_name("card")
            card_service.ensure_completion_checklist(new_card)
            api_card = new_card.board_api_response(0, [], [], [], completed=False, is_check_card=True)
            changed_item = checkitem.model_copy(deep=True)
            created_card = new_card.model_copy(deep=True)

            def publish():
                CheckitemPublisher.cardified(card, changed_item, target_column, api_card)
                CardCheckitemActivityTask.card_checkitem_cardified(user_or_bot, project, card, changed_item)
                CardCheckitemBotTask.card_checkitem_cardified(user_or_bot, project, card, changed_item, created_card)
                CardBotTask.card_created(user_or_bot, project, created_card)

            execution.db.after_commit(publish)

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
        CheckitemPublisher.board_progress_changed(project, card)
        self._mark_card_changed_for_unread(card, "checkitem", checkitem.id)
        CardCheckitemActivityTask.card_checkitem_deleted(user_or_bot, project, card, checkitem)
        CardCheckitemBotTask.card_checkitem_deleted(user_or_bot, project, card, checkitem)

        return True

    def __convert_api_response(
        self,
        card: Card,
        record: tuple[Checkitem, Card | None, User | None],
        timer_arcs: dict[int, dict[str, CheckitemTimerRecord]],
    ):
        checkitem, cardified_card, user = record

        api_checkitem = checkitem.api_response()
        api_checkitem["card_uid"] = card.get_uid()
        last_timer = timer_arcs.get(checkitem.id, {}).get("last")
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
