from sqlalchemy import func, select
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
