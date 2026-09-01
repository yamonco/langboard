from datetime import datetime, timezone
from json import dumps as json_dumps
from typing import Any, Literal, TypedDict
from langboard_shared.core.db import DbSession, SqlBuilder
from langboard_shared.core.logger import Logger
from langboard_shared.core.types import SafeDateTime
from langboard_shared.domain.models import Bot, CardComment, ChatHistory, ProjectActivity, User
from langboard_shared.helpers import InfraHelper
from .state import DefaultGraphState


GraphHistoryMessageType = Literal["chat", "comment", "card_action", "summary", "system_notice"]
GraphHistorySource = Literal["chat_history", "card_comment", "project_activity", "system"]
GraphHistoryChangeType = Literal["new", "edited", "deleted"]

_DEFAULT_HISTORY_SOURCE_LIMIT = 20
_DEFAULT_HISTORY_MESSAGE_LIMIT = 40
_DEFAULT_HISTORY_MESSAGE_MAX_CHARS = 600
_DEFAULT_HISTORY_PROMPT_MAX_CHARS = 6000
_DEFAULT_HISTORY_SUMMARY_MAX_CHARS = 1200
_MAX_HISTORY_SOURCE_LIMIT = 100
_MAX_HISTORY_MESSAGE_LIMIT = 200
_MAX_HISTORY_MESSAGE_MAX_CHARS = 4000
_MAX_HISTORY_PROMPT_MAX_CHARS = 30000
_MAX_HISTORY_SUMMARY_MAX_CHARS = 5000


class GraphHistoryMessage(TypedDict, total=False):
    msg_id: str
    msg_type: GraphHistoryMessageType
    source: GraphHistorySource
    change_type: GraphHistoryChangeType
    sender: dict[str, Any] | None
    content: str | dict[str, Any] | None
    timestamp: str
    updated_at: str | None
    parent_id: str | None
    action_type: str | None
    scope: dict[str, str | None]
    lineage: dict[str, Any]


def create_langboard_history_context_prompt(tweaks: dict[str, Any], state: DefaultGraphState) -> str:
    config = _get_history_config(tweaks)
    if not config["enabled"]:
        state["history_messages"] = []
        state["history_delta"] = None
        state["history_summary"] = None
        state["history_context_prompt"] = ""
        return ""

    try:
        messages = collect_langboard_history_messages(tweaks, config)
    except Exception as exc:
        Logger.main.exception(exc)
        messages = []

    if not messages:
        state["history_messages"] = []
        state["history_delta"] = None
        state["history_summary"] = None
        state["history_context_prompt"] = ""
        return ""

    messages = _sort_messages(messages)
    delivery, window_messages, delta = _create_history_window(messages, state.get("last_history_sync_at"))
    prompt_messages, summary = _apply_context_window(window_messages, delivery, config)
    state["history_messages"] = prompt_messages
    state["history_delta"] = delta
    state["history_summary"] = summary
    state["last_history_sync_at"] = _get_latest_timestamp(messages) or state.get("last_history_sync_at")

    if not prompt_messages:
        state["history_context_prompt"] = ""
        return ""

    prompt = _create_history_prompt(prompt_messages, config, delivery)
    state["history_context_prompt"] = prompt
    return prompt


def collect_langboard_history_messages(tweaks: dict[str, Any], config: dict[str, Any]) -> list[GraphHistoryMessage]:
    variables = _get_variables(tweaks)
    rest_data = _get_rest_data(variables)
    source_limit = int(config["source_limit"])
    messages: list[GraphHistoryMessage] = []

    messages.extend(collect_chat_history_messages(variables, rest_data, source_limit))
    messages.extend(collect_card_comment_messages(rest_data, source_limit))
    messages.extend(collect_project_activity_messages(variables, rest_data, source_limit))
    return messages


