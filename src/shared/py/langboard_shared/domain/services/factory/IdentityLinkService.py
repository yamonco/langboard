from ....core.domain import BaseDomainService
from ....core.types.ParamTypes import TUserParam
from ....domain.models import IdentityProvider, User, UserIdentityLink
from ....helpers import InfraHelper


class IdentityLinkService(BaseDomainService):
    @staticmethod
    def name() -> str:
        """DO NOT EDIT THIS METHOD"""
        return "identity_link"

    def _to_provider_enum(self, provider: IdentityProvider | str) -> IdentityProvider | None:
        if isinstance(provider, IdentityProvider):
            return provider
        if provider in IdentityProvider.__members__:
            return IdentityProvider[provider]
        if provider in IdentityProvider._value2member_map_:
            return IdentityProvider(provider)
        return None

    def get_by_provider_external_id(
        self,
        provider: IdentityProvider | str,
        external_id: str,
        issuer: str | None = None,
    ) -> UserIdentityLink | None:
        provider_enum = self._to_provider_enum(provider)
        if provider_enum is None or not external_id:
            return None
        return self.repo.user_identity_link.get_by_provider_external_id(provider_enum, external_id, issuer)

    def get_by_user_provider(self, user: TUserParam, provider: IdentityProvider | str) -> UserIdentityLink | None:
        provider_enum = self._to_provider_enum(provider)
        if provider_enum is None:
            return None
        return self.repo.user_identity_link.get_by_user_provider(user, provider_enum)

    def get_user_by_provider_external_id(
        self,
        provider: IdentityProvider | str,
        external_id: str,
        issuer: str | None = None,
    ) -> User | None:
        link = self.get_by_provider_external_id(provider, external_id, issuer)
        if not link:
            return None
        return InfraHelper.get_by_id_like(User, link.user_id)

    def upsert_user_link(
        self,
        user: TUserParam,
        provider: IdentityProvider | str,
        external_id: str,
        issuer: str | None = None,
        email: str | None = None,
    ) -> UserIdentityLink:
        user_id = InfraHelper.convert_id(user)
        provider_enum = self._to_provider_enum(provider)
        if provider_enum is None:
            raise ValueError("Unsupported identity provider")

        current_link = self.get_by_user_provider(user_id, provider_enum)
        normalized_issuer = issuer.strip().rstrip("/") if issuer else ""
        external_link = self.get_by_provider_external_id(provider_enum, external_id, normalized_issuer)

        if external_link and current_link and external_link.id != current_link.id:
            # Keep a single record per user/provider pair.
            self.repo.user_identity_link.delete(current_link, purge=True)
            current_link = None

        target = external_link or current_link
        if not target:
            target = UserIdentityLink(user_id=user_id, provider=provider_enum, external_id=external_id)
            target.issuer = normalized_issuer
            target.email = email
            self.repo.user_identity_link.insert(target)
            return target

        target.user_id = user_id
        target.provider = provider_enum
        target.external_id = external_id
        target.issuer = normalized_issuer
        target.email = email
        self.repo.user_identity_link.update(target)
        return target
