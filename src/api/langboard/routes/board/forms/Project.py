from typing import Literal
from langboard_shared.core.routing import BaseFormModel, form_model
from langboard_shared.core.schema import TimeBasedPagination
from langboard_shared.domain.models.GraphApprovalRequest import GraphApprovalOriginType, GraphApprovalStatus
from langboard_shared.domain.models.InternalBot import InternalBotType
from langboard_shared.domain.models.ProjectRole import ProjectRoleAction
from pydantic import BaseModel, Field


@form_model
class InviteProjectMemberForm(BaseFormModel):
    emails: list[str]


@form_model
class ProjectInvitationForm(BaseFormModel):
    invitation_token: str


class ChatHistoryPagination(TimeBasedPagination):
    pass


class GraphApprovalListForm(BaseModel):
    status: GraphApprovalStatus | None = GraphApprovalStatus.Pending
    origin_type: GraphApprovalOriginType | None = None
    scope_table: str | None = None
    scope_uid: str | None = None
    limit: int = Field(100, ge=1, le=500)


@form_model
class RejectGraphApprovalForm(BaseFormModel):
    reason: str | None = None


@form_model
class UpdateProjectDetailsForm(BaseFormModel):
    title: str = Field(..., description="Project title")
    description: str | None = Field(None, description="Project description")
    project_type: str = Field("Other", description="Project type")
    archive_visible_days: int = Field(3, ge=1, description="Visible archived card days")


@form_model
class UpdateRolesForm(BaseFormModel):
    roles: list[ProjectRoleAction]


@form_model
class ChangeInternalBotForm(BaseFormModel):
    internal_bot_uid: str


@form_model
class ChangeInternalBotSettingsForm(BaseFormModel):
    bot_type: InternalBotType
    use_default_prompt: bool | None = None
    prompt: str | None = None


@form_model
class CopyProjectTemplateForm(BaseFormModel):
    name: str


@form_model
class UpdateProjectChatSessionForm(BaseFormModel):
    title: str | None = None
    api_permission_level: Literal["read", "edit", "full_access"] | None = None
