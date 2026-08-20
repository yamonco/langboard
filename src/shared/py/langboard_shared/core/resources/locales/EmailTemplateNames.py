from typing import Literal


TEmailTemplateName = Literal[
    "recovery",
    "signup",
    "subemail",
    "project_invitation",
    # Notification
    "mentioned_in_card",
    "mentioned_in_comment",
    "mentioned_in_wiki",
    "assigned_to_card",
    "reacted_to_comment",
    "notified_from_checklist",
    "project_activity_updated",
]
