from typing import Any
from langboard_shared.core.routing import BaseFormModel, form_model
from pydantic import BaseModel, ConfigDict, Field


class ScimUsersPagination(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    start_index: int = Field(default=1, alias="startIndex")
    count: int = 100
    filter: str | None = None


class ScimGroupsPagination(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    start_index: int = Field(default=1, alias="startIndex")
    count: int = 100
    filter: str | None = None


class ScimName(BaseModel):
    givenName: str | None = None
    familyName: str | None = None


class ScimEmail(BaseModel):
    value: str
    primary: bool | None = None


class ScimGroupMember(BaseModel):
    value: str
    display: str | None = None


@form_model
class ScimUserUpsertForm(BaseFormModel):
    model_config = ConfigDict(extra="allow")

    schemas: list[str] | None = None
    externalId: str | None = None
    userName: str | None = None
    active: bool | None = None
    name: ScimName | None = None
    emails: list[ScimEmail] | None = None


@form_model
class ScimGroupUpsertForm(BaseFormModel):
    model_config = ConfigDict(extra="allow")

    schemas: list[str] | None = None
    externalId: str | None = None
    displayName: str | None = None
    members: list[ScimGroupMember] | None = None


class ScimPatchOperation(BaseModel):
    model_config = ConfigDict(extra="allow")

    op: str
    path: str | None = None
    value: Any | None = None


@form_model
class ScimPatchForm(BaseFormModel):
    model_config = ConfigDict(extra="allow")

    schemas: list[str] | None = None
    Operations: list[ScimPatchOperation] = Field(default_factory=list)
