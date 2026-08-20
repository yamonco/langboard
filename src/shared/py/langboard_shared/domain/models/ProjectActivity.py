from enum import Enum
from typing import Any
from ...core.db import ApiField, EnumLikeType, Field, SnowflakeIDField
from ...core.types import SnowflakeID
from .bases import BaseActivityModel
from .Card import Card
from .Project import Project
from .ProjectColumn import ProjectColumn


class ProjectActivityType(Enum):
    # Project
    ProjectCreated = "project_created"
    ProjectUpdated = "project_updated"
    ProjectAssignedUsersUpdated = "project_assigned_users_updated"
    ProjectEmailNotificationPolicyUpdated = "project_email_notification_policy_updated"
    ProjectInvitedUserAccepted = "project_invited_user_accepted"
    ProjectDeleted = "project_deleted"

    # Project Column
    ProjectColumnCreated = "project_column_created"
    ProjectColumnNameChanged = "project_column_name_changed"
    ProjectColumnDeleted = "project_column_deleted"

    # Project Label
    ProjectLabelCreated = "project_label_created"
    ProjectLabelUpdated = "project_label_updated"
    ProjectLabelDeleted = "project_label_deleted"

    # Card
    CardCreated = "card_created"
    CardUpdated = "card_updated"
    CardMoved = "card_moved"
    CardAssignedUsersUpdated = "card_assigned_users_updated"
    CardLabelsUpdated = "card_labels_updated"
    CardDeleted = "card_deleted"

    # Card Attachment
    CardAttachmentUploaded = "card_attachment_uploaded"
    CardAttachmentNameChanged = "card_attachment_name_changed"
    CardAttachmentDeleted = "card_attachment_deleted"

    # Card Comment
    CardCommentAdded = "card_comment_added"
    CardCommentUpdated = "card_comment_updated"
    CardCommentDeleted = "card_comment_deleted"
    CardCommentReacted = "card_comment_reacted"
    CardCommentUnreacted = "card_comment_unreacted"

    # Card Relationships
    CardRelationshipsUpdated = "card_relationships_updated"

    # Card Checklist
    CardChecklistCreated = "card_checklist_created"
    CardChecklistTitleChanged = "card_checklist_title_changed"
    CardChecklistChecked = "card_checklist_checked"
    CardChecklistUnchecked = "card_checklist_unchecked"
    CardChecklistDeleted = "card_checklist_deleted"

    # Card Checkitem
    CardCheckitemCreated = "card_checkitem_created"
    CardCheckitemTitleChanged = "card_checkitem_title_changed"
    CardCheckitemTimerStarted = "card_checkitem_timer_started"
    CardCheckitemTimerPaused = "card_checkitem_timer_paused"
    CardCheckitemTimerStopped = "card_checkitem_timer_stopped"
    CardCheckitemChecked = "card_checkitem_checked"
    CardCheckitemUnchecked = "card_checkitem_unchecked"
    CardCheckitemCardified = "card_checkitem_cardified"
    CardCheckitemDeleted = "card_checkitem_deleted"


class ProjectActivity(BaseActivityModel, table=True):
    project_id: SnowflakeID = SnowflakeIDField(foreign_key=Project, index=True)
    project_column_id: SnowflakeID | None = SnowflakeIDField(foreign_key=ProjectColumn, nullable=True)
    card_id: SnowflakeID | None = SnowflakeIDField(foreign_key=Card, nullable=True)
    activity_type: ProjectActivityType = Field(
        nullable=False, sa_type=EnumLikeType(ProjectActivityType), api_field=ApiField()
    )

    def api_response(self) -> dict[str, Any]:
        response = super().api_response()
        response["filterable_map"] = {
            Project.__tablename__: self.project_id.to_short_code(),
        }

        if self.project_column_id:
            response["filterable_map"][ProjectColumn.__tablename__] = self.project_column_id.to_short_code()
        if self.card_id:
            response["filterable_map"][Card.__tablename__] = self.card_id.to_short_code()
        return response
