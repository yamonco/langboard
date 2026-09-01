from functools import lru_cache
from json import dumps as json_dumps
from json import loads as json_loads
from typing import Any
from langboard_shared.core.logger import Logger
from langboard_shared.Env import Env
from langchain.chat_models import init_chat_model
from langchain.chat_models.base import BaseChatModel, _ConfigurableModel


PROVIDER_MAP = {
    "OpenAI": "openai",
    "Azure OpenAI": "azure_openai",
    "Groq": "groq",
    "Anthropic": "anthropic",
    "NVIDIA": "nvidia",
    "IBM Watson": "ibm",
    "Amazon Bedrock": "bedrock_converse",
    "Google Generative AI": "google_genai",
    "Ollama": "ollama",
    "LM Studio": "openai",
}

NON_MODEL_SETTING_KEYS = {
    "agent_llm",
    "api_names",
    "comfort_tool_names",
    "comfort_tool_descriptions",
    "comfort_tool_definitions",
    "system_prompt",
    "approval_request",
    "api_approval_policy",
}


def create_default_chat_model(agent_llm: str | None, settings: dict[str, Any]):
    if not agent_llm:
        return None
    try:
        settings_json = json_dumps(settings, sort_keys=True, separators=(",", ":"))
    except (TypeError, ValueError) as exc:
        Logger.main.exception(exc)
        return None
    try:
        return _create_cached_default_chat_model(agent_llm, settings_json)
    except Exception as exc:
        Logger.main.exception(exc)
        return None


@lru_cache(maxsize=32)
def _create_cached_default_chat_model(agent_llm: str, settings_json: str) -> BaseChatModel | _ConfigurableModel | None:
    provider = PROVIDER_MAP.get(agent_llm)
    if not provider:
        return None

    settings = json_loads(settings_json)
    model_name = settings.get("model_name") or settings.get("model") or settings.get("model_id")
    if not model_name:
        return None

    kwargs = {
        key: value for key, value in settings.items() if key not in NON_MODEL_SETTING_KEYS and value not in (None, "")
    }
    kwargs.pop("model", None)
    kwargs.pop("model_name", None)

    if agent_llm == "Ollama" and kwargs.get("base_url") == "default":
        kwargs["base_url"] = Env.OLLAMA_API_URL
    if agent_llm == "LM Studio":
        kwargs.setdefault("api_key", "lm-studio")

    return init_chat_model(str(model_name), model_provider=provider, **kwargs)
