from langboard_shared.core.routing import BaseFormModel, form_model
from pydantic import Field


@form_model
class CreateProjectLabelForm(BaseFormModel):
    name: str = Field(..., description="Project label name")
    color: str = Field(..., description="Project label color in hex format")
    description: str = Field(..., description="Project label description")


@form_model
class UpdateProjectLabelDetailsForm(BaseFormModel):
    name: str | None = Field(default=None, description="Project label name")
    color: str | None = Field(default=None, description="Project label color in hex format")
    description: str | None = Field(default=None, description="Project label description")


@form_model
class UseGlobalProjectLabelForm(BaseFormModel):
    global_label_uid: str = Field(..., min_length=1, max_length=100, description="Existing global label UID")
