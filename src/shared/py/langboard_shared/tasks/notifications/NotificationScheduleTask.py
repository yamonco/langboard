from collections.abc import Iterator
from datetime import datetime, timedelta
from typing import Any, NotRequired, TypedDict
from sqlalchemy import func
from ...core.db import DbSession, SqlBuilder
from ...core.types import SafeDateTime
from ...domain.models import (
    Card,
    Checkitem,
    Checklist,
    NotificationScheduleRule,
    Project,
    ProjectColumn,
    User,
    UserNotification,
)
from ...domain.models.BaseNotificationScheduleModel import BaseNotificationScheduleModel
from ...domain.models.UserNotification import NotificationType
from ...domain.services import DomainService
from ...helpers import InfraHelper, ModelHelper
from ...infrastructure.repositories import Repository


DEFAULT_NOTIFICATION_REPEAT_AFTER_HOURS = 24
NOTIFICATION_CANDIDATE_BATCH_SIZE = 500
SCHEDULED_RULE_NOTIFICATION_TYPE = NotificationType.ScheduledRule
TARGET_MODELS: dict[str, type[BaseNotificationScheduleModel]] = {
    str(model.__tablename__): model for model in ModelHelper.get_models_by_base_class(BaseNotificationScheduleModel)
}


class ScheduledRuleCandidate(TypedDict):
    project: Project
    target_model: BaseNotificationScheduleModel
    card: NotRequired[Card]
    checkitem: NotRequired[Checkitem]


async def run_scheduled_notifications(interval_str: str):
    with DbSession.use(readonly=False) as lock_db:
        lock_acquired = lock_db.exec(
            SqlBuilder.select.column(
                func.pg_try_advisory_xact_lock(func.hashtextextended(f"notification:{interval_str}", 0))
            )
        ).first()
        if not lock_acquired:
            return

        rules = _get_due_notification_rules(interval_str)
        if not rules:
            return

        ran_rule_uids = _run_notification_rules(rules)
        if not ran_rule_uids:
            return

        with DbSession.use(readonly=False) as db:
            for rule in rules:
                if rule.get_uid() not in ran_rule_uids:
                    continue
                rule.last_run_at = SafeDateTime.now()
                db.update(rule)


def _get_due_notification_rules(interval_str: str) -> list[NotificationScheduleRule]:
    with Repository.use() as repository:
        return [
            rule for rule in repository.notification_schedule_rule.get_enabled() if rule.interval_str == interval_str
        ]


def _run_notification_rules(notification_rules: list[NotificationScheduleRule]) -> set[str]:
    rules = [rule.api_response() for rule in notification_rules]
    if not rules:
        return set()

    with DomainService.use() as service:
        return _run_notification_rules_with_service(rules, service)


def _run_notification_rules_with_service(rules: list[dict[str, Any]], service: DomainService) -> set[str]:
    with Repository.use() as repository:
        return _run_notification_rules_with_resources(rules, service, repository)


def _run_notification_rules_with_resources(
    rules: list[dict[str, Any]], service: DomainService, repository: Repository
) -> set[str]:
    now = SafeDateTime.now()
    notification_service = service.notification
    sent_keys: set[tuple[str, int, int, str]] = set()

    ran_rule_uids: set[str] = set()
    for rule in rules:
        rule_uid = _get_rule_uid(rule)
        notification_type = _get_rule_notification_type(rule)
        repeat_after_hours = _get_int_option(rule, "repeat_after_hours", DEFAULT_NOTIFICATION_REPEAT_AFTER_HOURS, 1)
        recent_keys = _get_recent_scheduled_rule_notification_keys(
            rule_uid,
            notification_type,
            now - timedelta(hours=repeat_after_hours),
        )

        for candidate in _get_scheduled_rule_candidates(rule, now):
            notifier = InfraHelper.get_by_id_like(User, candidate["project"].owner_id)
            if not notifier:
                continue

            target_table_name = type(candidate["target_model"]).__tablename__
            target_record_id = int(candidate["target_model"].id)
            for target_user in _resolve_rule_recipients(rule, candidate, repository):
                key = (rule_uid, int(target_user.id), target_record_id, target_table_name)
                if key in recent_keys or key in sent_keys:
                    continue

                message_vars = {
                    "rule_uid": rule_uid,
                    "target": rule.get("target"),
                    "field": rule.get("field"),
                    "operator": rule.get("operator"),
                    "value": rule.get("value"),
                    "target_table": target_table_name,
                    "target_id": target_record_id,
                }

                if not notification_service.notify_notification_schedule_rule(
                    notifier,
                    target_user,
                    notification_type,
                    candidate["project"],
                    str(rule.get("name") or rule_uid),
                    candidate["target_model"],
                    message_vars,
                    now,
                ):
                    continue
                sent_keys.add(key)
                ran_rule_uids.add(rule_uid)

    return ran_rule_uids


