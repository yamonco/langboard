from datetime import timedelta
from typing import Any, Literal, Sequence, cast, overload
from sqlalchemy.exc import IntegrityError
from ....ai import BotScheduleHelper, BotScopeHelper
from ....core.db import EditorContentModel
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
from ...models import (
    Bot,
    Card,
    CardAssignedProjectLabel,
    CardAssignedUser,
    CardBotSchedule,
    CardBotScope,
    Checkitem,
    Project,
    ProjectColumn,
    ProjectWiki,
    User,
)
from ...models.Checkitem import CheckitemStatus
from .CardRelationshipService import CardRelationshipService
from .CheckitemService import CheckitemService
from .GraphApprovalRequestService import GraphApprovalRequestService
from .NotificationService import NotificationService
from .ProjectLabelService import ProjectLabelService
from .ProjectService import ProjectService
from .ProjectWikiService import ProjectWikiService


class CardService(BaseDomainService):
    CONTEXT_DESCRIPTION_MAX_LENGTH = 1200
    LINKED_RESOURCE_PREVIEW_MAX_LENGTH = 240

    @staticmethod
    def name() -> str:
        """DO NOT EDIT THIS METHOD"""
        return "card"

    def get_by_id_like(self, card: TCardParam | None) -> Card | None:
        card = InfraHelper.get_by_id_like(Card, card)
        return card

    def get_by_project(self, project: TProjectParam | None) -> list[Card]:
        project = InfraHelper.get_by_id_like(Project, project)
        if not project:
            return []

        return [card for card, _ in self.repo.card.get_all_by_project(project)]

    def get_details(
        self,
        project: TProjectParam | None,
        card: TCardParam | None,
        user_or_bot: TUserOrBot | None = None,
    ) -> dict[str, Any] | None:
        params = InfraHelper.get_records_with_foreign_by_params((Project, project), (Card, card))
        if not params:
            return None
        project, card = params

        column = InfraHelper.get_by_id_like(ProjectColumn, card.project_column_id)
        if not column:
            return None

        api_card = card.api_response()
        api_card["project_column_name"] = column.name
        if card.is_linked_resource:
            api_card.update(
                {
                    "count_comment": 0,
                    "project_members": [],
                    "labels": [],
                    "member_uids": [],
                    "relationships": [],
                    "linked_resource": self._get_linked_resource_payloads(
                        user_or_bot,
                        project,
                        [card],
                        include_content=True,
                    )[card.get_uid()],
                }
            )
            return api_card

        api_card["count_comment"] = self.repo.card_comment.count_by_card(card)

        project_service = self._get_service(ProjectService)
        api_card["project_members"] = project_service.get_api_assigned_user_list(card.project_id)

        project_label_service = self._get_service(ProjectLabelService)
        api_card["labels"] = project_label_service.get_api_list_by_card(card)

        api_card["member_uids"] = self.get_api_assigned_user_list(card, only_uids=True)

        card_relationship_service = self._get_service(CardRelationshipService)
        api_card["relationships"] = card_relationship_service.get_api_list_by_card(card)
        return api_card

    def get_board_list(
        self,
        project: TProjectParam | None,
        user_or_bot: TUserOrBot | None = None,
    ) -> list[dict[str, Any]]:
        project = InfraHelper.get_by_id_like(Project, project)
        if not project:
            return []

        archive_visible_since = SafeDateTime.now() - timedelta(days=project.archive_visible_days)
        raw_cards = self.repo.card.get_board_list(project, archive_visible_since)
        raw_members = self.repo.card_assigned_user.get_all_by_project(project, archive_visible_since)
        members: dict[int, list[str]] = {}
        for user, card_assigned_user in raw_members:
            if card_assigned_user.card_id not in members:
                members[card_assigned_user.card_id] = []
            members[card_assigned_user.card_id].append(user.get_uid())

        raw_relationships = self.repo.card_relationship.get_all_by_project(project, archive_visible_since)
        relationships: dict[int, list[dict[str, Any]]] = {}
        for relationship, _ in raw_relationships:
            if relationship.card_id_parent not in relationships:
                relationships[relationship.card_id_parent] = []
            if relationship.card_id_child not in relationships:
                relationships[relationship.card_id_child] = []
            relationships[relationship.card_id_parent].append(relationship.api_response())
            relationships[relationship.card_id_child].append(relationship.api_response())

        raw_labels = self.repo.project_label.get_all_card_labels_by_project(project, archive_visible_since)
        labels: dict[int, list[dict[str, Any]]] = {}
        for label, card_label in raw_labels:
            if card_label.card_id not in labels:
                labels[card_label.card_id] = []
            labels[card_label.card_id].append(label.api_response())

        cards = []
        resource_payloads = self._get_linked_resource_payloads(
            user_or_bot,
            project,
            [card for card, _ in raw_cards if card.is_linked_resource],
            include_content=False,
        )
        for card, count_comment in raw_cards:
            api_card = card.board_api_response(
                count_comment=count_comment,
                member_uids=members.get(card.id, []),
                relationships=relationships.get(card.id, []),
                labels=labels.get(card.id, []),
            )
            if card.is_linked_resource:
                api_card["linked_resource"] = resource_payloads[card.get_uid()]
            cards.append(api_card)

        return cards

    def _get_linked_resource_payloads(
        self,
        user_or_bot: TUserOrBot | None,
        project: Project,
        cards: Sequence[Card],
        *,
        include_content: bool,
    ) -> dict[str, dict[str, Any]]:
        payloads: dict[str, dict[str, Any]] = {
            card.get_uid(): {
                "type": card.source_type,
                "uid": card.source_uid,
                "status": "missing",
            }
            for card in cards
            if card.source_type is not None and card.source_uid is not None
        }
        wiki_cards = [
            card
            for card in cards
            if card.source_type == Card.LINKED_RESOURCE_PROJECT_WIKI and card.source_uid is not None
        ]
        wiki_uids = {cast(str, card.source_uid) for card in wiki_cards}
        if include_content:
            wikis = self.repo.project_wiki.get_by_project_and_uids(project, wiki_uids)
            wiki_map: dict[str, Any] = {wiki.get_uid(): wiki for wiki in wikis}
            private_wiki_ids = {int(wiki.id) for wiki in wikis if not wiki.is_public}
        else:
            headers = self.repo.project_wiki.get_headers_by_project_and_uids(project, wiki_uids)
            wiki_map = {
                wiki_id.to_short_code(): {"id": wiki_id, "title": title, "is_public": is_public}
                for wiki_id, title, is_public in headers
            }
            private_wiki_ids = {int(wiki_id) for wiki_id, _, is_public in headers if not is_public}

        assigned_wiki_ids: set[int] = set()
        can_view_all = isinstance(user_or_bot, Bot) or (
            isinstance(user_or_bot, User) and (user_or_bot.is_admin or project.owner_id == user_or_bot.id)
        )
        if isinstance(user_or_bot, User) and not can_view_all:
            assigned_wiki_ids = self.repo.project_wiki_assigned_user.get_assigned_wiki_ids(
                user_or_bot,
                private_wiki_ids,
            )

        for card in wiki_cards:
            source_uid = cast(str, card.source_uid)
            wiki = wiki_map.get(source_uid)
            payload: dict[str, Any] = {
                "type": Card.LINKED_RESOURCE_PROJECT_WIKI,
                "uid": source_uid,
                "status": "missing",
            }
            if wiki is not None:
                wiki_id = wiki.id if include_content else wiki["id"]
                is_public = wiki.is_public if include_content else wiki["is_public"]
                title = wiki.title if include_content else wiki["title"]
                can_view = is_public or can_view_all or int(wiki_id) in assigned_wiki_ids
                if can_view:
                    payload.update(
                        {
                            "status": "available",
                            "title": title,
                        }
                    )
                    if include_content:
                        content = wiki.content.content if wiki.content else ""
                        payload["preview"] = content[: self.LINKED_RESOURCE_PREVIEW_MAX_LENGTH]
                        payload["content"] = convert_python_data(wiki.content)
                else:
                    payload["status"] = "forbidden"
            payloads[card.get_uid()] = payload

        return payloads

    def create_linked_wiki_card(
        self,
        user_or_bot: TUserOrBot,
        project: TProjectParam | None,
        wiki: TWikiParam | None,
        column: TColumnParam | None = None,
    ) -> tuple[Card, dict[str, Any], bool] | None:
        params = InfraHelper.get_records_with_foreign_by_params((Project, project), (ProjectWiki, wiki))
        if not params:
            return None
        project, wiki = params
        if wiki.project_id != project.id:
            return None
        if column is None:
            column = next(
                (
                    candidate
                    for candidate, _ in self.repo.project_column.get_all_by_project(project)
                    if not candidate.is_archive
                ),
                None,
            )
        else:
            column = InfraHelper.get_by_id_like(ProjectColumn, column)
        if column is None or column.project_id != project.id or column.is_archive:
            return None
        if isinstance(user_or_bot, User):
            can_view = (
                user_or_bot.is_admin
                or project.owner_id == user_or_bot.id
                or self._get_service(ProjectWikiService).is_assigned(user_or_bot, wiki)
            )
            if not can_view:
                return None

        source_uid = wiki.get_uid()
        existing = self.repo.card.find_linked_resource(project, Card.LINKED_RESOURCE_PROJECT_WIKI, source_uid)
        if existing is not None:
            payload = existing.board_api_response(0, [], [], [])
            payload["linked_resource"] = self._get_linked_resource_payloads(
                user_or_bot, project, [existing], include_content=False
            )[existing.get_uid()]
            return existing, payload, False

        card = Card(
            created_by_user_id=user_or_bot.id if isinstance(user_or_bot, User) else None,
            created_by_bot_id=user_or_bot.id if isinstance(user_or_bot, Bot) else None,
            project_id=project.id,
            project_column_id=column.id,
            title="",
            description=EditorContentModel(),
            order=self.repo.card.get_next_order(column, {"project_id": project.id}),
            source_type=Card.LINKED_RESOURCE_PROJECT_WIKI,
            source_uid=source_uid,
        )
        try:
            self.repo.card.insert(card)
        except IntegrityError:
            existing = self.repo.card.find_linked_resource(project, Card.LINKED_RESOURCE_PROJECT_WIKI, source_uid)
            if existing is None:
                raise
            payload = existing.board_api_response(0, [], [], [])
            payload["linked_resource"] = self._get_linked_resource_payloads(
                user_or_bot, project, [existing], include_content=False
            )[existing.get_uid()]
            return existing, payload, False

        payload = card.board_api_response(0, [], [], [])
        payload["linked_resource"] = self._get_linked_resource_payloads(
            user_or_bot, project, [card], include_content=False
        )[card.get_uid()]
        CardPublisher.created(project, column, {"card": payload})
        return card, payload, True
    def get_api_archived_page_by_project(
        self,
        project: TProjectParam | None,
        limit: int,
        before_archived_at: SafeDateTime | None = None,
        before_card: TCardParam | None = None,
        input_value: str | None = None,
    ) -> tuple[list[dict[str, Any]], int, tuple[str, str] | None] | None:
        """Return an archive-only page kept separate from the board hot path."""

        project = InfraHelper.get_by_id_like(Project, project)
        if not project:
            return None
        records = self.repo.card.get_archived_page_by_project(
            project,
            limit,
            before_archived_at,
            before_card,
            input_value,
        )
        has_more = len(records) > limit
        page = records[:limit]
        cards: list[dict[str, Any]] = []
        for card, column in page:
            api_card = card.api_response()
            api_card["project_column_name"] = column.name
            cards.append(api_card)
        next_fields = None
        if has_more and page:
            last_card = page[-1][0]
            next_fields = (last_card.archived_at.isoformat(), last_card.get_uid())
        return cards, self.repo.card.count_archived_by_project(project, input_value), next_fields

    def get_dashboard_list(
        self, user: User, pagination: TimeBasedPagination
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        records = self.repo.card.get_dashboard_list_scroller(user, pagination)

        api_cards = []
        api_projects: dict[int, dict[str, Any]] = {}
        for card, project, column in records:
            api_card = card.api_response()
            api_card["project_column_name"] = column.name
            if project.id not in api_projects:
                api_projects[project.id] = project.api_response()
            api_cards.append(api_card)
        return api_cards, list(api_projects.values())

    def get_api_list_by_project(
        self,
        project: TProjectParam | None,
        user_or_bot: TUserOrBot | None = None,
    ) -> list[dict[str, Any]]:
        project = InfraHelper.get_by_id_like(Project, project)
        if not project:
            return []

        records = self.repo.card.get_all_by_project(project)
        resource_payloads = self._get_linked_resource_payloads(
            user_or_bot,
            project,
            [card for card, _ in records if card.is_linked_resource],
            include_content=False,
        )
        cards = []
        for card, column in records:
            api_card = card.api_response()
            api_card["project_column_name"] = column.name
            if card.is_linked_resource:
                api_card["linked_resource"] = resource_payloads[card.get_uid()]
            cards.append(api_card)
        return cards

    def search_context_by_project(self, project: TProjectParam | None, input_value: str) -> list[dict[str, Any]]:
        project = InfraHelper.get_by_id_like(Project, project)
        if not project:
            return []

        cards = []
        for card, column in self.repo.card.search_context_by_project(project, input_value):
            description = card.description.content
            if len(description) > self.CONTEXT_DESCRIPTION_MAX_LENGTH:
                description = f"{description[: self.CONTEXT_DESCRIPTION_MAX_LENGTH - 3]}..."
            cards.append(
                {
                    "uid": card.get_uid(),
                    "title": card.title,
                    "description": {"content": description},
                    "project_column_name": column.name,
                }
            )
        return cards

    def get_api_page_by_project(
        self,
        project: TProjectParam | None,
        limit: int,
        before_updated_at: SafeDateTime | None = None,
        before_card: TCardParam | None = None,
    ) -> tuple[list[dict[str, Any]], int, tuple[str, str] | None] | None:
        """Return a bounded newest-updated-first card page and opaque cursor fields."""

        project = InfraHelper.get_by_id_like(Project, project)
        if not project:
            return None
        records = self.repo.card.get_page_by_project(project, limit, before_updated_at, before_card)
        has_more = len(records) > limit
        page = records[:limit]
        cards: list[dict[str, Any]] = []
        for card, column in page:
            api_card = card.api_response()
            api_card["project_column_name"] = column.name
            cards.append(api_card)
        next_fields = None
        if has_more and page:
            last_card = page[-1][0]
            next_fields = (last_card.updated_at.isoformat(), last_card.get_uid())
        return cards, self.repo.card.count_by_project(project), next_fields

    def get_api_list_by_column(self, column: TColumnParam | None) -> list[dict[str, Any]]:
        column = InfraHelper.get_by_id_like(ProjectColumn, column)
        if not column:
            return []

        records = self.repo.card.get_all_by_column(column)
        return [card.api_response() for card in records]

    @overload
    def get_api_assigned_user_list(
        self,
        card: TCardParam | None,
        only_uids: Literal[False] = False,
        limit: int | None = None,
    ) -> list[dict[str, Any]]: ...
    @overload
    def get_api_assigned_user_list(
        self,
        card: TCardParam | None,
        only_uids: Literal[True],
        limit: int | None = None,
    ) -> list[str]: ...
    def get_api_assigned_user_list(
        self,
        card: TCardParam | None,
        only_uids: bool = False,
        limit: int | None = None,
    ) -> list[dict[str, Any]] | list[str]:
        """Return assigned users, optionally enforcing a repository row limit."""

        card = InfraHelper.get_by_id_like(Card, card)
        if not card:
            return []

        raw_users = self.repo.card_assigned_user.get_all_by_card(card, only_ids=only_uids, limit=limit)
        if only_uids:
            users = [cast(SnowflakeID, user).to_short_code() for user, _ in raw_users]
        else:
            users = [cast(User, user).api_response() for user, _ in raw_users]
        return users

    def get_api_bot_scope_list(
        self,
        project: TProjectParam | None,
        card: TCardParam | None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """Return card bot scopes, optionally enforcing a database row limit."""

        params = InfraHelper.get_records_with_foreign_by_params((Project, project), (Card, card))
        if not params:
            return []
        project, card = params

        scopes = BotScopeHelper.get_list(CardBotScope, limit=limit, card_id=card.id)
        return [scope.api_response() for scope in scopes]

    def get_api_bot_schedule_list(
        self,
        project: TProjectParam | None,
        card: TCardParam | None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """Return card bot schedules, optionally enforcing a database row limit."""

        params = InfraHelper.get_records_with_foreign_by_params((Project, project), (Card, card))
        if not params:
            return []
        project, card = params

        pagination = TimeBasedPagination(page=1, limit=limit) if limit is not None else None
        schedules = BotScheduleHelper.get_all_by_scope(CardBotSchedule, None, card, as_api=True, pagination=pagination)

        return schedules

    def create(
        self,
        user_or_bot: TUserOrBot,
        project: TProjectParam | None,
        column: TColumnParam | None,
        title: str,
        description: EditorContentModel | None = None,
        assign_user_uids: list[str] | None = None,
    ) -> tuple[Card, dict[str, Any]] | None:
        params = InfraHelper.get_records_with_foreign_by_params((Project, project), (ProjectColumn, column))
        if not params:
            return None
        project, column = params
        if column.is_archive:
            return None

        card = Card(
            created_by_user_id=user_or_bot.id if isinstance(user_or_bot, User) else None,
            created_by_bot_id=user_or_bot.id if isinstance(user_or_bot, Bot) else None,
            project_id=project.id,
            project_column_id=column.id,
            title=title,
            description=description or EditorContentModel(),
            order=self.repo.card.get_next_order(column, {"project_id": project.id}),
        )
        self.repo.card.insert(card)

        users: list[User] = []
        if assign_user_uids:
            raw_users = self.repo.project_assigned_user.get_all_by_project(project, where_users_in=assign_user_uids)
            for assign_user, project_assigned_user in raw_users:
                card_assigned_user = CardAssignedUser(
                    project_assigned_id=project_assigned_user.id,
                    card_id=card.id,
                    user_id=assign_user.id,
                )
                users.append(assign_user)
                self.repo.card_assigned_user.insert(card_assigned_user)

        api_card = card.board_api_response(0, [user.get_uid() for user in users], [], [])
        model = {"card": api_card}

        CardPublisher.created(project, column, model)
        CardActivityTask.card_created(user_or_bot, project, card)
        CardBotTask.card_created(user_or_bot, project, card)

        notification_service = self._get_service(NotificationService)
        for user in users:
            notification_service.notify_assigned_to_card(user_or_bot, user, project, card)

        return card, api_card

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

        if expected_description is None:
            self.repo.card.update(card)
        elif not self.repo.card.update_description_if_current(card, expected_description):
            raise CardDescriptionConflict("Card description changed after review: concurrent update")

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

        old_column = None
        old_column = InfraHelper.get_by_id_like(ProjectColumn, card.project_column_id)
        if not old_column or old_column.project_id != project.id:
            return None

        if new_column:
            new_column = InfraHelper.get_by_id_like(ProjectColumn, new_column)
            if not new_column or new_column.project_id != card.project_id:
                return None

            # A linked resource has no archived board-side state. Dropping it on
            # the archive column unlinks the card while preserving its Wiki.
            if card.is_linked_resource and new_column.is_archive:
                if not self.can_delete(user_or_bot, card):
                    raise CardDeleteForbidden("Only the original card author or an administrator can delete this card")
                return self._delete_card(user_or_bot, project, card)

            card.project_column_id = new_column.id

            if new_column.is_archive:
                card.archived_at = SafeDateTime.now()
            else:
                card.archived_at = None

        old_order = card.order
        card.order = order
        self.repo.card.update_row_order(card, old_column, old_order, order, new_column)
        self.repo.card.update(card)

        CardPublisher.order_changed(project, card, old_column, cast(ProjectColumn, new_column))

        if new_column and not card.is_linked_resource:
            CardBotTask.enqueue_card_moved_webhook(
                user_or_bot, project, card, old_column, cast(ProjectColumn, new_column)
            )
            CardActivityTask.card_moved(user_or_bot, project, card, old_column)
            CardBotTask.card_moved(user_or_bot, project, card, old_column, False)

        return True

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

        CardPublisher.labels_updated(project, card, new_labels)
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
        if not is_linked_resource:
            CardActivityTask.card_deleted(user_or_bot, project, card)
            CardBotTask.card_deleted(user_or_bot, project, card)

        return True

    @staticmethod
    def can_delete(user_or_bot: TUserOrBot, card: Card) -> bool:
        """Allow administrators or the immutable creator; unknown legacy authors otherwise fail closed."""

        if isinstance(user_or_bot, User):
            return user_or_bot.is_admin or (
                card.created_by_user_id is not None and card.created_by_user_id == user_or_bot.id
            )
        return card.created_by_bot_id is not None and card.created_by_bot_id == user_or_bot.id
