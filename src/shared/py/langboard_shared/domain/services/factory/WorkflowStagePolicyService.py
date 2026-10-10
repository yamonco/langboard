from ....core.db import DbSession, SqlBuilder
from ....core.domain import BaseDomainService
from ...models import Card, Project, ProjectColumn, WorkflowStageDefinition
from .CheckitemService import CheckitemService


class WorkflowStagePolicyService(BaseDomainService):
    @staticmethod
    def name() -> str:
        return "workflow_stage_policy"

    def apply_transition(
        self, actor, project: Project, card: Card, old_column: ProjectColumn, new_column: ProjectColumn | None
    ) -> dict[str, int]:
        empty = {"completed": 0, "stopped": 0}
        if (
            new_column is None
            or new_column.is_archive
            or card.is_linked_resource
            or not new_column.workflow_stage
            or old_column.workflow_stage == new_column.workflow_stage
        ):
            return empty
        with DbSession.atomic() as db:
            stage = db.exec(
                SqlBuilder.select.table(WorkflowStageDefinition).where(
                    WorkflowStageDefinition.column("key") == new_column.workflow_stage
                )
            ).first()
            if stage is None:
                raise ValueError("Workflow stage definition is missing")
            # Inactive definitions keep existing bindings and their meaning.
            effects = set(stage.entry_effects)
            if effects - {"complete_checkitems", "stop_running_timers"}:
                raise ValueError("Unsupported native workflow effect")
            if not effects:
                return empty
            return self._get_service(CheckitemService).complete_unchecked_by_card(
                actor,
                project,
                card,
                complete="complete_checkitems" in effects,
            )
