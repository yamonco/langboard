from ....core.domain import BaseRepository
from ....domain.models import WorkflowStageDefinition


class WorkflowStageRepository(BaseRepository[WorkflowStageDefinition]):
    @staticmethod
    def model_cls():
        return WorkflowStageDefinition

    @staticmethod
    def name() -> str:
        return "workflow_stage"
