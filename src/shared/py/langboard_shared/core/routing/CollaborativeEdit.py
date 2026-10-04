from enum import Enum
from typing import Any, Callable, Literal, TypedDict, TypeVar


_TRoute = TypeVar("_TRoute", bound=Callable[..., Any])
EDITOR_ROUTE_KEY_HEADER = "X-Editor-Route-Key"


class CollaborativeEditTarget(TypedDict, total=False):
    type: Literal["text", "rich", "block"]
    document_name: str
    form_field: str
    patch_field: str


class EEditorCollaborationType(Enum):
    AppSettings = "app-settings"
    BoardSettings = "board-settings"
    Card = "card"
    BoardColumnName = "board-column-name"
    BotSchedule = "bot-schedule"
    Wiki = "wiki"


def create_editor_collaboration_document_id(
    collaboration_type: EEditorCollaborationType,
    uid: int | str,
    section: int | str | None = None,
) -> str:
    return ":".join(
        str(value) for value in (collaboration_type.value, uid, section) if value is not None and len(str(value)) > 0
    )


def create_editor_document_route_key(document_name: str) -> str:
    value = 0x811C9DC5
    for byte in document_name.encode("utf-8"):
        value = ((value ^ byte) * 0x01000193) & 0xFFFFFFFF
    return f"{value:08x}"


def collaborative_edit(*targets: CollaborativeEditTarget):
    def wrapper(func: _TRoute) -> _TRoute:
        setattr(func, "_collaborative_edit_targets", list(targets))
        return func

    return wrapper


def collaborative_text(document_name: str, form_field: str, patch_field: str) -> CollaborativeEditTarget:
    return {
        "type": "text",
        "document_name": document_name,
        "form_field": form_field,
        "patch_field": patch_field,
    }


def collaborative_rich(document_name: str, form_field: str) -> CollaborativeEditTarget:
    return {
        "type": "rich",
        "document_name": document_name,
        "form_field": form_field,
    }


def collaborative_block(document_name: str) -> CollaborativeEditTarget:
    return {
        "type": "block",
        "document_name": document_name,
    }
