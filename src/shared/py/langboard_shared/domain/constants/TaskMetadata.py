TASK_METADATA_KEYS = {
    "source": "task.source",
    "source_url": "task.source_url",
    "external_id": "task.external_id",
    "type": "task.type",
    "assigned_agent": "task.assigned_agent",
    "assigned_bot_uid": "task.assigned_bot_uid",
    "acceptance_criteria": "task.acceptance_criteria",
    "risk_level": "task.risk_level",
    "related_files": "task.related_files",
    "pr_url": "task.pr_url",
}

SYSTEM_TASK_METADATA_KEYS = {
    "verification": "__system.task.verification",
    "failure": "__system.task.failure",
    "run": "__system.task.run",
    "suggestions": "__system.task.suggestions",
    "bypass": "__system.task.bypass",
}

TODO_COLUMN_NAME = "Todo"
IN_PROGRESS_COLUMN_NAME = "In Progress"
CHECKING_COLUMN_NAME = "Checking"
FAILED_COLUMN_NAME = "Failed"
FEEDBACK_COLUMN_NAME = "Feedback"
AUTO_FIX_COLUMN_NAME = "Auto Fix"
AI_REVIEW_COLUMN_NAME = "AI Review"
READY_TO_MERGE_COLUMN_NAME = "Ready to Merge"
DONE_COLUMN_NAME = "Done"

WORKFLOW_COLUMN_NAMES = [
    TODO_COLUMN_NAME,
    IN_PROGRESS_COLUMN_NAME,
    CHECKING_COLUMN_NAME,
    FAILED_COLUMN_NAME,
    FEEDBACK_COLUMN_NAME,
    AUTO_FIX_COLUMN_NAME,
    AI_REVIEW_COLUMN_NAME,
    READY_TO_MERGE_COLUMN_NAME,
    DONE_COLUMN_NAME,
]

TASK_RELATIONSHIP_PARENT_NAME = "Parent Task"
TASK_RELATIONSHIP_CHILD_NAME = "Child Task"
TASK_RELATIONSHIP_DESCRIPTION = "Links orchestration parent tasks to AI-generated child tasks."

ORCHESTRATION_AI_GENERATED_SOURCE = "ai_generated"

BYPASS_APPROVAL_ACTION_TYPES = {
    "auth",
    "authentication",
    "authorization",
    "billing",
    "payment",
    "permission",
    "permissions",
    "db_schema",
    "database_schema",
    "migration",
    "external_api",
    "large_file_structure",
}
