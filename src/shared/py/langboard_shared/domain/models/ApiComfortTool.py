import re
from hashlib import sha1
from typing import Any, ClassVar, NotRequired, TypedDict
from sqlalchemy import JSON, TEXT
from ...core.db import ApiField, BaseDbModel, CSVType, Field


class ApiComfortToolMap(TypedDict):
    label: str
    description: str
    api_names: list[str]
    query: NotRequired[dict[str, Any]]
    form: NotRequired[dict[str, Any]]
    api_queries: NotRequired[dict[str, dict[str, Any]]]
    api_forms: NotRequired[dict[str, dict[str, Any]]]


class ApiComfortTool(BaseDbModel, table=True):
    DEFAULT_TOOLS: ClassVar[dict[str, ApiComfortToolMap]] = {
        "card_lookup": {
            "label": "Card lookup",
            "description": (
                "Look up a card in one call. This includes the card body, assigned labels, checklists and "
                "checkitems, attachments, relationships, comments, and the latest 10 card activities."
            ),
            "api_names": ["get_card_details", "get_card_comments", "get_card_activities"],
            "api_queries": {"get_card_activities": {"limit": 10}},
        },
        "assign_card_label": {
            "label": "Assign card label",
            "description": (
                "Get the available project labels, then update the card labels. Use the label list to choose "
                "valid label UIDs before applying the change."
            ),
            "api_names": ["get_project_labels", "update_card_labels"],
        },
        "add_card_checklist": {
            "label": "Add card checklist",
            "description": (
                "Get the current card checklists, then create a new checklist on the card. Use the existing "
                "checklist list to avoid duplicates and choose a sensible position."
            ),
            "api_names": ["get_card_checklists", "create_checklist"],
        },
        "move_card_column": {
            "label": "Move card column",
            "description": (
                "Get the project columns, then move the card to the requested column or reorder it inside the "
                "current column."
            ),
            "api_names": ["get_project_columns", "change_card_order_or_move_column"],
        },
        "mention_project_member": {
            "label": "Mention project member",
            "description": (
                "Get project members and global bots, then add a card comment with the correct mention target."
            ),
            "api_names": ["get_project_assigned_users", "get_bots", "add_card_comment"],
        },
        "add_card_relationship": {
            "label": "Add card relationship",
            "description": (
                "Get the source card relationship metadata and available project cards, then update the card "
                "relationships using a valid relationship type and target card."
            ),
            "api_names": ["get_card_details", "get_project_cards", "update_card_relationships"],
        },
        "task_orchestration": {
            "label": "Task orchestration",
            "description": (
                "Create orchestration task cards, record agent runs, verification results, failure feedback, "
                "suggestions, and bypass decisions using existing card metadata and relationships. Record a run "
                "when agent work starts or finishes. Record failed verification with failure details so LangBoard "
                "can add card feedback and update task metadata. Use bypass only for low-risk changes; high-risk "
                "work must be treated as approval-required."
            ),
            "api_names": [
                "get_project",
                "get_project_columns",
                "get_project_cards",
                "get_card_details",
                "create_orchestration_task",
                "record_orchestration_run",
                "record_orchestration_verification",
                "record_orchestration_suggestions",
                "create_orchestration_suggestion_task",
                "record_orchestration_bypass",
            ],
        },
    }

    name: str = Field(nullable=False, unique=True, index=True, api_field=ApiField())
    label: str = Field(nullable=False, api_field=ApiField())
    description: str = Field(default="", nullable=False, sa_type=TEXT, api_field=ApiField())
    api_names: list[str] = Field(default_factory=list, nullable=False, sa_type=CSVType(str), api_field=ApiField())
    query: dict[str, Any] = Field(default_factory=dict, nullable=False, sa_type=JSON, api_field=ApiField())
    form: dict[str, Any] = Field(default_factory=dict, nullable=False, sa_type=JSON, api_field=ApiField())
    api_queries: dict[str, dict[str, Any]] = Field(
        default_factory=dict, nullable=False, sa_type=JSON, api_field=ApiField()
    )
    api_forms: dict[str, dict[str, Any]] = Field(
        default_factory=dict, nullable=False, sa_type=JSON, api_field=ApiField()
    )
    is_default: bool = Field(default=False, nullable=False, api_field=ApiField())

    @staticmethod
    def normalize_name(name: str, label: str = "") -> str:
        raw_value = (name or label).strip()
        value = raw_value.lower()
        value = re.sub(r"[^a-z0-9_-]+", "_", value)
        value = re.sub(r"_+", "_", value).strip("_")
        if not value and raw_value:
            value = f"comfort_tool_{sha1(raw_value.encode('utf-8')).hexdigest()[:10]}"
        return value

    @staticmethod
    def is_valid_name(name: str) -> bool:
        return bool(re.fullmatch(r"[A-Za-z0-9_-]+", name))

    @classmethod
    def create_default_api_response(cls, name: str, comfort_tool: ApiComfortToolMap) -> dict[str, Any]:
        return {
            "uid": name,
            "created_at": "1970-01-01T00:00:00+00:00",
            "updated_at": "1970-01-01T00:00:00+00:00",
            "name": name,
            "label": comfort_tool["label"],
            "description": comfort_tool["description"],
            "api_names": comfort_tool["api_names"],
            "query": comfort_tool.get("query", {}),
            "form": comfort_tool.get("form", {}),
            "api_queries": comfort_tool.get("api_queries", {}),
            "api_forms": comfort_tool.get("api_forms", {}),
            "is_default": True,
        }

    def to_api_comfort_tool_map(self) -> ApiComfortToolMap:
        comfort_tool_map: ApiComfortToolMap = {
            "label": self.label,
            "description": self.description,
            "api_names": self.api_names,
        }
        if self.query:
            comfort_tool_map["query"] = self.query
        if self.form:
            comfort_tool_map["form"] = self.form
        if self.api_queries:
            comfort_tool_map["api_queries"] = self.api_queries
        if self.api_forms:
            comfort_tool_map["api_forms"] = self.api_forms
        return comfort_tool_map

    def notification_data(self) -> dict[str, Any]:
        return {}

    def _get_repr_keys(self) -> list[str | tuple[str, str]]:
        return ["name", "label"]
