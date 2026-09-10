from re import IGNORECASE, search
from typing import Any
from ....core.domain import BaseDomainService
from ....core.exceptions import ScimProvisioningException
from ....core.types import SafeDateTime, SnowflakeID
from ....core.utils.String import generate_random_string
from ....Env import Env
from ....helpers import InfraHelper
from ....security import Auth
from ...models import IdentityProvider, ScimGroup, ScimGroupMember, User
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
    def SCIM_GROUP_SCHEMA(self) -> str:
        return "urn:ietf:params:scim:schemas:core:2.0:Group"

    @property
    def SCIM_LIST_SCHEMA(self) -> str:
        return "urn:ietf:params:scim:api:messages:2.0:ListResponse"

    def resolve_user(self, identifier: str) -> User | None:
        identity_link = self._get_service(IdentityLinkService)
        user = identity_link.get_user_by_provider_external_id(
            IdentityProvider.Scim,
            identifier,
            (Env.SCIM_ISSUER or "").rstrip("/"),
        )
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

    def resolve_group(self, identifier: str) -> ScimGroup | None:
        group = self.repo.scim_group.get_by_external_id(identifier)
        if group:
            return group

        return InfraHelper.get_by_id_like(ScimGroup, identifier)

    def build_scim_group(self, group: ScimGroup) -> dict[str, Any]:
        members = self.repo.scim_group_member.get_users_by_group(group)
        return self._build_scim_group(group, members)

    def get_api_group_list(self) -> list[dict[str, Any]]:
        groups = self.repo.scim_group.get_all()
        members = self.repo.scim_group_member.get_users_by_groups([group.id for group in groups])
        members_by_group: dict[int, list[tuple[ScimGroupMember, User]]] = {}
        for group_member, user in members:
            members_by_group.setdefault(group_member.group_id, []).append((group_member, user))

        return [self._build_scim_group(group, members_by_group.get(group.id, [])) for group in groups]

    def _build_scim_group(self, group: ScimGroup, members: list[tuple[ScimGroupMember, User]]) -> dict[str, Any]:
        member_resources = [
            {
                "value": user.get_uid(),
                "display": user.get_fullname(),
                "$ref": f"/scim/v2/Users/{user.get_uid()}",
            }
            for _, user in members
        ]
        content = {
            "schemas": [self.SCIM_GROUP_SCHEMA],
            "id": group.get_uid(),
            "displayName": group.display_name,
            "members": member_resources,
            "meta": {
                "resourceType": "Group",
                "created": group.created_at,
                "lastModified": group.updated_at,
            },
        }
        if group.external_id:
            content["externalId"] = group.external_id
        return content

    def list_users(self, start_index: int, count: int, filter_value: str | None) -> dict[str, Any]:
        normalized_start = self._coerce_int(start_index, default=1, min_value=1, max_value=100000)
        normalized_count = self._coerce_int(count, default=100, min_value=1, max_value=200)
        user_name_filter = self._parse_scim_filter(filter_value, "userName")
        user_service = self._get_service(UserService)

        if user_name_filter:
            user, _ = user_service.get_by_email(user_name_filter.lower())
            resources = [self.build_scim_user(user)] if user else []
            return self._build_list_response(resources, 1, len(resources), len(resources))

        total = self.repo.user.count_not_deleted()
        users = self.repo.user.get_not_deleted_page(normalized_start - 1, normalized_count)

        resources = [self.build_scim_user(user) for user in users]
        return self._build_list_response(resources, normalized_start, normalized_count, int(total))

    def list_groups(self, start_index: int, count: int, filter_value: str | None) -> dict[str, Any]:
        normalized_start = self._coerce_int(start_index, default=1, min_value=1, max_value=100000)
        normalized_count = self._coerce_int(count, default=100, min_value=1, max_value=200)
        display_name_filter = self._parse_scim_filter(filter_value, "displayName")
        external_id_filter = self._parse_scim_filter(filter_value, "externalId")

        if display_name_filter:
            group = self.repo.scim_group.get_by_display_name(display_name_filter)
            resources = [self.build_scim_group(group)] if group else []
            return self._build_list_response(resources, 1, len(resources), len(resources))

        if external_id_filter:
            group = self.repo.scim_group.get_by_external_id(external_id_filter)
            resources = [self.build_scim_group(group)] if group else []
            return self._build_list_response(resources, 1, len(resources), len(resources))

        total = self.repo.scim_group.count_all()
        groups = self.repo.scim_group.get_page(normalized_start - 1, normalized_count)
        resources = [self.build_scim_group(group) for group in groups]
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
            raise ScimProvisioningException.InvalidRequest()

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
                user_service.update(user, {"activated_at": SafeDateTime.now()}, from_setting=True)
            elif not active and user.activated_at:
                self.deactivate_user(user)

        if email and email != user.email:
            existing, _ = self._get_service(UserService).get_by_email(email)
            if existing and existing.id != user.id:
                raise ScimProvisioningException.Conflict()

            user.email = email
            self.repo.user.update(user)
            Auth.reset_user(user)

        self._upsert_identity_link(user, payload.get("externalId"), user.email)

    def deactivate_user(self, user: User) -> None:
        if user.activated_at:
            self._get_service(UserService).update(user, {"activated_at": None}, from_setting=True)

    def delete_user(self, user: User) -> None:
        self.deactivate_user(user)
        self.repo.scim_group_member.delete_all_by_user(user)

    def create_or_upsert_group(self, payload: dict[str, Any]) -> ScimGroup:
        external_id = self._extract_external_id(payload)
        display_name = self._extract_display_name(payload)

        group = self.repo.scim_group.get_by_external_id(external_id) if external_id else None
        if not group and display_name:
            group = self.repo.scim_group.get_by_display_name(display_name)

        if group:
            self.apply_group_mutations(group, payload)
            return group

        return self.create_group(payload)

    def create_group(self, payload: dict[str, Any]) -> ScimGroup:
        display_name = self._extract_display_name(payload)
        if not display_name:
            raise ScimProvisioningException.InvalidRequest()

        external_id = self._extract_external_id(payload)
        if external_id and self.repo.scim_group.get_by_external_id(external_id):
            raise ScimProvisioningException.Conflict()

        group = ScimGroup(display_name=display_name, external_id=external_id or None)
        self.repo.scim_group.insert(group)
        if "members" in payload:
            user_ids = self._extract_group_member_user_ids(payload)
            self.repo.scim_group_member.replace_group_members(group, user_ids)
        return group

    def apply_group_mutations(self, group: ScimGroup, payload: dict[str, Any]) -> None:
        display_name = self._extract_display_name(payload)
        external_id = self._extract_external_id(payload)
        has_external_id = "externalId" in payload

        if display_name and display_name != group.display_name:
            group.display_name = display_name

        if has_external_id and not external_id:
            group.external_id = None
        elif external_id and external_id != group.external_id:
            existing = self.repo.scim_group.get_by_external_id(external_id)
            if existing and existing.id != group.id:
                raise ScimProvisioningException.Conflict()
            group.external_id = external_id

        self.repo.scim_group.update(group)
        if "members" in payload:
            new_user_ids = self._extract_group_member_user_ids(payload)
            self.repo.scim_group_member.replace_group_members(group, new_user_ids)

    def delete_group(self, group: ScimGroup) -> None:
        self.repo.scim_group_member.delete_all_by_group(group)
        self.repo.scim_group.delete(group, purge=True)

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

    def apply_group_patch(self, group: ScimGroup, operations: list[dict[str, Any]]) -> None:
        payload: dict[str, Any] = {}
        current_members = [
            {"value": user.get_uid(), "display": user.get_fullname()}
            for _, user in self.repo.scim_group_member.get_users_by_group(group)
        ]
        next_members = current_members
        members_changed = False

        for operation in operations:
            op = str(operation.get("op", "")).strip().lower()
            path = str(operation.get("path", "")).strip()
            path_lower = path.lower()
            value = operation.get("value")

            if op not in {"add", "replace", "remove"}:
                continue

            if not path and isinstance(value, dict):
                for key in ("displayName", "externalId", "members"):
                    if key in value:
                        payload[key] = value[key]
                continue

            if path_lower == "displayname":
                if op != "remove" and value is not None:
                    payload["displayName"] = str(value)
                continue

            if path_lower == "externalid":
                if op == "remove":
                    payload["externalId"] = None
                elif value is not None:
                    payload["externalId"] = str(value)
                continue

            if path_lower == "members":
                members_changed = True
                if op == "remove":
                    next_members = []
                elif op == "replace":
                    next_members = self._normalize_member_payload(value)
                elif op == "add":
                    next_members = [*next_members, *self._normalize_member_payload(value)]
                continue

            member_value = self._parse_member_filter_value(path)
            if member_value:
                members_changed = True
                if op == "remove":
                    next_members = [member for member in next_members if member.get("value") != member_value]
                elif value is not None:
                    next_members = [*next_members, *self._normalize_member_payload(value)]

        if members_changed:
            payload["members"] = next_members
        self.apply_group_mutations(group, payload)

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

    def _extract_external_id(self, payload: dict[str, Any]) -> str:
        external_id = payload.get("externalId")
        return str(external_id).strip() if external_id is not None else ""

    def _extract_display_name(self, payload: dict[str, Any]) -> str:
        display_name = payload.get("displayName")
        return str(display_name).strip() if display_name is not None else ""

    def _extract_group_member_user_ids(self, payload: dict[str, Any]) -> list[SnowflakeID]:
        members = self._normalize_member_payload(payload.get("members"))
        user_ids: list[SnowflakeID] = []
        for member in members:
            value = str(member.get("value", "")).strip()
            if not value:
                continue

            user = self.resolve_user(value)
            if not user:
                raise ScimProvisioningException.InvalidRequest()
            user_ids.append(user.id)
        return list(dict.fromkeys(user_ids))

    def _normalize_member_payload(self, value: Any) -> list[dict[str, Any]]:
        if value is None:
            return []
        if isinstance(value, str):
            return [{"value": value}]
        if isinstance(value, dict):
            return [value]
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
        return []

    def _extract_names(self, payload: dict[str, Any]) -> tuple[str | None, str | None]:
        name = payload.get("name", {})
        if not isinstance(name, dict):
            name = {}

        firstname = name.get("givenName")
        lastname = name.get("familyName")

        firstname = str(firstname).strip() if firstname is not None else None
        lastname = str(lastname).strip() if lastname is not None else None
        return firstname, lastname

    def _parse_scim_filter(self, filter_value: str | None, attr: str) -> str | None:
        if not filter_value:
            return None
        match = search(rf"{attr}\s+eq\s+[\"']([^\"']+)[\"']", filter_value, IGNORECASE)
        if not match:
            return None
        return match.group(1).strip()

    def _parse_member_filter_value(self, path: str) -> str | None:
        match = search(r"members\s*\[\s*value\s+eq\s+[\"']([^\"']+)[\"']\s*\]", path, IGNORECASE)
        if not match:
            return None
        return match.group(1).strip()

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
