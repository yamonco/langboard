from langboard_shared.core.routing import BaseFormModel, form_model
from langboard_shared.core.schema import TimeBasedPagination


@form_model
class DashboardProjectCreateForm(BaseFormModel):
    title: str
    description: str | None = None
    project_type: str = "Other"
    template_name: str | None = None


class DashboardPagination(TimeBasedPagination):
    pass
