from ....core.domain import BaseRepository
from ....core.types.ParamTypes import TProjectParam
from ....domain.models import ProjectBotScope
from ....helpers import InfraHelper


class ProjectBotScopeRepository(BaseRepository[ProjectBotScope]):
    @staticmethod
    def model_cls():
        return ProjectBotScope

    @staticmethod
    def name() -> str:
        return "project_bot_scope"

    def get_all_by_project(self, project: TProjectParam) -> list[ProjectBotScope]:
        """Return all project-level bot trigger scopes."""

        return InfraHelper.get_all_by(ProjectBotScope, "project_id", InfraHelper.convert_id(project))
