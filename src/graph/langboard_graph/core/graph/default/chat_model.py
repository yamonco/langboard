from typing import Any
from langboard_shared.core.logger import Logger
from langboard_shared.Env import Env
from langchain.chat_models import init_chat_model


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

    provider = PROVIDER_MAP.get(agent_llm)
    if not provider:
        return None

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

    try:
        return init_chat_model(str(model_name), model_provider=provider, **kwargs)
    except Exception as exc:
        Logger.main.exception(exc)
        return None
