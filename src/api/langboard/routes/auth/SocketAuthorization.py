from collections.abc import Sequence
from langboard_shared.core.routing import (
    GLOBAL_TOPIC_ID,
    NONE_TOPIC_ID,
    EEditorCollaborationType,
    SettingSocketTopicID,
    SocketTopic,
)
from langboard_shared.core.security.CollaborationChannel import CollaborationChannel
from langboard_shared.domain.models import Project, User
from langboard_shared.domain.models.ApiKeyRole import ApiKeyRoleAction
from langboard_shared.domain.models.bases import ALL_GRANTED
from langboard_shared.domain.models.McpRole import McpRoleAction
from langboard_shared.domain.models.ProjectRole import ProjectRoleAction
from langboard_shared.domain.models.SettingRole import SettingRoleAction, SettingRoleCategory
from langboard_shared.domain.services import DomainService
from langboard_shared.domain.services.SocketCardAudience import can_receive_card_event
from langboard_shared.Env import Env
from .forms.Socket import SocketSubscriptionAuthorizationItem


_EDITOR_SETTINGS_TOPICS = {
    "bot": SettingSocketTopicID.Bot,
    "bot-value": SettingSocketTopicID.Bot,
    "global-relationship": SettingSocketTopicID.GlobalRelationship,
    "api-comfort-tool": SettingSocketTopicID.ApiComfortTool,
    "api-key": SettingSocketTopicID.ApiKey,
    "internal-bot": SettingSocketTopicID.InternalBot,
    "internal-bot-value": SettingSocketTopicID.InternalBot,
    "mcp-tool-group": SettingSocketTopicID.McpToolGroup,
    "notification-schedule-rule": SettingSocketTopicID.NotificationSchedule,
    "user": SettingSocketTopicID.User,
    "webhook": SettingSocketTopicID.Webhook,
}

_EDITOR_SETTINGS_WRITE_ACTIONS = {
    SettingSocketTopicID.User: SettingRoleAction.UserUpdate,
    SettingSocketTopicID.Bot: SettingRoleAction.BotUpdate,
    SettingSocketTopicID.InternalBot: SettingRoleAction.InternalBotUpdate,
    SettingSocketTopicID.GlobalRelationship: SettingRoleAction.GlobalRelationshipUpdate,
    SettingSocketTopicID.Webhook: SettingRoleAction.WebhookUpdate,
    SettingSocketTopicID.NotificationSchedule: SettingRoleAction.NotificationScheduleUpdate,
    SettingSocketTopicID.ApiComfortTool: SettingRoleAction.ApiComfortToolUpdate,
}


def authorized_subscription_items(
    service: DomainService,
    user: User,
    subscriptions: Sequence[SocketSubscriptionAuthorizationItem],
) -> list[dict[str, str]]:
    """Batch the common board/card admission path; preserve per-topic policy."""
    board_topics = {SocketTopic.Board, SocketTopic.BoardWiki, SocketTopic.Dashboard}
    board_uids = [item.topic_id for item in subscriptions if item.topic in board_topics]
    card_uids = [item.topic_id for item in subscriptions if item.topic == SocketTopic.BoardCard]
    cards = (
        service.card.get_readable_card_project_uids(card_uids, user, CollaborationChannel.HumanUI) if card_uids else {}
    )
    board_uids.extend(cards.values())
    assigned = service.project.get_assigned_project_uids(user, board_uids) if board_uids else set()
    readable_cards = {card_uid for card_uid, project_uid in cards.items() if user.is_admin or project_uid in assigned}
    authorized = []
    for item in subscriptions:
        if item.topic in board_topics:
            allowed = item.topic_id in assigned
        elif item.topic == SocketTopic.BoardCard:
            allowed = item.topic_id in readable_cards
        else:
            allowed = is_subscription_authorized(service, user, item.topic, item.topic_id)
        if allowed:
            authorized.append({"topic": item.topic.value, "topic_id": item.topic_id})
    return authorized


