from langboard_shared.core.db import EditorContentModel
from langboard_shared.core.routing import BaseFormModel, form_model
from langboard_shared.domain.models.bases import REACTION_TYPES
from langboard_shared.domain.models.CardComment import CardCommentAnchorModel
from pydantic import Field, field_validator


class CreateCardCommentForm(EditorContentModel):
    anchor: CardCommentAnchorModel | None = None


@form_model
class ToggleCardCommentReactionForm(BaseFormModel):
    reaction: str = Field(..., description=f"Reaction type: {', '.join(REACTION_TYPES)}")

    @field_validator("reaction")
    @classmethod
    def validate_reaction(cls, value: str) -> str:
        if value not in REACTION_TYPES:
            raise ValueError("Unsupported comment reaction")
        return value