def collect_chat_history_messages(
    variables: dict[str, Any], rest_data: dict[str, Any], limit: int
) -> list[GraphHistoryMessage]:
    chat_session_uid = _first_string(
        rest_data.get("chat_session_uid"),
        variables.get("chat_session_uid"),
    )
    chat_history_uid = _first_string(
        rest_data.get("chat_history_uid"),
        variables.get("chat_history_uid"),
    )
    if not chat_session_uid and not chat_history_uid:
        return []

    try:
        query = SqlBuilder.select.table(ChatHistory, with_deleted=True)
        if chat_session_uid:
            query = query.where(ChatHistory.column("chat_session_id") == InfraHelper.convert_id(chat_session_uid))
        if chat_history_uid:
            query = query.where(ChatHistory.column("id") != InfraHelper.convert_id(chat_history_uid))
        query = query.order_by(ChatHistory.column("created_at").desc(), ChatHistory.column("id").desc()).limit(limit)

        with DbSession.use(readonly=True) as db:
            records = db.exec(query).all()
    except Exception as exc:
        Logger.main.exception(exc)
        return []

    return [normalize_chat_history(history) for history in records if _has_chat_history_content(history)]


def collect_card_comment_messages(rest_data: dict[str, Any], limit: int) -> list[GraphHistoryMessage]:
    card_uid = _first_string(rest_data.get("card_uid"))
    if not card_uid:
        return []

    try:
        query = (
            SqlBuilder.select.tables(CardComment, User, Bot, with_deleted=True)
            .outerjoin(User, CardComment.column("user_id") == User.column("id"))
            .outerjoin(Bot, CardComment.column("bot_id") == Bot.column("id"))
            .where(CardComment.column("card_id") == InfraHelper.convert_id(card_uid))
            .order_by(CardComment.column("created_at").desc(), CardComment.column("id").desc())
            .limit(limit)
        )

        with DbSession.use(readonly=True) as db:
            records = db.exec(query).all()
    except Exception as exc:
        Logger.main.exception(exc)
        return []

    messages: list[GraphHistoryMessage] = []
    for comment, user, bot in records:
        messages.append(
            normalize_card_comment(
                comment, user if isinstance(user, User) else None, bot if isinstance(bot, Bot) else None
            )
        )
    return messages


def collect_project_activity_messages(
    variables: dict[str, Any], rest_data: dict[str, Any], limit: int
) -> list[GraphHistoryMessage]:
    project_uid = _first_string(rest_data.get("project_uid"), variables.get("project_uid"))
    card_uid = _first_string(rest_data.get("card_uid"))
    column_uid = _first_string(rest_data.get("project_column_uid"))
    if not project_uid and not card_uid and not column_uid:
        return []

    try:
        query = SqlBuilder.select.table(ProjectActivity)
        if card_uid:
            query = query.where(ProjectActivity.column("card_id") == InfraHelper.convert_id(card_uid))
        elif column_uid:
            query = query.where(ProjectActivity.column("project_column_id") == InfraHelper.convert_id(column_uid))
        elif project_uid:
            query = query.where(ProjectActivity.column("project_id") == InfraHelper.convert_id(project_uid))
        query = query.order_by(ProjectActivity.column("created_at").desc(), ProjectActivity.column("id").desc()).limit(
            limit
        )

        with DbSession.use(readonly=True) as db:
            records = db.exec(query).all()
    except Exception as exc:
        Logger.main.exception(exc)
        return []

    return [normalize_project_activity(activity) for activity in records]


def normalize_chat_history(history: ChatHistory) -> GraphHistoryMessage:
    return {
        "msg_id": f"chat_history:{history.get_uid()}",
        "msg_type": "chat",
        "source": "chat_history",
        "change_type": _get_mutable_change_type(
            history.created_at, history.updated_at, getattr(history, "deleted_at", None)
        ),
        "sender": {"type": "agent" if history.is_received else "user"},
        "content": _trim_text(history.message.content),
        "timestamp": _to_iso(history.created_at) or "",
        "updated_at": _to_iso(history.updated_at),
        "parent_id": None,
        "scope": {"chat_session": "current"},
        "lineage": {"source": "chat_history"},
    }


