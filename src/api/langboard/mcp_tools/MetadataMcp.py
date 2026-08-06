from langboard_shared.core.routing import SocketTopic
from langboard_shared.domain.models import (
    Bot,
    Card,
    CardMetadata,
    Project,
    ProjectRole,
    ProjectWiki,
    ProjectWikiMetadata,
    User,
)
from langboard_shared.domain.models.ProjectRole import ProjectRoleAction
from langboard_shared.domain.services.DomainService import DomainService
from langboard_shared.helpers import InfraHelper
from langboard_shared.publishers import MetadataPublisher
from langboard_shared.security import RoleFinder
from ..mcp_integration import McpRoleFilter, McpTool


@McpTool.add(description="Get card metadata.")
@McpRoleFilter.add(ProjectRole, [ProjectRoleAction.Read], RoleFinder.project)
def get_card_metadata(project_uid: str, card_uid: str, user_or_bot: User | Bot, service: DomainService) -> dict:
    params = InfraHelper.get_records_with_foreign_by_params((Project, project_uid), (Card, card_uid))
    if not params:
        raise ValueError("Project or card not found")

    _, card = params
    metadata = service.metadata.get_all_as_api(CardMetadata, card, as_dict=True)
    return {"metadata": metadata}


@McpTool.add(description="Get card metadata by key.")
@McpRoleFilter.add(ProjectRole, [ProjectRoleAction.Read], RoleFinder.project)
def get_card_metadata_by_key(
    project_uid: str, card_uid: str, key: str, user_or_bot: User | Bot, service: DomainService
) -> dict:
    params = InfraHelper.get_records_with_foreign_by_params((Project, project_uid), (Card, card_uid))
    if not params:
        raise ValueError("Project or card not found")

    _, card = params
    metadata = service.metadata.get_by_key_as_api(CardMetadata, card, key)
    value = metadata.get("value", None) if metadata else None
    return {key: value}


@McpTool.add(description="Save card metadata.")
@McpRoleFilter.add(ProjectRole, [ProjectRoleAction.CardUpdate], RoleFinder.project)
def save_card_metadata(
    project_uid: str,
    card_uid: str,
    key: str,
    value: str,
    old_key: str | None,
    user_or_bot: User | Bot,
    service: DomainService,
) -> dict:
    params = InfraHelper.get_records_with_foreign_by_params((Project, project_uid), (Card, card_uid))
    if not params:
        raise ValueError("Project or card not found")

    _, card = params
    metadata = service.metadata.save(CardMetadata, card, key, value, old_key)
    if metadata is None:
        raise ValueError("Failed to save metadata")

    MetadataPublisher.updated_metadata(SocketTopic.BoardCard, card.get_uid(), key, value, old_key)
    return {"message": "Metadata saved successfully"}


@McpTool.add(description="Delete card metadata.")
@McpRoleFilter.add(ProjectRole, [ProjectRoleAction.CardUpdate], RoleFinder.project)
def delete_card_metadata(
    project_uid: str, card_uid: str, keys: list[str], user_or_bot: User | Bot, service: DomainService
) -> dict:
    params = InfraHelper.get_records_with_foreign_by_params((Project, project_uid), (Card, card_uid))
    if not params:
        raise ValueError("Project or card not found")

    _, card = params
    service.metadata.delete(CardMetadata, card, keys)
    MetadataPublisher.deleted_metadata(SocketTopic.BoardCard, card.get_uid(), keys)
    return {"message": "Metadata deleted successfully"}


@McpTool.add(description="Get wiki metadata.")
@McpRoleFilter.add(ProjectRole, [ProjectRoleAction.Read], RoleFinder.project)
def get_wiki_metadata(project_uid: str, wiki_uid: str, user_or_bot: User | Bot, service: DomainService) -> dict:
    params = InfraHelper.get_records_with_foreign_by_params((Project, project_uid), (ProjectWiki, wiki_uid))
    if not params:
        raise ValueError("Project or wiki not found")

    _, wiki = params

    if isinstance(user_or_bot, User) and not service.project_wiki.is_assigned(user_or_bot, wiki):
        raise ValueError("User not assigned to wiki")

    metadata = service.metadata.get_all_as_api(ProjectWikiMetadata, wiki, as_dict=True)
    return {"metadata": metadata}


@McpTool.add(description="Get wiki metadata by key.")
@McpRoleFilter.add(ProjectRole, [ProjectRoleAction.Read], RoleFinder.project)
def get_wiki_metadata_by_key(
    project_uid: str, wiki_uid: str, key: str, user_or_bot: User | Bot, service: DomainService
) -> dict:
    params = InfraHelper.get_records_with_foreign_by_params((Project, project_uid), (ProjectWiki, wiki_uid))
    if not params:
        raise ValueError("Project or wiki not found")

    _, wiki = params

    if isinstance(user_or_bot, User) and not service.project_wiki.is_assigned(user_or_bot, wiki):
        raise ValueError("User not assigned to wiki")

    metadata = service.metadata.get_by_key_as_api(ProjectWikiMetadata, wiki, key)
    value = metadata.get("value", None) if metadata else None
    return {key: value}


@McpTool.add(description="Save wiki metadata.")
@McpRoleFilter.add(ProjectRole, [ProjectRoleAction.Update], RoleFinder.project)
def save_wiki_metadata(
    project_uid: str,
    wiki_uid: str,
    key: str,
    value: str,
    old_key: str | None,
    user_or_bot: User | Bot,
    service: DomainService,
) -> dict:
    params = InfraHelper.get_records_with_foreign_by_params((Project, project_uid), (ProjectWiki, wiki_uid))
    if not params:
        raise ValueError("Project or wiki not found")

    _, wiki = params

    if isinstance(user_or_bot, User) and not service.project_wiki.is_assigned(user_or_bot, wiki):
        raise ValueError("User not assigned to wiki")

    metadata = service.metadata.save(ProjectWikiMetadata, wiki, key, value, old_key)
    if metadata is None:
        raise ValueError("Failed to save metadata")

    MetadataPublisher.updated_metadata(SocketTopic.BoardWikiPrivate, wiki.get_uid(), key, value, old_key)
    return {"message": "Metadata saved successfully"}


@McpTool.add(description="Delete wiki metadata.")
@McpRoleFilter.add(ProjectRole, [ProjectRoleAction.Update], RoleFinder.project)
def delete_wiki_metadata(
    project_uid: str, wiki_uid: str, keys: list[str], user_or_bot: User | Bot, service: DomainService
) -> dict:
    params = InfraHelper.get_records_with_foreign_by_params((Project, project_uid), (ProjectWiki, wiki_uid))
    if not params:
        raise ValueError("Project or wiki not found")

    _, wiki = params

    if isinstance(user_or_bot, User) and not service.project_wiki.is_assigned(user_or_bot, wiki):
        raise ValueError("User not assigned to wiki")

    service.metadata.delete(ProjectWikiMetadata, wiki, keys)
    MetadataPublisher.deleted_metadata(SocketTopic.BoardWikiPrivate, wiki.get_uid(), keys)
    return {"message": "Metadata deleted successfully"}
