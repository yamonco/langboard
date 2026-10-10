from langboard_shared.core.routing import BaseFormModel, form_model
from langboard_shared.domain.models.Checkitem import CheckitemStatus
from pydantic import Field


@form_model
class CardCheckRelatedForm(BaseFormModel):
    title: str = Field(..., title="Title of the checklist or checkitem")


@form_model
class ChangeCardCheckitemStatusForm(BaseFormModel):
    status: CheckitemStatus
    replace_active: bool = False


@form_model
class ChangeCardCheckitemDeadlineForm(BaseFormModel):
    deadline_at: str | None = Field(default=None, title="Deadline of the checkitem")


@form_model
class CardChecklistNotifyForm(BaseFormModel):
    user_uids: list[str] = Field(..., title="List of user UIDs")


@form_model
class CardifyCheckitemForm(BaseFormModel):
    project_column_uid: str = Field(..., title="UID of the project column for the new card that will be created")
