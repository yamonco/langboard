from ....core.db import DbSession, SqlBuilder
from ....core.domain import BaseRepository
from ....core.types.ParamTypes import TUserParam
from ....domain.models import IdentityProvider, UserIdentityLink
from ....helpers import InfraHelper


class UserIdentityLinkRepository(BaseRepository[UserIdentityLink]):
    @staticmethod
    def model_cls():
        return UserIdentityLink

    @staticmethod
    def name() -> str:
        return "user_identity_link"

    def get_by_provider_external_id(
        self,
        provider: IdentityProvider,
        external_id: str,
        issuer: str | None = None,
    ) -> UserIdentityLink | None:
        """Resolve a provider subject, scoped to its issuer when supplied."""

        condition = (UserIdentityLink.column("provider") == provider) & (
            UserIdentityLink.column("external_id") == external_id
        )
        condition &= UserIdentityLink.column("issuer") == (issuer or "")
        with DbSession.use(readonly=True) as db:
            result = db.exec(SqlBuilder.select.table(UserIdentityLink).where(condition).limit(1))
            return result.first()

    def get_by_user_provider(self, user: TUserParam, provider: IdentityProvider) -> UserIdentityLink | None:
        user_id = InfraHelper.convert_id(user)
        with DbSession.use(readonly=True) as db:
            result = db.exec(
                SqlBuilder.select.table(UserIdentityLink)
                .where(
                    (UserIdentityLink.column("user_id") == user_id) & (UserIdentityLink.column("provider") == provider)
                )
                .limit(1)
            )
            return result.first()
