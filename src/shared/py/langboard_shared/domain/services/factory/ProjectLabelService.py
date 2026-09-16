from typing import Any, Literal
from ....core.domain import BaseDomainService
from ....core.domain.BaseDomainService import TMutableValidatorMap
from ....core.types.ParamTypes import TCardParam, TProjectLabelParam, TProjectParam, TUserOrBot
from ....core.utils.Converter import convert_python_data
from ....helpers import InfraHelper
from ....publishers import ProjectLabelPublisher
from ....tasks.activities import ProjectLabelActivityTask
from ....tasks.bots import ProjectLabelBotTask
from ...models import Card, Project, ProjectLabel


class ProjectLabelService(BaseDomainService):
    @staticmethod
    def name() -> str:
        """DO NOT EDIT THIS METHOD"""
        return "project_label"

    def get_api_list_by_project(
        self,
        project: TProjectParam | None,
        where_in: list[TProjectLabelParam] | None = None,
    ) -> list[dict[str, Any]]:
        """Return project labels, optionally restricted to requested identities."""

        project = InfraHelper.get_by_id_like(Project, project)
        if not project:
            return []
        labels = self.repo.project_label.get_all_by_project(project, where_in=where_in)
        return [label.api_response() for label in labels]

    def get_api_list_by_card(self, card: TCardParam | None, limit: int | None = None) -> list[dict[str, Any]]:
        """Return card labels, optionally enforcing a repository row limit."""

        card = InfraHelper.get_by_id_like(Card, card)
        if not card:
            return []
        labels = self.repo.project_label.get_all_by_card(card, limit=limit)
        return [label.api_response() for label in labels]

    def create(
        self, user_or_bot: TUserOrBot, project: TProjectParam | None, name: str, color: str, description: str
    ) -> tuple[ProjectLabel, dict[str, Any]] | None:
        project = InfraHelper.get_by_id_like(Project, project)
        if not project:
            return None

        label = ProjectLabel(
            project_id=project.id,
            name=name,
            color=color,
            description=description,
            order=self.repo.project_label.get_next_order(project),
        )
        self.repo.project_label.insert(label)

        ProjectLabelPublisher.created(project, label)
        ProjectLabelActivityTask.project_label_created(user_or_bot, project, label)
        ProjectLabelBotTask.project_label_created(user_or_bot, project, label)

        return label, label.api_response()

    def update(
        self, user_or_bot: TUserOrBot, project: TProjectParam | None, label: TProjectLabelParam | None, form: dict
    ) -> dict[str, Any] | Literal[True] | None:
        params = InfraHelper.get_records_with_foreign_by_params((Project, project), (ProjectLabel, label))
        if not params:
            return None
        project, label = params

        validators: TMutableValidatorMap = {
            "name": "not_empty",
            "color": "not_empty",
            "description": "default",
        }

        old_record = self.apply_mutates(label, form, validators)
        if not old_record:
            return True

        self.repo.project_label.update(label)

        model: dict[str, Any] = {}
        for key in validators:
            if key not in form or key not in old_record:
                continue
            model[key] = convert_python_data(getattr(label, key))

        ProjectLabelPublisher.updated(project, label, model)
        ProjectLabelActivityTask.project_label_updated(user_or_bot, project, old_record, label)
        ProjectLabelBotTask.project_label_updated(user_or_bot, project, label)

        return model

    def change_order(self, project: TProjectParam, label: TProjectLabelParam, order: int) -> Literal[True] | None:
        params = InfraHelper.get_records_with_foreign_by_params((Project, project), (ProjectLabel, label))
        if not params:
            return None
        project, label = params

        old_order = label.order
        label.order = order
        self.repo.project_label.update_column_order(label, project, old_order, order)

        ProjectLabelPublisher.order_changed(project, label)

        return True

    def delete(self, user_or_bot: TUserOrBot, project: TProjectParam, label: TProjectLabelParam) -> bool | None:
        params = InfraHelper.get_records_with_foreign_by_params((Project, project), (ProjectLabel, label))
        if not params:
            return None
        project, label = params

        self.repo.project_label.delete(label)

        ProjectLabelPublisher.deleted(project, label)
        ProjectLabelActivityTask.project_label_deleted(user_or_bot, project, label)
        ProjectLabelBotTask.project_label_deleted(user_or_bot, project, label)

        return True
