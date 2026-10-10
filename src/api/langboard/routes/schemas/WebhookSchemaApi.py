from typing import Any
from fastapi.openapi.docs import get_swagger_ui_html
from fastapi.responses import HTMLResponse
from langboard_shared.core.broker import Broker
from langboard_shared.core.routing import AppRouter, JsonResponse
from langboard_shared.core.schema import OpenApiSchema
from langboard_shared.domain.models import Bot, User
from langboard_shared.domain.models.bases import BotTriggerCondition
from langboard_shared.Env import Env
from langboard_shared.tasks.webhooks.utils import WEBHOOK_EVENT_NAMES, WORK_EXECUTION_EVENTS


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
_SAFE_EVENT_SCHEMA_FIELDS = frozenset(
    {
        "card_title",
        "old_project_column_is_archive",
        "old_project_column_name",
        "project_column_is_archive",
        "project_column_name",
        "project_title",
        "reaction_type",
    }
)
_DETERMINISTIC_EVENT_SCHEMAS: dict[str, dict[str, Any]] = {
    "bot_created": {"executor": {}},
    "bot_cron_scheduled": {
        "project_uid": "string",
        "project_column_uid": "string",
        "card_uid?": "string",
    },
    "work_event": {
        "event_type": "string",
        "actor": {"kind": "string", "uid": "string"},
        "recipient": {"kind": "string", "uid": "string"},
        "scope": {
            "project_uid": "string",
            "project_column_uid?": "string",
            "card_uid?": "string",
            "wiki_uid?": "string",
            "checklist_uid?": "string",
            "checkitem_uid?": "string",
            "project_invitation_uid?": "string",
        },
        "notification_uid": "string",
        "payload_hash": "string",
        "correlation_id": "string",
        "priority": "string",
    },
}
_EXECUTION_EVENT_SCHEMA = {
    "execution_generation": "integer",
    "title": "string",
    "labels": "string[]",
    "assignees": "string[]",
    "card_url": "string",
    "source_revision": "string",
}
_DETERMINISTIC_EVENT_SCHEMAS.update({name: _EXECUTION_EVENT_SCHEMA for name in WORK_EXECUTION_EVENTS})


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
        schema = _minimal_event_schema(schemas[schema_name], event=schema_name)
        if schema_name in WORK_EXECUTION_EVENTS:
            data_schema = _make_object_property("data", schema)
            data_schema["properties"]["source_revision"] = {
                "type": "string",
                "format": "date-time",
                "description": "Card.updated_at from the delivery-time point-read that produced this payload; "
                "provenance only. Fence on execution_generation plus point-read readiness, not on this revision.",
            }
            schemas[schema_name] = {
                "title": schema_name,
                "type": "object",
                "properties": {
                    "specversion": {"type": "string", "enum": ["1.0"]},
                    "id": {"type": "string", "format": "uuid"},
                    "source": {"type": "string", "pattern": "^/projects/[^/]+$"},
                    "subject": {"type": "string", "pattern": "^cards/[^/]+$"},
                    "type": {"type": "string", "enum": [schema_name]},
                    "time": {"type": "string", "format": "date-time"},
                    "data": data_schema,
                },
                "required": ["specversion", "id", "source", "subject", "type", "time", "data"],
                "additionalProperties": False,
            }
            continue
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
                "signature_format": "v1=<lowercase hex HMAC-SHA256>",
                "freshness_timestamp_header": "X-Langboard-Webhook-Timestamp",
                "example": {
                    "timestamp": "1786003200",
                    "signed_content": "1786003200.{\"specversion\":\"1.0\",...}",
                    "note": "Sign the exact delivered bytes; CloudEvent time is business time, not freshness time.",
                },
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

        value_type = property_value.replace("?", "")
        schema[output_name] = {
            "type": "array" if value_type.endswith("[]") else value_type,
            "title": output_name.replace("_", " ").capitalize(),
        }
        if value_type.endswith("[]"):
            schema[output_name]["items"] = {"type": value_type[:-2]}

    return schema, required


def _minimal_event_schema(schema: dict[str, Any], *, event: str | None = None) -> dict[str, Any]:
    """Expose only routing identifiers and non-PII actor identity."""

    if event in WORK_EXECUTION_EVENTS:
        return schema

    result = {
        key: value
        for key, value in schema.items()
        if key.removesuffix("?") in _SAFE_EVENT_SCHEMA_IDENTIFIERS
        or key.removesuffix("?") in _SAFE_EVENT_SCHEMA_FIELDS
        or (
            event == "work_event"
            and key
            in {
                "event_type",
                "actor",
                "recipient",
                "scope",
                "notification_uid",
                "payload_hash",
                "correlation_id",
                "priority",
            }
        )
    }
    if "executor" in schema:
        result["executor"] = {"uid": "string", "type": "string", "display_name": "string"}
    return result
