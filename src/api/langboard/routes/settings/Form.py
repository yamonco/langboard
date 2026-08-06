from re import match
from typing import Any
from langboard_shared.ai import BaseSharedBotForm
from langboard_shared.core.routing import BaseFormModel, form_model
from langboard_shared.core.routing.Exception import MissingException, ValidationFailureException, ValidationFailureInfo
from langboard_shared.core.types import SafeDateTime
from langboard_shared.domain.models.ApiKeyRole import ApiKeyRoleAction
from langboard_shared.domain.models.BaseBotModel import BotPlatform, BotPlatformRunningType
from langboard_shared.domain.models.InternalBot import InternalBotType
from langboard_shared.domain.models.McpRole import McpRoleAction
from langboard_shared.domain.models.SettingRole import SettingRoleAction
from langboard_shared.tasks.webhooks.utils import validate_webhook_events
from pydantic import BaseModel, Field, field_validator
from ...Constants import EMAIL_REGEX


@form_model
class CreateUserForm(BaseFormModel):
    firstname: str
    lastname: str
    email: str
    password: str
    industry: str
    purpose: str
    affiliation: str | None = None
    position: str | None = None
    is_admin: bool = False
    should_activate: bool = False

    @field_validator("email")
    @classmethod
    def validate_email(cls, value: str) -> str:
        if not value:
            raise MissingException("body", "email", {"email": value})

        if not bool(match(EMAIL_REGEX, value)):
            raise ValidationFailureException(
                ValidationFailureInfo(
                    loc="body",
                    field="email",
                    inputs={"email": value},
                )
            )

        return value


@form_model
class UpdateUserForm(BaseFormModel):
    firstname: str | None = None
    lastname: str | None = None
    password: str | None = None
    industry: str | None = None
    purpose: str | None = None
    affiliation: str | None = None
    position: str | None = None
    is_admin: bool | None = None
    activate: bool | None = None


@form_model
class DeleteSelectedUsersForm(BaseFormModel):
    user_uids: list[str]


@form_model
class CreateBotForm(BaseSharedBotForm):
    bot_name: str
    bot_uname: str
    ip_whitelist: str | None = None


@form_model
class UpdateBotForm(BaseFormModel):
    bot_name: str | None = None
    bot_uname: str | None = None
    platform: BotPlatform | None = None
    platform_running_type: BotPlatformRunningType | None = None
    api_url: str | None = None
    api_key: str | None = None
    ip_whitelist: str | None = None
    value: str | None = None
    delete_avatar: bool = False


class BotActionSuggestionForm(BaseModel):
    prompt: str = ""
    selected_api_names: list[str] = Field(default_factory=list)
    selected_comfort_tool_names: list[str] = Field(default_factory=list)
    include_mcp: bool = True
    limit: int = 8


class BotDraftForm(BaseModel):
    instruction: str
    value: dict[str, Any] = Field(default_factory=dict)
    selected_api_names: list[str] = Field(default_factory=list)
    selected_comfort_tool_names: list[str] = Field(default_factory=list)
    include_mcp: bool = True


@form_model
class CreateBotDefaultScopeBranchForm(BaseFormModel):
    name: str


@form_model
class UpdateBotDefaultScopeBranchForm(BaseFormModel):
    name: str | None = None
    conditions_map: dict[str, list[str]] | None = None


@form_model
class DeleteBotDefaultScopeBranchForm(BaseFormModel):
    default_scope_uid: str


@form_model
class CreateGlobalRelationshipTypeForm(BaseFormModel):
    parent_name: str
    child_name: str
    description: str = ""


@form_model
class ImportGlobalRelationshipTypesForm(BaseFormModel):
    relationships: list[CreateGlobalRelationshipTypeForm]


@form_model
class UpdateGlobalRelationshipTypeForm(BaseFormModel):
    parent_name: str | None = None
    child_name: str | None = None
    description: str | None = None


@form_model
class DeleteSelectedGlobalRelationshipTypesForm(BaseFormModel):
    relationship_type_uids: list[str]


