from typing import Any, Literal
from pydantic import BaseModel, Field, model_validator


GRAPH_PAYLOAD_MAX_DEPTH = 12
GRAPH_PAYLOAD_MAX_ITEMS = 5000
GRAPH_PAYLOAD_MAX_STRING_CHARACTERS = 500_000
GRAPH_PAYLOAD_MAX_SINGLE_STRING_CHARACTERS = 100_000


def validate_graph_payload(value: Any) -> None:
    item_count = 0
    string_characters = 0
    stack: list[tuple[Any, int]] = [(value, 0)]

    while stack:
        item, depth = stack.pop()
        if depth > GRAPH_PAYLOAD_MAX_DEPTH:
            raise ValueError(f"Graph payload nesting exceeds {GRAPH_PAYLOAD_MAX_DEPTH} levels")
        item_count += 1
        if item_count > GRAPH_PAYLOAD_MAX_ITEMS:
            raise ValueError(f"Graph payload exceeds {GRAPH_PAYLOAD_MAX_ITEMS} items")

        if isinstance(item, str):
            if len(item) > GRAPH_PAYLOAD_MAX_SINGLE_STRING_CHARACTERS:
                raise ValueError("Graph payload contains an oversized string")
            string_characters += len(item)
            if string_characters > GRAPH_PAYLOAD_MAX_STRING_CHARACTERS:
                raise ValueError("Graph payload contains too much text")
        elif isinstance(item, dict):
            for key, child in item.items():
                stack.append((key, depth + 1))
                stack.append((child, depth + 1))
        elif isinstance(item, (list, tuple)):
            stack.extend((child, depth + 1) for child in item)


class GraphRequestModel(BaseModel):
    input_value: str | None = Field(default=None, max_length=30_000, description="The input value")
    input_type: str | None = Field(default="chat", max_length=100, description="The input type")
    output_type: str | None = Field(default="chat", max_length=100, description="The output type")
    output_component: str | None = Field(default="", max_length=200, description="Reserved for response compatibility")
    tweaks: dict[str, Any] | None = Field(default=None, description="Graph runtime context")
    session_id: str = Field(..., max_length=512, description="The session id")
    thread_id: str | None = Field(default=None, max_length=512, description="Stable graph checkpoint thread id")
    run_type: Literal["internal_bot", "bot"] = Field(..., description="The runner type")
    uid: str = Field(..., max_length=64)
    project_uid: str | None = Field(default=None, max_length=64, description="The project uid")
    log_uid: str | None = Field(default=None, max_length=64, description="The bot log uid")
    scope_log_table: str | None = Field(default=None, max_length=100, description="The scope bot log table")

    @model_validator(mode="after")
    def validate_tweaks_size(self) -> "GraphRequestModel":
        validate_graph_payload(self.tweaks)
        return self