def _get_rule_uid(rule: dict[str, Any]) -> str:
    return str(
        rule.get("uid") or rule.get("name") or f"{rule.get('target')}.{rule.get('field')}.{rule.get('operator')}"
    )


def _get_rule_notification_type(rule: dict[str, Any]) -> NotificationType:
    target_model = TARGET_MODELS.get(str(rule.get("target") or ""))
    if target_model:
        notification_type = target_model.get_notification_schedule_rule_notification_type(
            rule.get("field"),
            rule.get("operator"),
        )
        if isinstance(notification_type, NotificationType):
            return notification_type

    return SCHEDULED_RULE_NOTIFICATION_TYPE


def _get_scheduled_rule_candidates(rule: dict[str, Any], now: SafeDateTime) -> Iterator[ScheduledRuleCandidate]:
    target = rule.get("target")
    if target == Project.__tablename__:
        rows = _get_project_rule_candidates()
    elif target == Card.__tablename__:
        rows = _get_card_rule_candidates()
    elif target == Checkitem.__tablename__:
        rows = _get_checkitem_rule_candidates()
    else:
        return

    for candidate in rows:
        if _does_rule_match(rule, candidate["target_model"], now):
            yield candidate


def _get_project_rule_candidates() -> Iterator[ScheduledRuleCandidate]:
    last_id = 0
    while True:
        with DbSession.use(readonly=True) as db:
            projects = db.exec(
                SqlBuilder.select.table(Project)
                .where(Project.column("id") > last_id)
                .order_by(Project.column("id").asc())
                .limit(NOTIFICATION_CANDIDATE_BATCH_SIZE)
            ).all()
        if not projects:
            return
        for project in projects:
            yield ScheduledRuleCandidate(project=project, target_model=project)
        last_id = int(projects[-1].id)


def _get_card_rule_candidates() -> Iterator[ScheduledRuleCandidate]:
    last_id = 0
    while True:
        with DbSession.use(readonly=True) as db:
            rows = db.exec(
                SqlBuilder.select.tables(Card, Project)
                .join(ProjectColumn, ProjectColumn.column("id") == Card.column("project_column_id"))
                .join(Project, Project.column("id") == Card.column("project_id"))
                .where(ProjectColumn.column("deleted_at") == None)  # noqa
                .where(Card.column("id") > last_id)
                .order_by(Card.column("id").asc())
                .limit(NOTIFICATION_CANDIDATE_BATCH_SIZE)
            ).all()
        if not rows:
            return
        for card, project in rows:
            yield ScheduledRuleCandidate(project=project, target_model=card, card=card)
        last_id = int(rows[-1][0].id)


def _get_checkitem_rule_candidates() -> Iterator[ScheduledRuleCandidate]:
    last_id = 0
    while True:
        with DbSession.use(readonly=True) as db:
            rows = db.exec(
                SqlBuilder.select.tables(Checkitem, Checklist, Card, Project)
                .join(Checklist, Checklist.column("id") == Checkitem.column("checklist_id"))
                .join(Card, Card.column("id") == Checklist.column("card_id"))
                .join(Project, Project.column("id") == Card.column("project_id"))
                .where(Checkitem.column("id") > last_id)
                .order_by(Checkitem.column("id").asc())
                .limit(NOTIFICATION_CANDIDATE_BATCH_SIZE)
            ).all()
        if not rows:
            return
        for checkitem, _, card, project in rows:
            yield ScheduledRuleCandidate(
                project=project,
                target_model=checkitem,
                card=card,
                checkitem=checkitem,
            )
        last_id = int(rows[-1][0].id)


