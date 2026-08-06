from typing import Sequence
from ....core.db import DbSession, SqlBuilder
from ....core.domain import BaseOrderRepository
from ....core.types.ParamTypes import TBaseParam, TCardParam, TProjectLabelParam, TProjectParam
from ....domain.models import CardAssignedProjectLabel, Project, ProjectLabel
from ....helpers import InfraHelper


class ProjectLabelRepository(BaseOrderRepository[ProjectLabel, Project]):
    @staticmethod
    def parent_model_cls():
        return Project

    @staticmethod
    def model_cls():
        return ProjectLabel

    @staticmethod
    def name() -> str:
        return "project_label"

    def get_all_by_project(
        self, project: TProjectParam, where_in: Sequence[TProjectLabelParam] | None = None
    ) -> list[ProjectLabel]:
        project_id = InfraHelper.convert_id(project)
        labels = []
        query = (
            SqlBuilder.select.table(ProjectLabel)
            .where(ProjectLabel.column("project_id") == project_id)
            .order_by(ProjectLabel.column("order").asc())
        )

        if where_in is not None:
            if not isinstance(where_in, Sequence) or isinstance(where_in, str):
                where_in = [where_in]
            label_ids = [InfraHelper.convert_id(label) for label in where_in]
            query = query.where(ProjectLabel.column("id").in_(label_ids))

        with DbSession.use(readonly=True) as db:
            result = db.exec(query)
            labels = result.all()
        return labels

    def get_all_by_card(
        self,
        card: TCardParam,
        where_in: list[TBaseParam] | None = None,
        limit: int | None = None,
    ) -> list[ProjectLabel]:
        """Return card labels, optionally enforcing a database row limit."""

        card_id = InfraHelper.convert_id(card)
        labels = []
        query = (
            SqlBuilder.select.table(ProjectLabel)
            .join(
                CardAssignedProjectLabel,
                ProjectLabel.column("id") == CardAssignedProjectLabel.column("project_label_id"),
            )
            .where(CardAssignedProjectLabel.column("card_id") == card_id)
        )

        if where_in is not None:
            label_ids = [InfraHelper.convert_id(label) for label in where_in]
            query = query.where(ProjectLabel.column("id").in_(label_ids))
        query = query.order_by(ProjectLabel.column("order").asc(), ProjectLabel.column("id").asc())
        if limit is not None:
            query = query.limit(limit)

        with DbSession.use(readonly=True) as db:
            result = db.exec(query)
            labels = result.all()
        return labels

    def get_all_card_labels_by_project(
        self, project: TProjectParam
    ) -> list[tuple[ProjectLabel, CardAssignedProjectLabel]]:
        project_id = InfraHelper.convert_id(project)

        labels = []
        with DbSession.use(readonly=True) as db:
            result = db.exec(
                SqlBuilder.select.tables(ProjectLabel, CardAssignedProjectLabel)
                .join(
                    CardAssignedProjectLabel,
                    ProjectLabel.column("id") == CardAssignedProjectLabel.column("project_label_id"),
                )
                .where(ProjectLabel.column("project_id") == project_id)
            )
            labels = result.all()
        return labels

    def init_defaults(self, project: TProjectParam) -> list[ProjectLabel]:
        project_id = InfraHelper.convert_id(project)

        labels: list[ProjectLabel] = []
        for default_label in ProjectLabel.DEFAULT_LABELS:
            label = ProjectLabel(
                project_id=project_id,
                name=default_label["name"],
                color=default_label["color"],
                description=default_label["description"],
                order=len(labels),
            )
            labels.append(label)
            with DbSession.use(readonly=False) as db:
                db.insert(label)

        return labels
