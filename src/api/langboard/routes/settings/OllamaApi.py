import requests
from langboard_shared.core.caching import Cache
from langboard_shared.core.filter import AuthFilter
from langboard_shared.core.routing import ApiErrorCode, ApiException, AppRouter, JsonResponse
from langboard_shared.core.schema import OpenApiSchema
from langboard_shared.domain.models import SettingRole
from langboard_shared.domain.models.SettingRole import SettingRoleAction
from langboard_shared.Env import Env
from langboard_shared.filter import RoleFilter
from langboard_shared.security import RoleFinder
from .Form import OllamaModelForm


_OLLAMA_PULLING_MODELS_CACHE_KEY = "ollama:pulling:models"


@AppRouter.api.get(
    "/settings/ollama/health",
    tags=["AppSettings.Ollama"],
    responses=OpenApiSchema().suc({"configured": "boolean", "available": "boolean"}).auth().forbidden().get(),
)
@RoleFilter.add(SettingRole, [SettingRoleAction.OllamaRead], RoleFinder.setting, allowed_all_admin=False)
@AuthFilter.add("admin")
def get_ollama_health() -> JsonResponse:
    if not Env.OLLAMA_API_URL:
        return JsonResponse(content={"configured": False, "available": False})

    try:
        response = requests.get(f"{Env.OLLAMA_API_URL}/api/tags", timeout=3)
        response.raise_for_status()
        return JsonResponse(content={"configured": True, "available": True})
    except Exception:
        return JsonResponse(content={"configured": True, "available": False})


@AppRouter.api.get(
    "/settings/ollama/models",
    tags=["AppSettings.Ollama"],
    responses=(
        OpenApiSchema()
        .suc(
            {
                "models": [{"check ollama api docs": "https://docs.ollama.com/api/tags"}],
                "pulling_models": {"<name>": "integer"},
            }
        )
        .auth()
        .forbidden()
        .get()
    ),
)
@RoleFilter.add(SettingRole, [SettingRoleAction.OllamaRead], RoleFinder.setting, allowed_all_admin=False)
@AuthFilter.add("admin")
def get_ollama_models() -> JsonResponse:
    if not Env.OLLAMA_API_URL:
        return JsonResponse(content={"models": [], "pulling_models": {}})

    try:
        response = requests.get(f"{Env.OLLAMA_API_URL}/api/tags", timeout=Env.AI_REQUEST_TIMEOUT)
        response.raise_for_status()
        data = response.json()
        data["pulling_models"] = []

        pulling_models: dict | None = Cache.get(_OLLAMA_PULLING_MODELS_CACHE_KEY)
        if pulling_models:
            for model in data.get("models", []):
                if model["name"] in pulling_models:
                    pulling_models.pop(model["name"])

            Cache.set(_OLLAMA_PULLING_MODELS_CACHE_KEY, pulling_models, ttl=24 * 60 * 60)
            data["pulling_models"] = pulling_models

        return JsonResponse(content=data)
    except Exception:
        return JsonResponse(content={"models": [], "pulling_models": {}})


@AppRouter.api.post(
    "/settings/ollama/model/details",
    tags=["AppSettings.Ollama"],
    responses=(
        OpenApiSchema()
        .suc({"check ollama api docs": "https://docs.ollama.com/api-reference/show-model-details"})
        .auth()
        .forbidden()
        .err(404, ApiErrorCode.NF9000, ApiErrorCode.NF9001)
        .get()
    ),
)
@RoleFilter.add(SettingRole, [SettingRoleAction.OllamaRead], RoleFinder.setting, allowed_all_admin=False)
@AuthFilter.add("admin")
def get_ollama_model_details(form: OllamaModelForm) -> JsonResponse:
    if not Env.OLLAMA_API_URL:
        raise ApiException.NotFound_404(ApiErrorCode.NF9000)

    try:
        response = requests.post(
            f"{Env.OLLAMA_API_URL}/api/show",
            json={"model": form.model},
            timeout=Env.AI_REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        data = response.json()
        return JsonResponse(content=data)
    except Exception:
        raise ApiException.NotFound_404(ApiErrorCode.NF9001)


@AppRouter.api.get(
    "/settings/ollama/models/running",
    tags=["AppSettings.Ollama"],
    responses=(
        OpenApiSchema().suc({"check ollama api docs": "https://docs.ollama.com/api/ps"}).auth().forbidden().get()
    ),
)
@RoleFilter.add(SettingRole, [SettingRoleAction.OllamaRead], RoleFinder.setting, allowed_all_admin=False)
@AuthFilter.add("admin")
def get_ollama_running_models() -> JsonResponse:
    if not Env.OLLAMA_API_URL:
        return JsonResponse(content={"models": []})

    try:
        response = requests.get(f"{Env.OLLAMA_API_URL}/api/ps", timeout=Env.AI_REQUEST_TIMEOUT)
        response.raise_for_status()
        data = response.json()
        return JsonResponse(content=data)
    except Exception:
        return JsonResponse(content={"models": []})