def _does_rule_match(rule: dict[str, Any], target_model: BaseNotificationScheduleModel, now: SafeDateTime) -> bool:
    field = rule.get("field")
    operator = rule.get("operator")
    if not isinstance(field, str) or not isinstance(operator, str) or not hasattr(target_model, field):
        return False

    field_value = getattr(target_model, field)
    if hasattr(field_value, "value"):
        field_value = field_value.value

    if operator == BaseNotificationScheduleModel.OPERATOR_WITHIN_NEXT_DAYS:
        if not isinstance(field_value, datetime):
            return False
        value = _get_int_option(rule, "value", 0, 0)
        if field_value < now:
            return False
        return field_value <= now + timedelta(days=value)

    if operator == BaseNotificationScheduleModel.OPERATOR_OVERDUE:
        return isinstance(field_value, datetime) and field_value < now

    if operator == BaseNotificationScheduleModel.OPERATOR_OLDER_THAN_DAYS:
        return isinstance(field_value, datetime) and field_value <= now - timedelta(
            days=_get_int_option(rule, "value", 0, 0)
        )

    if operator == BaseNotificationScheduleModel.OPERATOR_GREATER_THAN_SECONDS:
        return isinstance(field_value, int) and field_value >= _get_int_option(rule, "value", 0, 0)

    if operator == BaseNotificationScheduleModel.OPERATOR_EQUALS:
        return field_value == rule.get("value")

    if operator == BaseNotificationScheduleModel.OPERATOR_IS_EMPTY:
        return field_value is None

    if operator == BaseNotificationScheduleModel.OPERATOR_IS_NOT_EMPTY:
        return field_value is not None

    return False


def _resolve_rule_recipients(
    rule: dict[str, Any], candidate: ScheduledRuleCandidate, repository: Repository
) -> list[User]:
    recipient_keys = rule.get("recipients")
    if not isinstance(recipient_keys, list):
        recipient_keys = [BaseNotificationScheduleModel.RECIPIENT_PROJECT_OWNER]

    users: list[User] = []
    for recipient_key in recipient_keys:
        if recipient_key == BaseNotificationScheduleModel.RECIPIENT_PROJECT_OWNER:
            owner = InfraHelper.get_by_id_like(User, candidate["project"].owner_id)
            if owner:
                users.append(owner)
        elif recipient_key == BaseNotificationScheduleModel.RECIPIENT_PROJECT_MEMBERS:
            for user, _ in repository.project_assigned_user.get_all_by_project(candidate["project"]):
                users.append(user)
        elif recipient_key == BaseNotificationScheduleModel.RECIPIENT_CARD_ASSIGNEES:
            card = candidate.get("card")
            if card:
                for user, _ in repository.card_assigned_user.get_all_by_card(card):
                    users.append(user)
        elif recipient_key == BaseNotificationScheduleModel.RECIPIENT_CHECKITEM_USER:
            checkitem = candidate.get("checkitem")
            if checkitem and checkitem.user_id:
                user = InfraHelper.get_by_id_like(User, checkitem.user_id)
                if user:
                    users.append(user)

    deduped_users: list[User] = []
    seen_user_ids: set[int] = set()
    for user in users:
        if int(user.id) in seen_user_ids:
            continue
        deduped_users.append(user)
        seen_user_ids.add(int(user.id))

    return deduped_users


def _get_recent_scheduled_rule_notification_keys(
    rule_uid: str,
    notification_type: NotificationType,
    created_after: SafeDateTime,
) -> set[tuple[str, int, int, str]]:
    condition = (
        (UserNotification.column("notification_type") == notification_type)
        & (UserNotification.column("created_at") >= created_after)
        & (UserNotification.column("message_vars")["rule_uid"].as_string() == rule_uid)
    )

    with DbSession.use(readonly=True) as db:
        notifications = db.exec(SqlBuilder.select.table(UserNotification).where(condition)).all()

    keys: set[tuple[str, int, int, str]] = set()
    for notification in notifications:
        if notification.message_vars.get("rule_uid") != rule_uid:
            continue

        target_id = notification.message_vars.get("target_id")
        target_table = notification.message_vars.get("target_table")
        if isinstance(target_id, str) and target_id.isdigit():
            target_id = int(target_id)
        if not isinstance(target_id, int) or not isinstance(target_table, str):
            continue
        keys.add((rule_uid, int(notification.receiver_id), target_id, target_table))

    return keys


def _get_int_option(options: dict[str, Any], key: str, default: int, min_value: int) -> int:
    try:
        return max(int(options.get(key, default)), min_value)
    except (TypeError, ValueError):
        return default
