from json import loads
from urllib.parse import urlsplit
from httpx import AsyncClient
from langboard_shared.core.filter import AuthFilter
from langboard_shared.core.routing import AppRouter, BaseFormModel, JsonResponse, form_model
from langboard_shared.domain.models import SettingRole
from langboard_shared.domain.models.SettingRole import SettingRoleAction
from langboard_shared.Env import Env
from langboard_shared.filter import RoleFilter
from langboard_shared.security import RoleFinder
from langboard_shared.tasks.webhooks.utils import ResolvedWebhookTarget, ensure_public_webhook_url
from pydantic import Field, SecretStr


@form_model
class ModelListForm(BaseFormModel):
    base_url: str = Field(max_length=2048)
    api_key: SecretStr = Field(default=SecretStr(""), max_length=4096)


@AppRouter.api.post("/settings/model-providers/models", tags=["AppSettings.InternalBot"])
@RoleFilter.add(SettingRole, [SettingRoleAction.InternalBotUpdate], RoleFinder.setting, allowed_all_admin=False)
@AuthFilter.add("admin")
async def get_provider_models(form: ModelListForm = ModelListForm.scope()) -> JsonResponse:
    try:
        base_url = form.base_url.strip().rstrip("/")
        parsed = urlsplit(base_url)
        if (
            parsed.scheme not in ("http", "https")
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("Invalid model provider URL")
        allowed = {
            url.strip().rstrip("/")
            for url in Env.get_from_env("MODEL_PROVIDER_ALLOWED_BASE_URLS", "").split(",")
            if url.strip()
        }
        if base_url in allowed:
            target = ResolvedWebhookTarget(f"{base_url}/models", parsed.netloc, parsed.hostname)
        else:
            if parsed.scheme != "https":
                raise ValueError("Public model providers require HTTPS")
            target = await ensure_public_webhook_url(f"{base_url}/models")
        headers = {"Host": target.host_header, "Accept": "application/json"}
        key = form.api_key.get_secret_value().strip()
        if key:
            headers["Authorization"] = f"Bearer {key}"
        async with AsyncClient(timeout=10, follow_redirects=False, trust_env=False) as client:
            async with client.stream(
                "GET", target.url, headers=headers, extensions={"sni_hostname": target.sni_hostname}
            ) as response:
                response.raise_for_status()
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > 1024 * 1024:
                        raise ValueError("Model list is too large")
        records = loads(body).get("data")
        if not isinstance(records, list):
            raise ValueError("Invalid model list")
        models = sorted(
            {
                row["id"]
                for row in records
                if isinstance(row, dict) and isinstance(row.get("id"), str) and 0 < len(row["id"]) <= 256
            }
        )[:1000]
        return JsonResponse(content={"models": models})
    except Exception:
        # Provider errors must not expose credentials or upstream response bodies.
        return JsonResponse(content={"models": [], "error": "model_provider_unavailable"}, status_code=502)
