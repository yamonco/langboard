from langboard_shared.core.routing import BaseFormModel, form_model
from pydantic import Field


@form_model
class ColumnForm(BaseFormModel):
    name: str = Field(..., description="Project column name")


@form_model
class CreateColumnForm(BaseFormModel):
    """Create a named column with optional workflow guidance."""

    name: str = Field(..., description="Project column name")
    description: str = Field(default="", max_length=4096, description="When cards should enter this column")


@form_model
class ColumnDescriptionForm(BaseFormModel):
    """Replace column guidance; an empty string explicitly clears it."""

    description: str = Field(..., max_length=4096, description="When cards should enter this column")
