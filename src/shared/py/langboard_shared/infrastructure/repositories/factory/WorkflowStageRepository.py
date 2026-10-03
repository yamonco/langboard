from sqlalchemy import func, select, text
from ....core.db import DbSession, SqlBuilder
from ....core.domain import BaseRepository
from ....domain.models import ProjectColumn, WorkflowStageDefinition


class WorkflowStageRepository(BaseRepository[WorkflowStageDefinition]):
    @staticmethod
    def model_cls():
        return WorkflowStageDefinition

    @staticmethod
    def name() -> str:
        return "workflow_stage"

    def get_column_usage(self) -> dict[str, int]:
        query = (
            select(ProjectColumn.column("workflow_stage"), func.count(ProjectColumn.column("id")))
            .where(ProjectColumn.column("deleted_at") == None)  # noqa: E711
            .where(ProjectColumn.column("is_archive") == False)  # noqa: E712
            .group_by(ProjectColumn.column("workflow_stage"))
        )
        with DbSession.use(readonly=True) as db:
            return {key: count for key, count in db.exec(query).all() if key is not None}

    def get_by_keys(self, keys: set[str]) -> dict[str, WorkflowStageDefinition]:
        if not keys:
            return {}
        with DbSession.use(readonly=True) as db:
            return {
                stage.key: stage
                for stage in db.exec(
                    SqlBuilder.select.table(WorkflowStageDefinition).where(
                        WorkflowStageDefinition.column("key").in_(keys)
                    )
                ).all()
            }

    def get_policy_affected_cards(self, key: str) -> list[tuple[int, int]]:
        """Find bound cards and direct dependents without crossing project boundaries."""
        with DbSession.use(readonly=False) as db:
            return db.exec(
                select(text("affected.project_id"), text("affected.id")).select_from(text("""
                (SELECT DISTINCT c.project_id, c.id FROM card c
                WHERE c.deleted_at IS NULL AND c.id IN (
                    SELECT parent.id FROM card parent
                    JOIN project_column col ON col.id = parent.project_column_id
                    WHERE col.workflow_stage = :key AND col.project_id = parent.project_id
                      AND parent.deleted_at IS NULL AND col.deleted_at IS NULL
                    UNION
                    SELECT child.id FROM card_relationship r
                    JOIN card parent ON parent.id = r.card_id_parent
                    JOIN project_column col ON col.id = parent.project_column_id
                    JOIN card child ON child.id = r.card_id_child
                    WHERE col.workflow_stage = :key AND col.project_id = parent.project_id
                      AND parent.deleted_at IS NULL AND col.deleted_at IS NULL
                      AND child.project_id = parent.project_id
                )
                ) affected
            """)),
                params={"key": key},
            ).all()
