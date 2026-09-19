from ....core.db import DbSession, SqlBuilder
from ....core.domain import BaseRepository
from ....core.types.ParamTypes import TUserParam
from ....domain.models import Organization
from ....helpers import InfraHelper


class OrganizationRepository(BaseRepository[Organization]):
    @staticmethod
    def model_cls():
        return Organization

    @staticmethod
    def name() -> str:
        return "organization"

    def get_by_slug(self, slug: str) -> Organization | None:
        """Find one organization by its unique slug."""

        slug = slug.strip().lower()
        if not slug:
            return None
        with DbSession.use(readonly=True) as db:
            return (
                db.exec(
                    SqlBuilder.select.table(Organization).where(Organization.column("slug") == slug).limit(1)
                ).first()
            )

    def get_all_by_owner(self, user: TUserParam) -> list[Organization]:
        """List organizations owned by one user, newest first."""

        user_id = InfraHelper.convert_id(user)
        with DbSession.use(readonly=True) as db:
            return db.exec(
                SqlBuilder.select.table(Organization)
                .where(Organization.column("owner_user_id") == user_id)
                .order_by(Organization.column("id").desc())
            ).all()
