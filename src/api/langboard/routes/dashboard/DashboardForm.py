from typing import Annotated
from langboard_shared.core.routing import BaseFormModel, form_model
from langboard_shared.core.schema import TimeBasedPagination
from pydantic import Field, StringConstraints


@form_model
class DashboardProjectCreateForm(BaseFormModel):
    title: str
    description: str | None = None
    project_type: str = "Other"
    template_name: str | None = None


class DashboardPagination(TimeBasedPagination):
    pass


@form_model
class RecentCardsAvailabilityForm(BaseFormModel):
    card_uids: Annotated[list[Annotated[str, StringConstraints(min_length=1, max_length=32)]], Field(max_length=200)]
