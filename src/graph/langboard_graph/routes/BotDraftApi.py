import asyncio
from json import JSONDecodeError
from json import dumps as json_dumps
from json import loads as json_loads
from re import DOTALL
from re import search as re_search
from typing import Any
from langboard_shared.core.routing import AppRouter, JsonResponse
from langboard_shared.Env import Env
from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from pydantic import BaseModel, Field, model_validator
from ..core.graph.default.chat_model import create_default_chat_model
from ..core.schema.GraphRequestModel import validate_graph_payload


class BotDraftGraphForm(BaseModel):
    instruction: str = Field(min_length=1, max_length=30_000)
    current_value: dict[str, Any] = Field(default_factory=dict)
    suggestions: list[dict[str, Any]] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def validate_nested_values(self) -> "BotDraftGraphForm":
        validate_graph_payload(self.current_value)
        validate_graph_payload(self.suggestions)
        return self


@AppRouter.api.post("/api/v1/graph/bot/draft")
async def create_bot_draft_with_graph(form: BotDraftGraphForm):
    chat_model = create_default_chat_model(str(form.current_value.get("agent_llm") or ""), form.current_value)
    if chat_model is None:
        return JsonResponse(content={"draft": None, "generated": False})

    try:
        result = await asyncio.wait_for(
            chat_model.ainvoke(
                [
                    SystemMessage(content=_create_system_prompt()),
                    HumanMessage(content=_create_user_prompt(form)),
                ]
            ),
            timeout=Env.AI_REQUEST_TIMEOUT,
        )
    except Exception:
        return JsonResponse(content={"draft": None, "generated": False})

    draft = _parse_draft_response(result)
    return JsonResponse(content={"draft": draft, "generated": draft is not None})


def _create_system_prompt() -> str:
    return "\n".join(
        [
            "You create Langboard bot form drafts.",
            "Return only one valid JSON object.",
            "Do not create or save anything.",
            "Use action candidates only to understand intent. Do not put action names in value_patch.",
            "Do not include secrets, api_key, tokens, or credentials.",
            "JSON shape:",
            '{"bot_name":"...","bot_uname":"...","value_patch":{"system_prompt":"..."}}',
        ]
    )


def _create_user_prompt(form: BotDraftGraphForm) -> str:
    return "\n\n".join(
        [
            f"User instruction:\n{form.instruction.strip()}",
            f"Current bot draft value:\n{json_dumps(_create_safe_current_value(form.current_value), ensure_ascii=False)}",
            f"Action candidates:\n{json_dumps(form.suggestions[:8], ensure_ascii=False)}",
        ]
    )


def _create_safe_current_value(value: dict[str, Any]) -> dict[str, Any]:
    allowed_keys = {
        "agent_llm",
        "model",
        "model_name",
        "model_id",
        "temperature",
        "max_tokens",
        "system_prompt",
        "api_names",
        "comfort_tool_names",
        "comfort_tool_descriptions",
    }
    return {key: value[key] for key in allowed_keys if key in value}


def _parse_draft_response(message: BaseMessage) -> dict[str, Any] | None:
    text = _message_content_to_text(message)
    if not text:
        return None

    for candidate in [text, _extract_json_code_block(text), _extract_json_object(text)]:
        if not candidate:
            continue
        try:
            data = json_loads(candidate)
        except JSONDecodeError:
            continue
        if isinstance(data, dict):
            return data

    return None


def _message_content_to_text(message: BaseMessage) -> str:
    content = message.content
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])
        return "\n".join(parts).strip()
    return ""


def _extract_json_code_block(text: str) -> str | None:
    match = re_search(r"```(?:json)?\s*(\{.*?\})\s*```", text, flags=DOTALL)
    return match.group(1) if match else None


def _extract_json_object(text: str) -> str | None:
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        return None
    return text[start : end + 1]