@form_model
class CreateInternalBotForm(BaseSharedBotForm):
    bot_type: InternalBotType
    display_name: str


@form_model
class UpdateInternalBotForm(BaseFormModel):
    display_name: str | None = None
    platform: BotPlatform | None = None
    platform_running_type: BotPlatformRunningType | None = None
    api_url: str | None = None
    api_key: str | None = None
    value: str | None = None
    delete_avatar: bool = False


@form_model
class OllamaModelForm(BaseFormModel):
    model: str


@form_model
class CreateApiKeyForm(BaseFormModel):
    name: str
    ip_whitelist: str | None = None
    is_active: bool = True
    expires_in_days: str | None = None

    @field_validator("expires_in_days")
    @classmethod
    def validate_expires_in_days(cls, value: str | None) -> str | None:
        if value is not None and value != "never":
            valid_values = ["30", "60", "90", "180", "365"]
            if value not in valid_values:
                raise ValidationFailureException(
                    ValidationFailureInfo(
                        loc="body",
                        field="expires_in_days",
                        inputs={"expires_in_days": value},
                    )
                )
        return value


@form_model
class UpdateApiKeyForm(BaseFormModel):
    name: str | None = None
    ip_whitelist: str | None = None


@form_model
class DeleteSelectedApiKeysForm(BaseFormModel):
    key_uids: list[str]


class ApiKeysPagination(BaseModel):
    page: int = 1
    limit: int = 0
    refer_time: SafeDateTime = SafeDateTime.now()
    only_count: bool = False


@form_model
class CreateMcpToolGroupForm(BaseFormModel):
    name: str
    description: str = ""
    tools: list[str]
    activate: bool = True
    is_global: bool = False


@form_model
class UpdateMcpToolGroupForm(BaseFormModel):
    name: str | None = None
    description: str | None = None
    tools: list[str] | None = None
    activate: bool | None = None


@form_model
class DeleteSelectedMcpToolGroupsForm(BaseFormModel):
    group_uids: list[str]


@form_model
class UpdateSettingRoleForm(BaseFormModel):
    actions: list[SettingRoleAction]


@form_model
class UpdateApiKeyRoleForm(BaseFormModel):
    actions: list[ApiKeyRoleAction]


@form_model
class UpdateMcpRoleForm(BaseFormModel):
    actions: list[McpRoleAction]


@form_model
class CreateWebhookForm(BaseFormModel):
    """Webhook creation input."""

    name: str
    url: str
    events: list[str] | None = None

    @field_validator("events")
    @classmethod
    def validate_events(cls, events: list[str] | None) -> list[str] | None:
        """Validate a supplied webhook event allowlist."""

        return validate_webhook_events(events)


@form_model
class UpdateWebhookForm(BaseFormModel):
    """Partial webhook update input."""

    name: str | None = None
    url: str | None = None
    events: list[str] | None = None

    @field_validator("events")
    @classmethod
    def validate_events(cls, events: list[str] | None) -> list[str] | None:
        """Validate a supplied webhook event allowlist."""

        return validate_webhook_events(events)


@form_model
class DeleteSelectedWebhooksForm(BaseFormModel):
    webhook_uids: list[str]


@form_model
class SetDefaultProjectTemplateForm(BaseFormModel):
    template_name: str


@form_model
class CreateNotificationScheduleRuleForm(BaseFormModel):
    name: str
    is_enabled: bool = False
    interval_str: str = "0 9 * * *"
    timezone: str | float = "UTC"
    target: str
    field: str
    operator: str
    value: Any | None = None
    recipients: list[str] = Field(default_factory=list)
    repeat_after_hours: int = 24


@form_model
class UpdateNotificationScheduleRuleForm(BaseFormModel):
    name: str | None = None
    is_enabled: bool | None = None
    interval_str: str | None = None
    timezone: str | float | None = None
    target: str | None = None
    field: str | None = None
    operator: str | None = None
    value: Any | None = None
    recipients: list[str] | None = None
    repeat_after_hours: int | None = None


@form_model
class DeleteSelectedNotificationScheduleRulesForm(BaseFormModel):
    rule_uids: list[str]
