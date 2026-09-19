import re
from typing import Any
from ....core.domain import BaseDomainService
from ....core.types import SafeDateTime
from ....core.types.ParamTypes import TUserParam
from ....helpers import InfraHelper
from ...models import Organization, User


_SLUG_PATTERN = re.compile(r"[^a-z0-9-]+")


def slugify(name: str) -> str:
    """Normalize an organization name into a unique-ready slug."""

    slug = _SLUG_PATTERN.sub("-", name.strip().lower()).strip("-")
    if not slug:
        raise ValueError("organization name must contain alphanumeric characters")
    return slug[:60]


class OrganizationService(BaseDomainService):
    @staticmethod
    def name() -> str:
        """DO NOT EDIT THIS METHOD"""
        return "organization"

    def get_by_id_like(self, organization: TUserParam | None) -> Organization | None:
        """Resolve one organization by model, id, or uid."""

        return InfraHelper.get_by_id_like(Organization, organization)

    def get_by_slug(self, slug: str) -> Organization | None:
        """Resolve one organization by slug."""

        return self.repo.organization.get_by_slug(slug)

    def get_api_list_by_owner(self, user: User) -> list[dict[str, Any]]:
        """List an owner's organizations as API payloads."""

        organizations = self.repo.organization.get_all_by_owner(user)
        return [organization.api_response() for organization in organizations]

    def create(self, user: User, name: str, *, slug: str | None = None) -> Organization:
        """Create an organization owned by the requesting user."""

        normalized_slug = slugify(slug or name)
        if self.repo.organization.get_by_slug(normalized_slug) is not None:
            raise ValueError(f"organization slug '{normalized_slug}' already exists")

        organization = Organization(
            name=name.strip(),
            slug=normalized_slug,
            owner_user_id=user.id,
            is_active=True,
        )
        self.repo.organization.insert(organization)
        return organization

    def set_active(self, user: User, organization: TUserParam | None, is_active: bool) -> Organization | None:
        """Suspend or reactivate an organization; owners only."""

        organization = InfraHelper.get_by_id_like(Organization, organization)
        if not organization or organization.owner_user_id != user.id:
            return None

        organization.is_active = is_active
        organization.suspended_at = None if is_active else SafeDateTime.now()
        self.repo.organization.update(organization)
        return organization

    def assign_project(self, user: User, organization: TUserParam | None, project) -> Organization:
        """Map a project into this organization; owners only."""

        from ...models import Project  # local import avoids model-registration ordering issues

        organization = InfraHelper.get_by_id_like(Organization, organization)
        project = InfraHelper.get_by_id_like(Project, project)
        if not organization or not project or organization.owner_user_id != user.id:
            raise ValueError("organization or project not found")

        project.organization_id = organization.id
        self.repo.project.update(project)
        return organization

    def unassign_project(self, user: User, organization: TUserParam | None, project) -> Organization | None:
        """Detach a project from its organization; owners only."""

        from ...models import Project

        organization = InfraHelper.get_by_id_like(Organization, organization)
        project = InfraHelper.get_by_id_like(Project, project)
        if not organization or not project or organization.owner_user_id != user.id:
            return None
        if project.organization_id != organization.id:
            return None

        project.organization_id = None
        self.repo.project.update(project)
        return organization

    def get_api_project_list(self, user: User, organization: TUserParam | None) -> list[dict[str, Any]]:
        """List an organization's projects as API payloads; owners only."""

        organization = InfraHelper.get_by_id_like(Organization, organization)
        if not organization or organization.owner_user_id != user.id:
            return []

        projects = self.repo.project.get_all_by_organization(organization.id)
        return [project.api_response() for project in projects]
