from sqlalchemy import update
from ....core.db import DbSession, SqlBuilder
from ....core.domain import BaseOrderRepository
from ....core.types import SafeDateTime, SnowflakeID
from ....core.types.ParamTypes import TProjectParam, TWikiParam
from ....domain.models import Project, ProjectWiki
from ....helpers import InfraHelper


class ProjectWikiRepository(BaseOrderRepository[ProjectWiki, Project]):
    @staticmethod
    def parent_model_cls():
        return Project

    @staticmethod
    def model_cls():
        return ProjectWiki

    @staticmethod
    def name() -> str:
        return "project_wiki"

    def get_by_id_like(self, wiki: TWikiParam | None) -> ProjectWiki | None:
        return InfraHelper.get_by_id_like(ProjectWiki, wiki)

    def update_content_if_current(self, wiki: ProjectWiki, expected_content: str) -> bool:
        """Lock the live row and persist only content if its reviewed value still matches."""
        with DbSession.use(readonly=False) as db:
            current = db.exec(
                SqlBuilder.select.table(ProjectWiki)
                .where((ProjectWiki.column("id") == wiki.id) & (ProjectWiki.column("project_id") == wiki.project_id))
                .with_for_update()
            ).first()
            if current is None or current.content.content != expected_content:
                return False
            updated_at = SafeDateTime.now()
            changed = db.exec(
                update(ProjectWiki.__table__)
                .where(ProjectWiki.column("id") == wiki.id)
                .values(content=wiki.content, updated_at=updated_at)
            )
            if changed != 1:
                return False
        wiki.updated_at = updated_at
        wiki.clear_changes()
        return True

    def get_all_by_project(self, project: TProjectParam):
        project_id = InfraHelper.convert_id(project)
        wikis = []
        with DbSession.use(readonly=True) as db:
            result = db.exec(
                SqlBuilder.select.table(ProjectWiki)
                .where(ProjectWiki.column("project_id") == project_id)
                .order_by(ProjectWiki.column("order").asc())
            )
            wikis = result.all()
        return wikis

    def get_by_project_and_uids(self, project: TProjectParam, wiki_uids: set[str]) -> list[ProjectWiki]:
        if not wiki_uids:
            return []
        project_id = InfraHelper.convert_id(project)
        wiki_ids = [InfraHelper.convert_id(wiki_uid) for wiki_uid in wiki_uids]
        with DbSession.use(readonly=True) as db:
            return db.exec(
                SqlBuilder.select.table(ProjectWiki)
                .where(ProjectWiki.column("project_id") == project_id)
                .where(ProjectWiki.column("id").in_(wiki_ids))
            ).all()

    def get_headers_by_project_and_uids(
        self, project: TProjectParam, wiki_uids: set[str]
    ) -> list[tuple[SnowflakeID, str, bool]]:
        """Project only the fields needed by the board, never the Wiki body."""

        if not wiki_uids:
            return []
        project_id = InfraHelper.convert_id(project)
        wiki_ids = [InfraHelper.convert_id(wiki_uid) for wiki_uid in wiki_uids]
        with DbSession.use(readonly=True) as db:
            rows = db.exec(
                SqlBuilder.select.columns(ProjectWiki.id, ProjectWiki.title, ProjectWiki.is_public)
                .where(ProjectWiki.column("project_id") == project_id)
                .where(ProjectWiki.column("id").in_(wiki_ids))
            ).all()
            return [(SnowflakeID(row[0]), row[1], row[2]) for row in rows]
