from enum import Enum
from typing import Any
from ...core.db import ApiField, BaseDbModel, EnumLikeType, Field, SnowflakeIDField
from ...core.types import SnowflakeID
from .User import User


class IdentityProvider(Enum):
    Oidc = "oidc"
    Scim = "scim"


class UserIdentityLink(BaseDbModel, table=True):
    user_id: SnowflakeID = SnowflakeIDField(
        foreign_key=User,
        nullable=False,
        index=True,
        unique_groups=("user_provider",),
        api_field=ApiField(name="user_uid"),
    )
    provider: IdentityProvider = Field(
        nullable=False,
        sa_type=EnumLikeType(IdentityProvider),
        index=True,
        unique_groups=("provider_issuer_external_id", "user_provider"),
        api_field=ApiField(),
    )
    external_id: str = Field(
        nullable=False,
        index=True,
        unique_groups=("provider_issuer_external_id",),
        api_field=ApiField(),
    )
    issuer: str = Field(
        default="",
        nullable=False,
        unique_groups=("provider_issuer_external_id",),
        api_field=ApiField(),
    )
    email: str | None = Field(default=None, nullable=True, api_field=ApiField())

    def notification_data(self) -> dict[str, Any]:
        return {}

    def _get_repr_keys(self) -> list[str | tuple[str, str]]:
        return ["user_id", "provider", "external_id", "issuer", "email"]