def _has_project_action(
    service: DomainService,
    user: User,
    project: Project,
    action: ProjectRoleAction,
) -> bool:
    actions = service.project.get_user_role_actions_by_project(user, project)
    return ALL_GRANTED in actions or action.value in actions


def _is_app_settings_subscription_authorized(
    service: DomainService,
    user: User,
    topic_id: str,
) -> bool:
    if user.email in Env.FULL_ADMIN_ACCESS_EMAILS:
        return True

    try:
        setting_topic_id = SettingSocketTopicID(topic_id)
    except ValueError:
        return False

    if setting_topic_id == SettingSocketTopicID.ApiKey:
        role = service.api_key.get_role(user)
        return bool(role and role.actions)

    if setting_topic_id == SettingSocketTopicID.McpToolGroup:
        role = service.mcp_tool_group.get_role(user)
        return bool(role and role.actions)

    if not user.is_admin:
        return False

    role = service.user.get_setting_role(user)
    if not role:
        return False

    try:
        category = SettingRoleCategory(setting_topic_id.value)
    except ValueError:
        return False
    return role.has_category_permission(category)


def is_subscription_authorized(
    service: DomainService,
    user: User,
    topic: SocketTopic,
    topic_id: str,
) -> bool:
    if topic == SocketTopic.Global:
        return topic_id == GLOBAL_TOPIC_ID
    if topic == SocketTopic.NoneTopic:
        return topic_id == NONE_TOPIC_ID
    if topic == SocketTopic.UserPrivate:
        return topic_id == user.get_uid()
    if topic == SocketTopic.AppSettings:
        return _is_app_settings_subscription_authorized(service, user, topic_id)
    if topic == SocketTopic.OllamaManager:
        if not user.is_admin or topic_id != GLOBAL_TOPIC_ID:
            return False
        if user.email in Env.FULL_ADMIN_ACCESS_EMAILS:
            return True
        role = service.user.get_setting_role(user)
        return bool(role and role.is_granted(SettingRoleAction.OllamaRead))
    if topic == SocketTopic.User:
        target = service.user.get_by_id_like(topic_id)
        if not target or target.id == user.id:
            return False
        return user.is_admin or service.project.are_users_related(user, target)

    if topic == SocketTopic.BoardCard:
        if not can_receive_card_event(service, user, topic_id):
            return False
        card = service.card.get_by_id_like(topic_id)
        if not card:
            return False
        project = service.project.get_by_id_like(card.project_id)
        if not project:
            return False
        if user.is_admin:
            return True
        return service.project.is_assigned(user, project)[0]

    if topic == SocketTopic.BoardWikiPrivate:
        wiki = service.project_wiki.get_by_id_like(topic_id)
        if not wiki:
            return False
        project = service.project.get_by_id_like(wiki.project_id)
        if not project:
            return False
        if user.is_admin:
            return True
        if not service.project.is_assigned(user, project)[0]:
            return False
        return service.project_wiki.is_assigned(user, wiki) or _has_project_action(
            service, user, project, ProjectRoleAction.Update
        )

    project = service.project.get_by_id_like(topic_id)
    if not project:
        return False
    if topic in {SocketTopic.Board, SocketTopic.BoardWiki, SocketTopic.Dashboard}:
        return service.project.is_assigned(user, project)[0]
    if topic == SocketTopic.BoardSettings:
        return user.is_admin or (
            service.project.is_assigned(user, project)[0]
            and _has_project_action(service, user, project, ProjectRoleAction.Update)
        )
    return False