def normalize_card_comment(
    comment: CardComment, user: User | None = None, bot: Bot | None = None
) -> GraphHistoryMessage:
    return {
        "msg_id": f"card_comment:{comment.get_uid()}",
        "msg_type": "comment",
        "source": "card_comment",
        "change_type": _get_mutable_change_type(comment.created_at, comment.updated_at, comment.deleted_at),
        "sender": _create_sender(user, bot),
        "content": _trim_text(comment.content.content),
        "timestamp": _to_iso(comment.created_at) or "",
        "updated_at": _to_iso(comment.updated_at),
        "parent_id": "current_card",
        "scope": {"card": "current"},
        "lineage": {"source": "card_comment"},
    }


def normalize_project_activity(activity: ProjectActivity) -> GraphHistoryMessage:
    action_type = getattr(activity.activity_type, "value", activity.activity_type)
    return {
        "msg_id": f"project_activity:{activity.get_uid()}",
        "msg_type": "card_action",
        "source": "project_activity",
        "change_type": "new",
        "sender": _create_activity_sender(activity),
        "content": _create_activity_content(activity),
        "timestamp": _to_iso(activity.created_at) or "",
        "updated_at": _to_iso(activity.updated_at),
        "parent_id": "current_card" if activity.card_id else None,
        "action_type": str(action_type or ""),
        "scope": {
            "project": "current",
            "project_column": "current" if activity.project_column_id else None,
            "card": "current" if activity.card_id else None,
        },
        "lineage": {"source": "project_activity"},
    }


def _get_history_config(tweaks: dict[str, Any]) -> dict[str, Any]:
    graph_config = tweaks.get("Graph")
    graph_config = graph_config if isinstance(graph_config, dict) else {}
    return {
        "enabled": graph_config.get("history_context_enabled", True) is not False,
        "source_limit": _get_bounded_positive_int(
            graph_config.get("history_source_limit"), _DEFAULT_HISTORY_SOURCE_LIMIT, _MAX_HISTORY_SOURCE_LIMIT
        ),
        "message_limit": _get_bounded_positive_int(
            graph_config.get("history_message_limit"), _DEFAULT_HISTORY_MESSAGE_LIMIT, _MAX_HISTORY_MESSAGE_LIMIT
        ),
        "message_max_chars": _get_bounded_positive_int(
            graph_config.get("history_message_max_chars"),
            _DEFAULT_HISTORY_MESSAGE_MAX_CHARS,
            _MAX_HISTORY_MESSAGE_MAX_CHARS,
        ),
        "prompt_max_chars": _get_bounded_positive_int(
            graph_config.get("history_prompt_max_chars"),
            _DEFAULT_HISTORY_PROMPT_MAX_CHARS,
            _MAX_HISTORY_PROMPT_MAX_CHARS,
        ),
        "summary_enabled": graph_config.get("history_summary_enabled") is True,
        "summary_max_chars": _get_bounded_positive_int(
            graph_config.get("history_summary_max_chars"),
            _DEFAULT_HISTORY_SUMMARY_MAX_CHARS,
            _MAX_HISTORY_SUMMARY_MAX_CHARS,
        ),
    }


def _create_history_window(
    messages: list[GraphHistoryMessage], last_history_sync_at: str | None
) -> tuple[str, list[GraphHistoryMessage], dict[str, Any]]:
    last_sync = _parse_iso_timestamp(last_history_sync_at)
    if last_sync is None:
        return (
            "full_window",
            messages,
            {
                "type": "full_window",
                "new": messages,
                "edited": [],
                "deleted": [],
            },
        )

    delta = _extract_history_delta(messages, last_sync)
    prompt_messages = _sort_messages(delta["new"] + delta["edited"] + delta["deleted"])
    return (
        "delta",
        prompt_messages,
        {
            "type": "delta",
            "new": delta["new"],
            "edited": delta["edited"],
            "deleted": delta["deleted"],
        },
    )


