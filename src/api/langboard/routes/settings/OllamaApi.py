import requests
from langboard_shared.core.caching import Cache
from langboard_shared.core.filter import AuthFilter
from langboard_shared.core.publisher import BaseSocketPublisher, SocketPublishModel
from langboard_shared.core.routing import (
    GLOBAL_TOPIC_ID,
    ApiErrorCode,
    ApiException,
    AppRouter,
    JsonResponse,
    SocketTopic,
)
from langboard_shared.core.schema import OpenApiSchema
from langboard_shared.domain.models import SettingRole
from langboard_shared.domain.models.SettingRole import SettingRoleAction
from langboard_shared.domain.services import DomainService
from langboard_shared.Env import Env
from langboard_shared.filter import RoleFilter
from langboard_shared.security import RoleFinder
from .Form import CopyOllamaModelForm, OllamaModelForm


_OLLAMA_PULLING_MODELS_CACHE_KEY = "ollama:pulling:models"


def _publish_model_change(event: str, data: dict[str, str]) -> None:
    try:
        BaseSocketPublisher.put_dispather(
            data,
            SocketPublishModel(topic=SocketTopic.OllamaManager, topic_id=GLOBAL_TOPIC_ID, event=event, data_keys=list(data)),
        )
    except Exception as error:
        raise ApiException.ServiceUnavailable_503() from error


@AppRouter.api.post("/settings/ollama/models/copy", tags=["AppSettings.Ollama"])
@RoleFilter.add(SettingRole, [SettingRoleAction.OllamaRead], RoleFinder.setting, allowed_all_admin=False)
@AuthFilter.add("admin")
def copy_ollama_model(form: CopyOllamaModelForm) -> JsonResponse:
    if not Env.OLLAMA_API_URL:
        raise ApiException.NotFound_404(ApiErrorCode.NF9000)

    try:
        response = requests.post(
            f"{Env.OLLAMA_API_URL}/api/copy",
            json={"source": form.model, "destination": form.copy_to},
            timeout=Env.AI_REQUEST_TIMEOUT,
        )
    except requests.RequestException as error:
        raise ApiException.BadGateway_502() from error

    if response.status_code == 404:
        raise ApiException.NotFound_404(ApiErrorCode.NF9001)
    if response.status_code != 200:
        raise ApiException.BadGateway_502()

    data = {"model": form.model, "copy_to": form.copy_to}
    _publish_model_change("settings:ollama:model:copied", data)
    return JsonResponse(content=data)


@AppRouter.api.delete("/settings/ollama/models", tags=["AppSettings.Ollama"])
@RoleFilter.add(SettingRole, [SettingRoleAction.OllamaRead], RoleFinder.setting, allowed_all_admin=False)
@AuthFilter.add("admin")
def delete_ollama_model(form: OllamaModelForm) -> JsonResponse:
    if not Env.OLLAMA_API_URL:
        raise ApiException.NotFound_404(ApiErrorCode.NF9000)

    try:
        response = requests.delete(
            f"{Env.OLLAMA_API_URL}/api/delete",
            json={"model": form.model},
            timeout=Env.AI_REQUEST_TIMEOUT,
        )
    except requests.RequestException as error:
        raise ApiException.BadGateway_502() from error

    if response.status_code not in {200, 404}:
        raise ApiException.BadGateway_502()

    data = {"model": form.model}
    _publish_model_change("settings:ollama:model:deleted", data)
    return JsonResponse(content=data)


@AppRouter.api.post("/settings/ollama/models/pull", tags=["AppSettings.Ollama"])
@RoleFilter.add(SettingRole, [SettingRoleAction.OllamaRead], RoleFinder.setting, allowed_all_admin=False)
@AuthFilter.add("admin")
def pull_ollama_model(form: OllamaModelForm, service: DomainService = DomainService.scope()) -> JsonResponse:
    if not Env.OLLAMA_API_URL:
        raise ApiException.NotFound_404(ApiErrorCode.NF9000)

    pull = service.ollama_model_pull.request_pull(form.model)
    return JsonResponse(
        content={
            "uid": pull.get_uid(),
            "model": pull.model_name,
            "status": pull.status.value,
            "percent": pull.percent,
            "attempt": pull.attempt,
        }
    )


@AppRouter.api.get("/settings/ollama/models/pull", tags=["AppSettings.Ollama"])
@RoleFilter.add(SettingRole, [SettingRoleAction.OllamaRead], RoleFinder.setting, allowed_all_admin=False)
@AuthFilter.add("admin")
def get_ollama_model_pulls(service: DomainService = DomainService.scope()) -> JsonResponse:
    pulls = service.ollama_model_pull.get_recent()
    return JsonResponse(
        content={
            "pulls": [
                {
                    "uid": pull.get_uid(),
                    "model": pull.model_name,
                    "status": pull.status.value,
                    "percent": pull.percent,
                    "attempt": pull.attempt,
                    "status_text": pull.status_text,
                    "error": pull.failure_reason,
                }
                for pull in pulls
            ]
        }
    )


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

        pulling_models: dict[str, bool] | None = Cache.get(_OLLAMA_PULLING_MODELS_CACHE_KEY)
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