def editor_document_subscription(document_name: str) -> tuple[SocketTopic, str] | None:
    parts = document_name.split(":")
    if len(parts) not in {2, 3} or any(not part for part in parts):
        return None

    try:
        document_type = EEditorCollaborationType(parts[0])
    except ValueError:
        return None

    entity_uid = parts[1]
    section = parts[2] if len(parts) == 3 else None

    if document_type == EEditorCollaborationType.AppSettings:
        setting_topic = _EDITOR_SETTINGS_TOPICS.get(section or "")
        return (SocketTopic.AppSettings, setting_topic.value) if setting_topic else None
    if document_type == EEditorCollaborationType.Card:
        return SocketTopic.BoardCard, entity_uid
    if document_type == EEditorCollaborationType.BoardColumnName:
        return SocketTopic.Board, entity_uid
    if document_type in {EEditorCollaborationType.BoardSettings, EEditorCollaborationType.BotSchedule}:
        return SocketTopic.BoardSettings, entity_uid
    if document_type == EEditorCollaborationType.Wiki:
        return SocketTopic.BoardWikiPrivate, entity_uid
    return None


def authorized_editor_document_subscription(
    service: DomainService, user: User, document_name: str
) -> tuple[SocketTopic, str] | None:
    subscription = editor_document_subscription(document_name)
    if subscription and is_subscription_authorized(service, user, *subscription):
        return subscription
    return None


_CARD_COMMENT_SECTION_PREFIX = "comment-"


def is_card_comment_author(service: DomainService, user: User, document_name: str | None) -> bool:
    """Return whether the document names a card comment the user may mutate (REST can_mutate parity)."""

    if not document_name:
        return False
    parts = document_name.split(":")
    if len(parts) != 3 or parts[0] != EEditorCollaborationType.Card.value:
        return False
    section = parts[2]
    if not section.startswith(_CARD_COMMENT_SECTION_PREFIX):
        return False
    comment_uid = section[len(_CARD_COMMENT_SECTION_PREFIX) :]
    if not comment_uid:
        return False
    comment = service.card_comment.get_by_id_like(comment_uid)
    return bool(comment and service.card_comment.can_mutate(user, comment))


def is_editor_document_write_authorized(
    service: DomainService,
    user: User,
    subscription: tuple[SocketTopic, str],
    document_name: str | None = None,
) -> bool:
    topic, topic_id = subscription

    if topic == SocketTopic.BoardCard:
        if not can_receive_card_event(service, user, topic_id):
            return False
        card = service.card.get_by_id_like(topic_id)
        if not card:
            return False
        project = service.project.get_by_id_like(card.project_id)
        if not project:
            return False
        if user.is_admin:
            return True
        if is_card_comment_author(service, user, document_name):
            return True
        return bool(
            service.project.is_assigned(user, project)[0]
            and _has_project_action(service, user, project, ProjectRoleAction.CardUpdate)
        )

    if topic == SocketTopic.Board:
        project = service.project.get_by_id_like(topic_id)
        return bool(
            project
            and (
                user.is_admin
                or (
                    service.project.is_assigned(user, project)[0]
                    and _has_project_action(service, user, project, ProjectRoleAction.Update)
                )
            )
        )

    if topic in {SocketTopic.BoardSettings, SocketTopic.BoardWikiPrivate}:
        return True

    if topic != SocketTopic.AppSettings:
        return False

    if user.email in Env.FULL_ADMIN_ACCESS_EMAILS:
        return True

    try:
        setting_topic_id = SettingSocketTopicID(topic_id)
    except ValueError:
        return False

    if setting_topic_id == SettingSocketTopicID.ApiKey:
        role = service.api_key.get_role(user)
        return bool(role and role.is_granted(ApiKeyRoleAction.Update))

    if setting_topic_id == SettingSocketTopicID.McpToolGroup:
        role = service.mcp_tool_group.get_role(user)
        return bool(role and role.is_granted(McpRoleAction.Update))

    if not user.is_admin:
        return False

    action = _EDITOR_SETTINGS_WRITE_ACTIONS.get(setting_topic_id)
    role = service.user.get_setting_role(user)
    return bool(action and role and role.is_granted(action))