def _extract_history_delta(
    messages: list[GraphHistoryMessage], last_sync: datetime
) -> dict[GraphHistoryChangeType, list[GraphHistoryMessage]]:
    delta: dict[GraphHistoryChangeType, list[GraphHistoryMessage]] = {
        "new": [],
        "edited": [],
        "deleted": [],
    }
    for message in messages:
        created_at = _parse_iso_timestamp(message.get("timestamp"))
        updated_at = _parse_iso_timestamp(message.get("updated_at")) or created_at
        change_type = message.get("change_type") or "new"
        change_type = change_type if change_type in delta else "new"

        if change_type == "new":
            if created_at and created_at > last_sync:
                delta["new"].append(message)
            continue

        if updated_at and updated_at > last_sync:
            delta[change_type].append(message)
            continue

        if created_at and created_at > last_sync:
            delta["new"].append(message)

    return delta


def _apply_context_window(
    messages: list[GraphHistoryMessage], delivery: str, config: dict[str, Any]
) -> tuple[list[GraphHistoryMessage], GraphHistoryMessage | None]:
    message_limit = int(config["message_limit"])
    if len(messages) <= message_limit:
        return messages, None

    if not config["summary_enabled"] or message_limit < 2:
        return messages[-message_limit:], None

    older_messages = messages[: -(message_limit - 1)]
    recent_messages = messages[-(message_limit - 1) :]
    summary = _create_summary_message(older_messages, delivery, int(config["summary_max_chars"]))
    return [summary, *recent_messages], summary


def _create_summary_message(messages: list[GraphHistoryMessage], delivery: str, max_chars: int) -> GraphHistoryMessage:
    first_timestamp = messages[0].get("timestamp") if messages else None
    latest_timestamp = _get_latest_timestamp(messages)
    by_type: dict[str, int] = {}
    by_change: dict[str, int] = {}

    for message in messages:
        msg_type = str(message.get("msg_type") or "system_notice")
        change_type = str(message.get("change_type") or "new")
        by_type[msg_type] = by_type.get(msg_type, 0) + 1
        by_change[change_type] = by_change.get(change_type, 0) + 1

    content = {
        "summary": _trim_text(
            "Older history messages were compacted into this deterministic summary.",
            max_chars,
        ),
        "message_count": len(messages),
        "by_type": by_type,
        "by_change": by_change,
        "time_range": {
            "from": first_timestamp,
            "to": latest_timestamp,
        },
    }
    return {
        "msg_id": f"history_summary:{delivery}:{first_timestamp or ''}:{latest_timestamp or ''}",
        "msg_type": "summary",
        "source": "system",
        "change_type": "new",
        "sender": {"type": "system"},
        "content": content,
        "timestamp": str(latest_timestamp or ""),
        "updated_at": str(latest_timestamp or ""),
        "parent_id": None,
        "scope": {"history_window": "summary"},
        "lineage": {"source": "history_context", "delivery": delivery},
    }


def _create_history_prompt(messages: list[GraphHistoryMessage], config: dict[str, Any], delivery: str) -> str:
    lines = [
        "Langboard hybrid history context:",
        f"- delivery: {delivery}",
        "- Treat msg_id values as internal context only. Do not expose them to the user.",
        "",
        "Messages:",
    ]
    message_max_chars = int(config["message_max_chars"])

    for index, message in enumerate(messages, 1):
        lines.append(_format_history_message(index, message, message_max_chars))

    prompt = "\n".join(lines).strip()
    max_chars = int(config["prompt_max_chars"])
    if len(prompt) <= max_chars:
        return prompt
    return f"{prompt[: max_chars - 3]}..."


def _format_history_message(index: int, message: GraphHistoryMessage, max_chars: int) -> str:
    msg_type = message.get("msg_type") or "system_notice"
    change_type = message.get("change_type") or "new"
    timestamp = message.get("timestamp") or ""
    sender = _format_sender(message.get("sender"))
    action_type = message.get("action_type")
    content = _format_content(message.get("content"))
    content = _trim_text(content, max_chars)

    action = f":{action_type}" if action_type else ""
    sender_part = f" by {sender}" if sender else ""
    time_part = f" at {timestamp}" if timestamp else ""
    return f"{index}. [{msg_type}{action}:{change_type}]{sender_part}{time_part} - {content}"


