from typing import Any
from pydantic import BaseModel, ConfigDict, SerializerFunctionWrapHandler, model_serializer, model_validator


class BoundedItemsDto(BaseModel):
    """One bounded collection projection with an opaque continuation."""

    model_config = ConfigDict(extra="forbid")

    items: list[dict[str, Any]]
    total_count: int
    next_cursor: str | None
    limit: int


class BoundedTextDto(BaseModel):
    """One bounded text fragment with an opaque continuation."""

    model_config = ConfigDict(extra="forbid")

    content: str
    format: str
    total_chars: int
    next_cursor: str | None


class ClassificationDto(BaseModel):
    """Bounded labels and relationships for a card."""

    model_config = ConfigDict(extra="forbid")

    labels: BoundedItemsDto
    relationships: BoundedItemsDto


class AutomationDto(BaseModel):
    """Bounded native bot scope and schedule projections."""

    model_config = ConfigDict(extra="forbid")

    bot_scopes: BoundedItemsDto
    bot_schedules: BoundedItemsDto


class CardBundleDto(BaseModel):
    """Agent-facing native card aggregate."""

    model_config = ConfigDict(extra="forbid")

    core: dict[str, Any]
    workflow: dict[str, Any]
    people: BoundedItemsDto | None = None
    classification: ClassificationDto | None = None
    checklists: BoundedItemsDto | None = None
    comments: BoundedItemsDto | None = None
    attachments: BoundedItemsDto | None = None
    metadata: BoundedItemsDto | None = None
    automation: AutomationDto | None = None

    @model_serializer(mode="wrap")
    def serialize_selected_sections(self, handler: SerializerFunctionWrapHandler) -> dict[str, Any]:
        """Omit sections that callers did not explicitly request."""

        return {key: value for key, value in handler(self).items() if value is not None}


class CardBundleContinuationDto(BaseModel):
    """Continuation-only response for one selected card section."""

    model_config = ConfigDict(extra="forbid")

    section: str
    page: BoundedItemsDto | None = None
    text: BoundedTextDto | None = None

    @model_validator(mode="after")
    def validate_payload(self) -> "CardBundleContinuationDto":
        """Require exactly one continuation payload shape."""

        if (self.page is None) == (self.text is None):
            raise ValueError("A continuation must contain exactly one page or text payload")
        return self


class CardBundleResponse(BaseModel):
    """Structured MCP output for one card bundle."""

    model_config = ConfigDict(extra="forbid")

    card_uid: str
    card: CardBundleDto | None = None
    continuation: CardBundleContinuationDto | None = None

    @model_validator(mode="after")
    def validate_shape(self) -> "CardBundleResponse":
        """Return either the initial bundle or one continuation, never both."""

        if (self.card is None) == (self.continuation is None):
            raise ValueError("Response must contain exactly one card bundle or continuation")
        return self


class ProjectIdentityResponse(BaseModel):
    """Stable project identity plus its bounded active workflow columns."""

    model_config = ConfigDict(extra="forbid")

    uid: str
    title: str
    project_type: str
    url: str
    columns: BoundedItemsDto


class ProjectCardListResponse(BaseModel):
    """Bounded project card list."""

    model_config = ConfigDict(extra="forbid")

    project_uid: str
    cards: BoundedItemsDto
