from langboard_shared.core.routing import BaseFormModel, form_model
from langboard_shared.core.types.BotRelatedTypes import AVAILABLE_BOT_TARGET_TABLES
from langboard_shared.domain.models.bases import BotTriggerCondition
from pydantic import Field


@form_model
class CreateBotScopeForm(BaseFormModel):
    target_table: str = Field(..., title=f"Target table name ({', '.join(AVAILABLE_BOT_TARGET_TABLES.keys())})")
    target_uid: str = Field(..., title="Target UID")
    conditions: list[BotTriggerCondition] = Field(default=[], title="List of conditions for the bot trigger")


@form_model
class UpsertBotHookForm(BaseFormModel):
    """Desired event hook for one bot and one native target."""

    target_table: str = Field(..., title=f"Target type ({', '.join(AVAILABLE_BOT_TARGET_TABLES.keys())})")
    target_uid: str = Field(..., title="Target UID")
    events: list[BotTriggerCondition] = Field(..., min_length=1, title="Events subscribed by the bot")
    active: bool = True


@form_model
class ToggleBotTriggerConditionForm(BaseFormModel):
    target_table: str = Field(..., title=f"Target table name ({', '.join(AVAILABLE_BOT_TARGET_TABLES.keys())})")
    condition: BotTriggerCondition


@form_model
class ToggleBotScopeFreezeForm(BaseFormModel):
    target_table: str = Field(..., title=f"Target table name ({', '.join(AVAILABLE_BOT_TARGET_TABLES.keys())})")
    is_frozen: bool


@form_model
class DeleteBotScopeForm(BaseFormModel):
    target_table: str = Field(..., title=f"Target table name ({', '.join(AVAILABLE_BOT_TARGET_TABLES.keys())})")


@form_model
class ApplyDefaultBotScopeForm(BaseFormModel):
    target_table: str = Field(..., title=f"Target table name ({', '.join(AVAILABLE_BOT_TARGET_TABLES.keys())})")
    target_uid: str = Field(..., title="Target UID")
    default_scope_branch_uid: str | None = Field(
        None, title="Default scope branch UID to apply, or null to switch to custom mode"
    )