def _format_content(content: str | dict[str, Any] | None) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    return json_dumps(_redact_internal_keys(content), ensure_ascii=False, default=str)


def _create_activity_content(activity: ProjectActivity) -> dict[str, Any]:
    action_type = getattr(activity.activity_type, "value", activity.activity_type)
    history = activity.convert_activity_history()
    return {
        "action": str(action_type or ""),
        "history": _compact_activity_history(str(action_type or ""), history),
    }


def _create_activity_sender(activity: ProjectActivity) -> dict[str, Any] | None:
    if activity.user_id:
        return {"type": "user"}
    if activity.bot_id:
        return {"type": "bot"}
    return None


def _create_sender(user: User | None = None, bot: Bot | None = None) -> dict[str, Any] | None:
    if user:
        if user.deleted_at:
            return {"type": "unknown_user"}
        return {"type": "user", "name": user.get_fullname()}
    if bot:
        return {"type": "bot", "name": bot.name}
    return None


def _format_sender(sender: dict[str, Any] | None) -> str:
    if not sender:
        return ""
    name = sender.get("name")
    sender_type = sender.get("type")
    if isinstance(name, str) and name:
        return name
    return str(sender_type or "")


def _get_mutable_change_type(
    created_at: SafeDateTime, updated_at: SafeDateTime, deleted_at: SafeDateTime | None
) -> GraphHistoryChangeType:
    if deleted_at:
        return "deleted"
    if created_at.timestamp() != updated_at.timestamp():
        return "edited"
    return "new"


def _sort_messages(messages: list[GraphHistoryMessage]) -> list[GraphHistoryMessage]:
    return sorted(messages, key=lambda message: (message.get("timestamp") or "", message.get("msg_id") or ""))


def _get_latest_timestamp(messages: list[GraphHistoryMessage]) -> str | None:
    timestamps = [message.get("updated_at") or message.get("timestamp") for message in messages]
    timestamps = [timestamp for timestamp in timestamps if isinstance(timestamp, str) and timestamp]
    return max(timestamps) if timestamps else None


def _parse_iso_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _get_variables(tweaks: dict[str, Any]) -> dict[str, Any]:
    variables = tweaks.get("LangboardCalledVariablesComponent")
    return variables if isinstance(variables, dict) else {}


def _get_rest_data(variables: dict[str, Any]) -> dict[str, Any]:
    rest_data = variables.get("rest_data")
    return rest_data if isinstance(rest_data, dict) else {}


def _first_string(*values: Any) -> str:
    for value in values:
        if isinstance(value, str) and value:
            return value
    return ""


def _to_iso(value: SafeDateTime | None) -> str | None:
    return value.isoformat() if value else None


def _trim_text(value: str, max_chars: int = _DEFAULT_HISTORY_MESSAGE_MAX_CHARS) -> str:
    value = " ".join(str(value or "").split())
    if len(value) <= max_chars:
        return value
    return f"{value[: max_chars - 3]}..."


def _has_chat_history_content(history: ChatHistory) -> bool:
    return bool(_trim_text(history.message.content))


def _get_bounded_positive_int(value: Any, default: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return min(parsed, maximum) if parsed > 0 else default


def _redact_internal_keys(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _redact_internal_keys(item)
            for key, item in value.items()
            if key not in {"id", "uid"} and not key.endswith("_id") and not key.endswith("_uid")
        }
    if isinstance(value, list):
        return [_redact_internal_keys(item) for item in value]
    return value


def _compact_activity_history(action_type: str, history: dict[str, Any]) -> dict[str, Any]:
    compact = _redact_internal_keys(history)
    if action_type.startswith("card_comment_"):
        comment = compact.get("comment") if isinstance(compact, dict) else None
        if isinstance(comment, dict):
            comment.pop("content", None)
    return compact
