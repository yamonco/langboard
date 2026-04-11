from re import IGNORECASE, search
from typing import Any
from ....core.db import DbSession, SqlBuilder
from ....core.domain import BaseDomainService
from ....core.routing import ApiErrorCode, ApiException
from ....core.types import SafeDateTime
from ....core.utils.String import generate_random_string
from ....Env import Env
from ....helpers import InfraHelper
from ....security import Auth
from ...models import IdentityProvider, Project, ProjectAssignedUser, ProjectRole, User
from ...models.ProjectRole import ProjectRoleAction
from .IdentityLinkService import IdentityLinkService
from .UserService import UserService


class ScimProvisioningService(BaseDomainService):
    @staticmethod
    def name() -> str:
        """DO NOT EDIT THIS METHOD"""
        return "scim_provisioning"

    @property
    def SCIM_USER_SCHEMA(self) -> str:
        return "urn:ietf:params:scim:schemas:core:2.0:User"

    @property
    def SCIM_LIST_SCHEMA(self) -> str:
        return "urn:ietf:params:scim:api:messages:2.0:ListResponse"

    @property
    def SCIM_GROUP_SCHEMA(self) -> str:
        return "urn:ietf:params:scim:schemas:core:2.0:Group"

    def resolve_user(self, identifier: str) -> User | None:
        identity_link = self._get_service(IdentityLinkService)
        user = identity_link.get_user_by_provider_external_id(IdentityProvider.Scim, identifier)
        if user:
            return user

        user_service = self._get_service(UserService)
        return user_service.get_by_id_like(identifier)

    def build_scim_user(self, user: User) -> dict[str, Any]:
        identity_link = self._get_service(IdentityLinkService)
        link = identity_link.get_by_user_provider(user, IdentityProvider.Scim)
        external_id = link.external_id if link else user.get_uid()

        return {
            "schemas": [self.SCIM_USER_SCHEMA],
            "id": user.get_uid(),
            "externalId": external_id,
            "userName": user.email,
            "name": {
                "givenName": user.firstname,
                "familyName": user.lastname,
            },
            "displayName": user.get_fullname(),
            "active": bool(user.activated_at),
            "emails": [{"value": user.email, "primary": True}],
            "meta": {
                "resourceType": "User",
                "created": user.created_at,
                "lastModified": user.updated_at,
            },
        }

    def resolve_group(self, identifier: str) -> dict[str, Any] | None:
        parsed = self._parse_project_role_group_identifier(identifier)
        if not parsed:
            return None
        project, role_key = parsed
        return self._build_project_role_group(project, role_key)

    def build_scim_group(self, group: dict[str, Any]) -> dict[str, Any]:
        return {
            "schemas": [self.SCIM_GROUP_SCHEMA],
            "id": str(group.get("id") or "").strip(),
            "externalId": str(group.get("externalId") or "").strip(),
            "displayName": str(group.get("displayName") or "").strip(),
            "members": list(group.get("members") or []),
            "meta": {
                "resourceType": "Group",
                "created": group.get("createdAt"),
                "lastModified": group.get("updatedAt"),
            },
        }

    def list_groups(self, start_index: int, count: int, filter_value: str | None) -> dict[str, Any]:
        normalized_start = self._coerce_int(start_index, default=1, min_value=1, max_value=100000)
        normalized_count = self._coerce_int(count, default=100, min_value=1, max_value=200)
        display_name_filter = self._parse_scim_group_filter(filter_value)
        groups = self._list_project_role_groups()
        if display_name_filter:
            lowered = display_name_filter.lower()
            groups = [
                group
                for group in groups
                if lowered in str(group.get("displayName") or "").lower()
                or lowered == str(group.get("externalId") or "").lower()
                or lowered == str(group.get("id") or "").lower()
            ]
        total = len(groups)
        slice_start = max(normalized_start - 1, 0)
        resources = [self.build_scim_group(group) for group in groups[slice_start : slice_start + normalized_count]]
        return self._build_list_response(resources, normalized_start, normalized_count, total)

    def create_or_upsert_group(self, payload: dict[str, Any]) -> dict[str, Any]:
        group = self._resolve_project_role_group_payload(payload)
        member_ids = self._extract_group_member_ids(payload)
        if member_ids:
            self._replace_project_role_group_members(group["project"], group["roleKey"], member_ids)
        return self._build_project_role_group(group["project"], group["roleKey"])

    def replace_group(self, identifier: str, payload: dict[str, Any]) -> dict[str, Any]:
        group = self._resolve_group_or_raise(identifier)
        member_ids = self._extract_group_member_ids(payload)
        self._replace_project_role_group_members(group["project"], group["roleKey"], member_ids)
        return self._build_project_role_group(group["project"], group["roleKey"])

    def patch_group(self, identifier: str, operations: list[dict[str, Any]]) -> dict[str, Any]:
        group = self._resolve_group_or_raise(identifier)
        for operation in operations:
            op = str(operation.get("op", "")).strip().lower()
            path = str(operation.get("path", "")).strip().lower()
            value = operation.get("value")
            if op not in {"add", "replace", "remove"}:
                continue
            if path in {"", "members"}:
                member_ids = self._extract_group_member_ids({"members": value if isinstance(value, list) else []})
                if op == "replace":
                    self._replace_project_role_group_members(group["project"], group["roleKey"], member_ids)
                elif op == "add":
                    for member_id in member_ids:
                        self._add_project_role_member(group["project"], group["roleKey"], member_id)
                elif op == "remove":
                    existing = [member["value"] for member in group["members"]]
                    for member_id in existing:
                        self._remove_project_role_member(group["project"], group["roleKey"], member_id)
            elif path.startswith("members[value eq "):
                member_id = self._parse_member_value_filter(path)
                if not member_id:
                    continue
                if op == "remove":
                    self._remove_project_role_member(group["project"], group["roleKey"], member_id)
                elif op in {"add", "replace"}:
                    self._add_project_role_member(group["project"], group["roleKey"], member_id)
        return self._build_project_role_group(group["project"], group["roleKey"])

    def delete_group(self, identifier: str) -> None:
        group = self._resolve_group_or_raise(identifier)
        member_ids = [member["value"] for member in group["members"]]
        for member_id in member_ids:
            self._remove_project_role_member(group["project"], group["roleKey"], member_id)

    def list_users(self, start_index: int, count: int, filter_value: str | None) -> dict[str, Any]:
        normalized_start = self._coerce_int(start_index, default=1, min_value=1, max_value=100000)
        normalized_count = self._coerce_int(count, default=100, min_value=1, max_value=200)
        user_name_filter = self._parse_scim_filter(filter_value)
        user_service = self._get_service(UserService)

        if user_name_filter:
            user, _ = user_service.get_by_email(user_name_filter)
            resources = [self.build_scim_user(user)] if user else []
            return self._build_list_response(resources, 1, len(resources), len(resources))

        with DbSession.use(readonly=True) as db:
            total = (
                db.exec(
                    SqlBuilder.select.count(User, User.column("id")).where(User.column("deleted_at") == None)  # noqa
                ).first()
                or 0
            )

            users = db.exec(
                SqlBuilder.select.table(User)
                .where(User.column("deleted_at") == None)  # noqa
                .order_by(User.column("created_at").asc(), User.column("id").asc())
                .offset(normalized_start - 1)
                .limit(normalized_count)
            ).all()

        resources = [self.build_scim_user(user) for user in users]
        return self._build_list_response(resources, normalized_start, normalized_count, int(total))

    def create_or_upsert_user(self, payload: dict[str, Any]) -> User:
        email = self._extract_email(payload)
        user_service = self._get_service(UserService)
        user, _ = user_service.get_by_email(email) if email else (None, None)

        if user:
            self.apply_user_mutations(user, payload)
            return user

        return self.create_user(payload)

    def create_user(self, payload: dict[str, Any]) -> User:
        email = self._extract_email(payload)
        if not email:
            raise ApiException.BadRequest_400(ApiErrorCode.VA0000)

        firstname, lastname = self._extract_names(payload)
        firstname = firstname or "SCIM"
        lastname = lastname or "User"

        now = SafeDateTime.now()
        active = payload.get("active")
        should_activate = bool(active) if isinstance(active, bool) else True

        form = {
            "firstname": firstname,
            "lastname": lastname,
            "email": email,
            "password": generate_random_string(48),
            "industry": "SCIM",
            "purpose": "Provisioning",
            "affiliation": None,
            "position": None,
        }
        if should_activate:
            form["created_at"] = now
            form["updated_at"] = now
            form["activated_at"] = now

        user_service = self._get_service(UserService)
        user, _ = user_service.create(form)
        self._upsert_identity_link(user, payload.get("externalId"), email)
        return user

    def apply_user_mutations(self, user: User, payload: dict[str, Any]) -> None:
        firstname, lastname = self._extract_names(payload)
        email = self._extract_email(payload)
        active = payload.get("active")

        update_form: dict[str, Any] = {}
        if firstname is not None and firstname != "" and firstname != user.firstname:
            update_form["firstname"] = firstname
        if lastname is not None and lastname != "" and lastname != user.lastname:
            update_form["lastname"] = lastname
        if update_form:
            self._get_service(UserService).update(user, update_form)

        if isinstance(active, bool):
            user_service = self._get_service(UserService)
            if active and not user.activated_at:
                user_service.activate(user)
            elif not active and user.activated_at:
                user_service.update(user, {"activated_at": None}, from_setting=True)

        if email and email != user.email:
            existing, _ = self._get_service(UserService).get_by_email(email)
            if existing and existing.id != user.id:
                raise ApiException.Conflict_409(ApiErrorCode.EX1003)

            user.email = email
            self.repo.user.update(user)
            Auth.reset_user(user)

        self._upsert_identity_link(user, payload.get("externalId"), user.email)

    def deactivate_user(self, user: User) -> None:
        if user.activated_at:
            self._get_service(UserService).update(user, {"activated_at": None}, from_setting=True)

    def normalize_patch_payload(self, operations: list[dict[str, Any]]) -> dict[str, Any]:
        payload: dict[str, Any] = {}
        for operation in operations:
            op = str(operation.get("op", "")).strip().lower()
            path = str(operation.get("path", "")).strip()
            path_lower = path.lower()
            value = operation.get("value")

            if op not in {"add", "replace", "remove"}:
                continue

            if not path and isinstance(value, dict):
                payload.update(value)
                continue

            if path_lower == "active":
                payload["active"] = False if op == "remove" else bool(value)
                continue

            if path_lower in {"username", "emails.value"}:
                if op != "remove" and value is not None:
                    payload["userName"] = str(value)
                continue

            if path_lower == "name.givenname":
                payload.setdefault("name", {})
                if op != "remove" and value is not None:
                    payload["name"]["givenName"] = str(value)
                continue

            if path_lower == "name.familyname":
                payload.setdefault("name", {})
                if op != "remove" and value is not None:
                    payload["name"]["familyName"] = str(value)
                continue

            if path_lower == "externalid":
                if op != "remove" and value is not None:
                    payload["externalId"] = str(value)
                continue

        return payload

    def _upsert_identity_link(self, user: User, external_id: Any, email: str | None) -> None:
        external_id_str = str(external_id).strip() if external_id else ""
        if not external_id_str:
            return

        self._get_service(IdentityLinkService).upsert_user_link(
            user=user,
            provider=IdentityProvider.Scim,
            external_id=external_id_str,
            issuer=Env.SCIM_ISSUER or None,
            email=email,
        )

    def _extract_email(self, payload: dict[str, Any]) -> str:
        emails = payload.get("emails")
        if isinstance(emails, list):
            for item in emails:
                if not isinstance(item, dict):
                    continue
                value = item.get("value")
                if value:
                    return str(value).strip().lower()

        user_name = payload.get("userName", "")
        return str(user_name).strip().lower()

    def _extract_names(self, payload: dict[str, Any]) -> tuple[str | None, str | None]:
        name = payload.get("name", {})
        if not isinstance(name, dict):
            name = {}

        firstname = name.get("givenName")
        lastname = name.get("familyName")

        firstname = str(firstname).strip() if firstname is not None else None
        lastname = str(lastname).strip() if lastname is not None else None
        return firstname, lastname

    def _parse_scim_filter(self, filter_value: str | None) -> str | None:
        if not filter_value:
            return None
        match = search(r"userName\s+eq\s+[\"']([^\"']+)[\"']", filter_value, IGNORECASE)
        if not match:
            return None
        return match.group(1).strip().lower()

    def _parse_scim_group_filter(self, filter_value: str | None) -> str | None:
        if not filter_value:
            return None
        match = search(r"displayName\s+eq\s+[\"']([^\"']+)[\"']", filter_value, IGNORECASE)
        if match:
            return match.group(1).strip()
        match = search(r"externalId\s+eq\s+[\"']([^\"']+)[\"']", filter_value, IGNORECASE)
        if match:
            return match.group(1).strip()
        return None

    def _build_list_response(
        self, resources: list[dict[str, Any]], start_index: int, items_per_page: int, total: int
    ) -> dict[str, Any]:
        return {
            "schemas": [self.SCIM_LIST_SCHEMA],
            "totalResults": total,
            "startIndex": start_index,
            "itemsPerPage": items_per_page,
            "Resources": resources,
        }

    def _coerce_int(self, value: int, default: int, min_value: int, max_value: int) -> int:
        return max(min_value, min(max_value, value if isinstance(value, int) else default))

    def _list_project_role_groups(self) -> list[dict[str, Any]]:
        with DbSession.use(readonly=True) as db:
            projects = db.exec(
                SqlBuilder.select.table(Project)
                .where(Project.column("deleted_at") == None)  # noqa
                .order_by(Project.column("created_at").asc(), Project.column("id").asc())
            ).all()
        groups: list[dict[str, Any]] = []
        for project in projects:
            for role_key in ("owner", "contributor", "viewer"):
                groups.append(self._build_project_role_group(project, role_key))
        return groups

    def _build_project_role_group(self, project: Project, role_key: str) -> dict[str, Any]:
        members = self._get_project_role_group_members(project, role_key)
        display_name = f"{project.title} · {self._project_role_label(role_key)}"
        identifier = self._project_role_group_id(project, role_key)
        return {
            "id": identifier,
            "externalId": identifier,
            "displayName": display_name,
            "members": [
                {
                    "value": user.get_uid(),
                    "display": user.email,
                }
                for user in members
            ],
            "createdAt": project.created_at,
            "updatedAt": project.updated_at,
            "project": project,
            "roleKey": role_key,
        }

    def _get_project_role_group_members(self, project: Project, role_key: str) -> list[User]:
        with DbSession.use(readonly=True) as db:
            assigned = db.exec(
                SqlBuilder.select.table(ProjectAssignedUser)
                .where(ProjectAssignedUser.column("project_id") == project.id)
            ).all()
            users = db.exec(
                SqlBuilder.select.table(User)
                .where(
                    User.column("id").in_([record.user_id for record in assigned] + [project.owner_id])
                )
            ).all()
        user_map = {user.id: user for user in users}
        role_rows = self.repo.role.project.get_list(project_id=project.id)
        role_map = {role.user_id: role for role in role_rows if role.user_id}
        members: list[User] = []
        for user_id, user in user_map.items():
            derived = self._derive_project_role_key(project, user_id, role_map.get(user_id))
            if derived == role_key:
                members.append(user)
        members.sort(key=lambda item: (item.email or "", item.id))
        return members

    def _derive_project_role_key(
        self, project: Project, user_id: Any, role: ProjectRole | None
    ) -> str:
        if user_id == project.owner_id:
            return "owner"
        if role and role.is_all_granted():
            return "owner"
        if role and any(action != ProjectRoleAction.Read.value for action in role.actions):
            return "contributor"
        return "viewer"

    def _resolve_project_role_group_payload(self, payload: dict[str, Any]) -> dict[str, Any]:
        identifier = str(payload.get("externalId") or "").strip()
        parsed = self._parse_project_role_group_identifier(identifier)
        if not parsed:
            raise ApiException.BadRequest_400(ApiErrorCode.VA0000)
        project, role_key = parsed
        return {"project": project, "roleKey": role_key}

    def _resolve_group_or_raise(self, identifier: str) -> dict[str, Any]:
        parsed = self._parse_project_role_group_identifier(identifier)
        if not parsed:
            raise ApiException.NotFound_404(ApiErrorCode.NF1003)
        project, role_key = parsed
        return {"project": project, "roleKey": role_key, "members": self._build_project_role_group(project, role_key)["members"]}

    def _parse_project_role_group_identifier(self, identifier: str) -> tuple[Project, str] | None:
        parts = str(identifier or "").strip().split(":")
        if len(parts) != 3 or parts[0] != "project-role":
            return None
        _, project_uid, role_key = parts
        if role_key not in {"owner", "contributor", "viewer"}:
            return None
        project = self._resolve_project_identifier(project_uid)
        if not project:
            return None
        return project, role_key

    def _project_role_group_id(self, project: Project, role_key: str) -> str:
        return f"project-role:{project.get_uid()}:{role_key}"

    def _project_role_label(self, role_key: str) -> str:
        return {
            "owner": "Owners",
            "contributor": "Contributors",
            "viewer": "Viewers",
        }[role_key]

    def _extract_group_member_ids(self, payload: dict[str, Any]) -> list[str]:
        members = payload.get("members")
        if not isinstance(members, list):
            return []
        out: list[str] = []
        for item in members:
            if not isinstance(item, dict):
                continue
            value = str(item.get("value") or "").strip()
            if value:
                out.append(value)
        return list(dict.fromkeys(out))

    def _parse_member_value_filter(self, path: str) -> str:
        match = search(r'members\[value eq ["\']([^"\']+)["\']\]', path, IGNORECASE)
        return match.group(1).strip() if match else ""

    def _replace_project_role_group_members(self, project: Project, role_key: str, member_ids: list[str]) -> None:
        desired = set(member_ids)
        current = {
            member["value"] for member in self._build_project_role_group(project, role_key)["members"]
        }
        for user_id in sorted(desired - current):
            self._add_project_role_member(project, role_key, user_id)
        for user_id in sorted(current - desired):
            self._remove_project_role_member(project, role_key, user_id)

    def _add_project_role_member(self, project: Project, role_key: str, user_id: str) -> None:
        user = self._resolve_user_identifier(user_id)
        if not user:
            raise ApiException.NotFound_404(ApiErrorCode.NF1004)
        if not self._get_service_by_name("project").is_assigned(user, project)[0]:
            self.repo.project_assigned_user.insert(ProjectAssignedUser(project_id=project.id, user_id=user.id))
        if role_key == "owner":
            if user.id != project.owner_id:
                self.repo.role.project.grant_all(user_id=user.id, project_id=project.id)
            return
        if role_key == "contributor":
            self.repo.role.project.grant(
                user_id=user.id,
                project_id=project.id,
                actions=[
                    ProjectRoleAction.Read.value,
                    ProjectRoleAction.Update.value,
                    ProjectRoleAction.CardWrite.value,
                    ProjectRoleAction.CardUpdate.value,
                ],
            )
            return
        self.repo.role.project.grant_default(user_id=user.id, project_id=project.id)

    def _remove_project_role_member(self, project: Project, role_key: str, user_id: str) -> None:
        user = self._resolve_user_identifier(user_id)
        if not user:
            return
        current_key = self._derive_project_role_key(
            project, user.id, self.repo.role.project.get_one(project_id=project.id, user_id=user.id)
        )
        if current_key != role_key:
            return
        if role_key == "owner" and user.id == project.owner_id:
            return
        self._get_service_by_name("project").unassign_assignee(user, project, user)

    def _resolve_project_identifier(self, identifier: str) -> Project | None:
        project = InfraHelper.get_by_id_like(Project, identifier)
        if project:
            return project
        normalized = str(identifier or "").strip()
        if not normalized:
            return None
        with DbSession.use(readonly=True) as db:
            projects = db.exec(
                SqlBuilder.select.table(Project).where(Project.column("deleted_at") == None)  # noqa
            ).all()
        for item in projects:
            if item.get_uid() == normalized:
                return item
        return None

    def _resolve_user_identifier(self, identifier: str) -> User | None:
        user = InfraHelper.get_by_id_like(User, identifier)
        if user:
            return user
        normalized = str(identifier or "").strip()
        if not normalized:
            return None
        identity_link = self._get_service(IdentityLinkService)
        user = identity_link.get_user_by_provider_external_id(IdentityProvider.Scim, normalized)
        if user:
            return user
        user_service = self._get_service(UserService)
        user, _ = user_service.get_by_email(normalized)
        if user:
            return user
        with DbSession.use(readonly=True) as db:
            users = db.exec(
                SqlBuilder.select.table(User).where(User.column("deleted_at") == None)  # noqa
            ).all()
        normalized_lower = normalized.lower()
        for item in users:
            if item.get_uid() == normalized or str(item.email or "").strip().lower() == normalized_lower:
                return item
        return None
