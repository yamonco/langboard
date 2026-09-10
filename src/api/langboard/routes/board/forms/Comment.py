from langboard_shared.core.db import EditorContentModel
from langboard_shared.core.routing import BaseFormModel, form_model
from langboard_shared.domain.models.bases import REACTION_TYPES
from langboard_shared.domain.models.CardComment import CardCommentAnchorModel
from pydantic import Field


class CreateCardCommentForm(EditorContentModel):
    anchor: CardCommentAnchorModel | None = None


@form_model
class ToggleCardCommentReactionForm(BaseFormModel):
    reaction: str = Field(..., description=f"Reaction type: {', '.join(REACTION_TYPES)}")
