from ....core.db import DbSession, SqlBuilder
from ....core.domain import BaseRepository
from ....domain.models import ProjectTemplate


class ProjectTemplateRepository(BaseRepository[ProjectTemplate]):
    """Persist and resolve project templates."""

    @staticmethod
    def model_cls():
        return ProjectTemplate

    @staticmethod
    def name() -> str:
        return "project_template"

    def get_all(self) -> list[ProjectTemplate]:
        with DbSession.use(readonly=True) as db:
            return list(db.exec(SqlBuilder.select.table(ProjectTemplate).order_by(ProjectTemplate.name)).all())

    def get_by_name(self, name: str) -> ProjectTemplate | None:
        with DbSession.use(readonly=True) as db:
            return db.exec(
                SqlBuilder.select.table(ProjectTemplate).where(ProjectTemplate.column("name") == name.strip()).limit(1)
            ).first()

    def get_default(self) -> ProjectTemplate | None:
        with DbSession.use(readonly=True) as db:
            return db.exec(
                SqlBuilder.select.table(ProjectTemplate)
                .where(ProjectTemplate.column("is_default") == True)  # noqa: E712
                .limit(1)
            ).first()

    def replace_default(self, template: ProjectTemplate) -> None:
        with DbSession.use(readonly=False) as db:
            db.exec(SqlBuilder.update.table(ProjectTemplate).values({ProjectTemplate.column("is_default"): False}))
            db.exec(
                SqlBuilder.update.table(ProjectTemplate)
                .values({ProjectTemplate.column("is_default"): True})
                .where(ProjectTemplate.column("id") == template.id)
            )
