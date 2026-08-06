from typing import Any
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import HTMLResponse
from langboard_shared.core.broker import Broker
from langboard_shared.core.routing import AppRouter, JsonResponse
from langboard_shared.core.schema import OpenApiSchema
from langboard_shared.domain.models import Bot, User
from langboard_shared.domain.models.bases import BotTriggerCondition
from langboard_shared.Env import Env
from langboard_shared.tasks.webhooks.utils import WEBHOOK_EVENT_NAMES


_SAFE_EVENT_SCHEMA_IDENTIFIERS = frozenset(
    {
        "attachment_uid",
        "card_uid",
        "cardified_card_uid",
        "checkitem_uid",
        "checklist_uid",
        "comment_uid",
        "old_project_column_uid",
        "project_column_uid",
        "project_label_uid",
        "project_uid",
        "project_wiki_uid",
    }
)
_DETERMINISTIC_EVENT_SCHEMAS: dict[str, dict[str, Any]] = {
    "bot_created": {"executor": {}},
    "bot_cron_scheduled": {
        "project_uid": "string",
        "project_column_uid": "string",
        "card_uid?": "string",
    },
}


@AppRouter.api.get("/schema/webhook", response_class=HTMLResponse)
def webhook_docs():
    return get_swagger_ui_html(openapi_url="/schema/webhook.json", title=Env.PROJECT_NAME.capitalize())


@AppRouter.api.get("/schema/webhook.json", include_in_schema=False)
def webhook_openapi() -> JsonResponse:
    """Return the deterministic public schema for emitted webhook events."""

    registered_schemas = Broker.get_schema("webhook")
    schemas = {
        event: _DETERMINISTIC_EVENT_SCHEMAS.get(event, registered_schemas.get(event, {}))
        for event in sorted(WEBHOOK_EVENT_NAMES)
    }
    bot_schema = {
        **Bot.api_schema(),
        "app_api_token": "string",
        "prompt": "string",
    }
    bot_schema = _make_object_property("bot", bot_schema)
    user_schema = User.api_schema()
    user_schema = _make_object_property("user", user_schema)

    for schema_name in schemas:
        schema = _minimal_event_schema(schemas[schema_name])
        schemas[schema_name] = {
            "title": schema_name.replace("_", " ").capitalize(),
            "type": "object",
            "properties": {
                "schema_version": {"type": "string", "enum": ["1"]},
                "event_id": {"type": "string", "format": "uuid"},
                "occurred_at": {"type": "string", "format": "date-time"},
                "event": {"type": "string", "title": "Event", "enum": [schema_name]},
                "data": _make_object_property("data", schema),
            },
            "required": ["schema_version", "event_id", "occurred_at", "event", "data"],
        }

    return JsonResponse(
        content={
            "openapi": "3.1.0",
            "info": {
                "title": Env.PROJECT_NAME.capitalize(),
                "version": Env.PROJECT_VERSION,
            },
            "components": {"schemas": schemas},
            "x-langboard-webhook-signature": {
                "algorithm": "HMAC-SHA256",
                "signed_content": "<X-Langboard-Webhook-Timestamp>.<raw request body>",
                "headers": [
                    "X-Langboard-Webhook-Id",
                    "X-Langboard-Webhook-Timestamp",
                    "X-Langboard-Webhook-Version",
                    "X-Langboard-Webhook-Signature",
                ],
            },
            "shared": {
                "Bot": bot_schema,
                "User": user_schema,
            },
        }
    )


@AppRouter.api.get(
    "/schema/bot/trigger-conditions",
    tags=["Schema"],
    responses=OpenApiSchema().suc({"conditions": BotTriggerCondition}).get(),
)
def get_bot_trigger_conditions():
    return JsonResponse(content={"conditions": [condition.value for condition in BotTriggerCondition]})


def _make_object_property(schema_name: str, schema: dict[str, Any]):
    properties, required = _make_property(schema)

    return {
        "type": "object",
        "title": schema_name.replace("_", " ").capitalize(),
        "properties": properties,
        "required": required,
    }


def _make_property(properties: dict[str, Any]):
    required = []
    schema = {}
    for property_name in properties:
        output_name = property_name.removesuffix("?")
        property_value: str | dict = properties[property_name]
        if isinstance(property_value, dict):
            if "oneOf" in property_value:
                schema[output_name] = {
                    "oneOf": [
                        _make_object_property(oneOf, property_value["oneOf"][oneOf])
                        for oneOf in property_value["oneOf"]
                    ]
                }
            else:
                schema[output_name] = _make_object_property(output_name, property_value)
            continue

        if "?" not in property_name and "?" not in property_value:
            required.append(output_name)

        schema[output_name] = {
            "type": property_value.replace("?", ""),
            "title": output_name.replace("_", " ").capitalize(),
        }

    return schema, required


def _minimal_event_schema(schema: dict[str, Any]) -> dict[str, Any]:
    """Expose only routing identifiers and non-PII actor identity."""

    result = {
        key: value
        for key, value in schema.items()
        if key.removesuffix("?") in _SAFE_EVENT_SCHEMA_IDENTIFIERS or key == "reaction_type"
    }
    if "executor" in schema:
        result["executor"] = {"uid": "string", "type": "string"}
    return result
