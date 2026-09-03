from json import dumps as json_dumps
from json import loads as json_loads
from typing import TYPE_CHECKING, Any, Sequence, cast
from urllib.parse import urlparse
from ....core.caching import Cache
from ....core.domain import BaseDomainService
from ....core.domain.BaseDomainService import TMutableValidatorMap
from ....core.resources.locales.LangEnum import LangEnum
from ....core.storage import FileModel
from ....core.types import SafeDateTime, SnowflakeID
from ....core.types.ParamTypes import TUserParam
from ....core.utils.Converter import convert_python_data
from ....core.utils.Encryptor import Encryptor
from ....core.utils.String import concat, generate_random_string
from ....Env import UI_QUERY_NAMES, Env
from ....helpers import InfraHelper
from ....publishers import AppSettingPublisher, UserPublisher
from ....security import Auth
from ...models import SettingRole, User, UserEmail, UserProfile, UserSignInHistory
from ...models.SettingRole import SettingRoleAction, SettingRoleCategory
from ...models.UserSignInHistory import SignInErrorCode


if TYPE_CHECKING:
    from .ProjectInvitationService import ProjectInvitationService


class UserService(BaseDomainService):
    @staticmethod
    def name() -> str:
        """DO NOT EDIT THIS METHOD"""
        return "user"

    def get_by_id_like(self, user: TUserParam | None) -> User | None:
        project = InfraHelper.get_by_id_like(User, user)
        return project

    def create_cache_name(self, cache_type: str, email: str) -> str:
        return f"{cache_type}:{email}"

    def get_api_list_in_settings(self) -> list[dict[str, Any]]:
        users = self.repo.user.get_all_with_profile_in_settings()
        if not users:
            return []

        api_key_roles = self.repo.role.api_key.get_list(user_id=cast(SnowflakeID, [user.id for user, _ in users]))
        api_key_role_actions_dicts = {role.user_id: role.actions for role in api_key_roles}

        setting_roles = self.repo.role.setting.get_list(user_id=cast(SnowflakeID, [user.id for user, _ in users]))
        setting_role_actions_dicts = {role.user_id: role.actions for role in setting_roles}

        mcp_roles = self.repo.role.mcp.get_list(user_id=cast(SnowflakeID, [user.id for user, _ in users]))
        mcp_role_actions_dicts = {role.user_id: role.actions for role in mcp_roles}

        api_list = []
        for user, profile in users:
            api_user = user.api_response()
            if profile:
                api_user.update(profile.api_response())
            else:
                api_user.update(
                    {
                        "industry": "",
                        "purpose": "",
                        "affiliation": None,
                        "position": None,
                    }
                )
            api_user["created_at"] = user.created_at
            api_user["activated_at"] = user.activated_at
            api_user["is_admin"] = user.is_admin
            api_user["setting_role_actions"] = setting_role_actions_dicts.get(user.id, [])
            api_user["api_key_role_actions"] = api_key_role_actions_dicts.get(user.id, [])
            api_user["mcp_role_actions"] = mcp_role_actions_dicts.get(user.id, [])
            api_list.append(api_user)

        return api_list

    def count_not_deleted(self) -> int:
        return self.repo.user.count_not_deleted()

    def get_by_email(self, email: str | None):
        if not email:
            return None, None
        return self.repo.user.get_by_email(email)

    def get_by_token(self, token: str | None, key: str | None) -> tuple[User, UserEmail | None] | tuple[None, None]:
        if not token or not key:
            return None, None
        email = Encryptor.decrypt(token, key)
        return self.repo.user.get_by_email(email)

    def get_api_profile(self, user: TUserParam) -> dict[str, Any]:
        profile = self.repo.user_profile.get_by_user(user)
        if not profile:
            return {}
        return profile.api_response()

    def create(self, form: dict, avatar: FileModel | None = None) -> tuple[User, UserProfile]:
        user = User(**form)
        user.avatar = avatar

        self.repo.user.insert(user)

        user_profile = UserProfile(user_id=user.id, **form)
        self.repo.user_profile.insert(user_profile)

        return user, user_profile

    def create_subemail(self, user: TUserParam, email: str) -> UserEmail:
        user_id = InfraHelper.convert_id(user)
        user_email = UserEmail(user_id=user_id, email=email)
        self.repo.user_email.insert(user_email)

        return user_email

    def get_subemails(self, user: User) -> list[dict[str, Any]]:
        if not user.id:
            return []
        raw_subemails = self.repo.user_email.get_all_by_user(user.id)
        subemails = [subemail.api_response() for subemail in raw_subemails]
        return subemails

    def create_token_url(
        self,
        user: User,
        cache_key: str,
        token_query_name: UI_QUERY_NAMES,
        extra_token_data: dict | None = None,
    ) -> str:
        token = generate_random_string(32)
        token_expire_hours = 24
        token_data = json_dumps({"token": token, "id": user.id})
        encrypted_token = Encryptor.encrypt(token_data, Env.COMMON_SECRET_KEY)

        url_chunks = urlparse(Env.UI_REDIRECT_URL)
        token_url = url_chunks._replace(
            query=concat(
                url_chunks.query,
                "&" if url_chunks.query else "",
                token_query_name.value,
                "=",
                encrypted_token,
            )
        ).geturl()

        cache_token_Data = {"token": token, "id": user.id}
        if extra_token_data:
            cache_token_Data["extra"] = extra_token_data

        Cache.set(cache_key, cache_token_Data, 60 * 60 * token_expire_hours)

        return token_url

    def validate_token_from_url(
        self, token_type: str, token: str
    ) -> tuple[User, str, dict | None] | tuple[None, None, None]:
        try:
            token_info = json_loads(Encryptor.decrypt(token, Env.COMMON_SECRET_KEY))
            if not token_info or "token" not in token_info or "id" not in token_info:
                raise Exception()
        except Exception:
            return None, None, None

        user = InfraHelper.get_by(User, "id", token_info["id"])
        if not user:
            return None, None, None

        cache_key = self.create_cache_name(token_type, user.email)

        cached_token_info: dict | None = Cache.get(cache_key)
        if (
            not cached_token_info
            or cached_token_info["id"] != user.id
            or cached_token_info["token"] != token_info["token"]
        ):
            return None, None, None

        return user, cache_key, cached_token_info.get("extra")

    def activate(self, user: User) -> None:
        user.activated_at = SafeDateTime.now()
        self.repo.user.update(user)

        invitation_service: "ProjectInvitationService" = self._get_service_by_name("project_invitation")
        invitation_service.update_by_signed_up(user)

    def verify_subemail(self, subemail: UserEmail) -> None:
        subemail.verified_at = SafeDateTime.now()
        self.repo.user_email.update(subemail)

    def update(self, user: User, form: dict, from_setting: bool = False) -> bool:
        profile = self.repo.user_profile.get_by_user(user)
        if not profile:
            profile = UserProfile(
                user_id=user.id,
                industry=str(form.get("industry", "") or ""),
                purpose=str(form.get("purpose", "") or ""),
                affiliation=form.get("affiliation"),
                position=form.get("position"),
            )

        validators: TMutableValidatorMap = {
            "firstname": "default",
            "lastname": "default",
            "avatar": "default",
        }
        profile_validators: TMutableValidatorMap = {
            "affiliation": "default",
            "position": "default",
        }
        if from_setting:
            validators.update(
                {
                    "is_admin": "default",
                    "activated_at": "nullable",
                }
            )
            profile_validators.update(
                {
                    "industry": "default",
                    "purpose": "default",
                }
            )

        old_record = self.apply_mutates(user, form, validators)
        old_record.update(self.apply_mutates(profile, form, profile_validators))

        if "delete_avatar" in form and form["delete_avatar"]:
            old_record["avatar"] = convert_python_data(user.avatar)
            user.avatar = None

        if not old_record:
            if profile.is_new():
                self.repo.user_profile.insert(profile)
            return True

        if profile.is_new():
            self.repo.user.update(user)
            self.repo.user_profile.insert(profile)
        else:
            self.repo.user.update([user, profile])

        Auth.reset_user(user)

        model: dict[str, Any] = {}
        for key in form:
            if key not in validators or key not in old_record:
                continue
            if key == "avatar":
                model[key] = user.avatar.path if user.avatar else None
            else:
                model[key] = convert_python_data(getattr(user, key))

        UserPublisher.updated(user, model)
        if from_setting and model:
            AppSettingPublisher.user_updated(user.get_uid(), model)
        if from_setting:
            if "activated_at" in form and not user.activated_at:
                UserPublisher.deactivated(user)

        return True

    def update_preferred_lang(self, user: User, lang: str):
        if lang in LangEnum.__members__:
            lang = LangEnum[lang].value
        elif lang in LangEnum._value2member_map_:
            lang = lang
        else:
            return False

        user.preferred_lang = lang
        self.repo.user.update(user)

        return True

    def change_primary_email(self, user: User, subemail: UserEmail) -> bool:
        user_email = user.email
        user.email = subemail.email
        subemail.email = user_email

        self.repo.user.update([user, subemail])

        Auth.reset_user(user)

        model = {"email": user.email}
        UserPublisher.updated(user, model)

        return True

    def delete_email(self, subemail: UserEmail) -> bool:
        self.repo.user_email.delete(subemail)

        return True

    def change_password(self, user: User, password: str) -> None:
        user.set_password(password)
        self.repo.user.update(user)

    def get_setting_role(self, user: TUserParam) -> SettingRole | None:
        user_id = InfraHelper.convert_id(user)
        return self.repo.role.setting.get_one(user_id=user_id)

    def can_search_all_users(self, user: User) -> bool:
        if user.email in Env.FULL_ADMIN_ACCESS_EMAILS:
            return True

        if not user.is_admin:
            return False

        role = self.get_setting_role(user)
        return bool(role and role.is_granted(SettingRoleAction.UserRead))

    def grant_setting_roles(
        self,
        user: TUserParam,
        actions: SettingRoleAction | str | list[SettingRoleAction | str] | list[SettingRoleAction] | list[str],
    ) -> SettingRole:
        user_id = InfraHelper.convert_id(user)
        if not isinstance(actions, list):
            actions = [actions]
        action_strs = [action.value if isinstance(action, SettingRoleAction) else action for action in actions]

        # Handle Read permission dependencies for SettingRole
        action_strs = self._normalize_setting_role_actions(action_strs)

        role = self.repo.role.setting.grant(actions=action_strs, user_id=user_id)

        UserPublisher.setting_roles_updated(InfraHelper.convert_uid(user), role.actions)

        return role

    def _normalize_setting_role_actions(self, actions: list[str]) -> list[str]:
        """Ensure Read permission dependencies are properly handled for SettingRole"""
        if not actions:
            return actions

        result = set(actions)

        # Dynamically get actions for each category
        for category in SettingRoleCategory:
            category_value = category.value
            read_action = f"{category_value}_read"

            # Get all actions for this category by checking SettingRoleAction enum
            category_actions = [
                action.value for action in SettingRoleAction if action.value.startswith(f"{category_value}_")
            ]

            if not category_actions:
                continue

            dependent_actions = [action for action in category_actions if action != read_action]

            # If any Create/Update/Delete is added, add Read too
            if any(action in result for action in dependent_actions):
                result.add(read_action)

            # If Read is removed, remove all dependent actions
            if read_action not in result:
                for action in dependent_actions:
                    result.discard(action)

        return list(result)

    def grant_all_setting_roles(self, user: TUserParam) -> SettingRole:
        user_id = InfraHelper.convert_id(user)
        role = self.repo.role.setting.grant_all(user_id=user_id)

        UserPublisher.setting_roles_updated(InfraHelper.convert_uid(user), role.actions)

        return role

    def delete(self, user: User) -> None:
        self.repo.user.delete(user)

        Auth.reset_user(user)
        UserPublisher.deleted(user)

    def delete_selected(self, users: Sequence[TUserParam]) -> None:
        if not isinstance(users, Sequence) or isinstance(users, str):
            users = [users]

        self.repo.user.delete(users)

        ids = [InfraHelper.convert_id(user) for user in users]
        uids = [InfraHelper.convert_uid(user) for user in users]
        AppSettingPublisher.selected_users_deleted(uids)
        for user_id in ids:
            UserPublisher.deleted(user_id)

    def log_sign_in(
        self,
        user: User,
        is_success: bool = True,
        ip_address: str | None = None,
        error_code: SignInErrorCode | None = None,
    ) -> None:
        login_history = UserSignInHistory(
            user_id=user.id, is_success=is_success, ip_address=ip_address, error_code=error_code
        )
        self.repo.user_sign_in_history.insert(login_history)
