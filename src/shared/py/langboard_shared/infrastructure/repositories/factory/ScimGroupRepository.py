from ....core.db import DbSession, SqlBuilder
from ....core.domain import BaseRepository
from ....domain.models import ScimGroup


class ScimGroupRepository(BaseRepository[ScimGroup]):
    @staticmethod
    def model_cls():
        return ScimGroup

    @staticmethod
    def name() -> str:
        return "scim_group"

    def count_all(self) -> int:
        with DbSession.use(readonly=True) as db:
            return db.exec(SqlBuilder.select.count(ScimGroup, ScimGroup.column("id"))).first() or 0

    def get_page(self, offset: int, limit: int) -> list[ScimGroup]:
        with DbSession.use(readonly=True) as db:
            return db.exec(
                SqlBuilder.select.table(ScimGroup)
                .order_by(ScimGroup.column("created_at").asc(), ScimGroup.column("id").asc())
                .offset(offset)
                .limit(limit)
            ).all()

    def get_all(self) -> list[ScimGroup]:
        with DbSession.use(readonly=True) as db:
            return db.exec(
                SqlBuilder.select.table(ScimGroup).order_by(
                    ScimGroup.column("created_at").asc(), ScimGroup.column("id").asc()
                )
            ).all()

    def get_by_external_id(self, external_id: str, *, consistent: bool = False) -> ScimGroup | None:
        if not external_id:
            return None

        with DbSession.use(readonly=not consistent) as db:
            return db.exec(
                SqlBuilder.select.table(ScimGroup).where(ScimGroup.column("external_id") == external_id).limit(1)
            ).first()

    def get_by_display_name(self, display_name: str) -> ScimGroup | None:
        if not display_name:
            return None

        with DbSession.use(readonly=True) as db:
            return db.exec(
                SqlBuilder.select.table(ScimGroup).where(ScimGroup.column("display_name") == display_name).limit(1)
            ).first()
