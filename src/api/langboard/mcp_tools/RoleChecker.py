from collections.abc import Callable
from typing import Any
from langboard_shared.ai import BotScopeHelper
from langboard_shared.domain.models import Bot, ProjectBotScope, ProjectRole, User
from langboard_shared.domain.services.DomainService import DomainService
from langboard_shared.security import RoleSecurity
from ..mcp_integration.RoleFilter import McpRoleFilter


class McpRoleChecker:
    """Apply one MCP role policy consistently across all execution transports."""

    def __init__(self, service: DomainService) -> None:
        self.service = service

    def check_permission(
        self,
        method: Callable[..., Any],
        user_or_bot: User | Bot,
        arguments: dict[str, Any],
    ) -> bool:
        """Return whether the actor may invoke a role-filtered MCP method."""

        if not McpRoleFilter.exists(method):
            return True

        role_model, required_actions, role_finder, allowed_all_admin = McpRoleFilter.get_filtered(method)

        if isinstance(user_or_bot, Bot):
            if role_model is not ProjectRole:
                return True
            return self._has_project_scope(user_or_bot, arguments)

        if allowed_all_admin and user_or_bot.is_admin:
            return True

        return RoleSecurity(role_model).is_authorized(
            user_or_bot.id,
            arguments,
            required_actions,
            role_finder,
        )

    def _has_project_scope(self, bot: Bot, arguments: dict[str, Any]) -> bool:
        project_uid = arguments.get("project_uid")
        if not isinstance(project_uid, str) or not project_uid:
            return False

        project = self.service.project.get_by_id_like(project_uid)
        if not project:
            return False

        scopes = BotScopeHelper.get_list(ProjectBotScope, bot_id=bot.id, project_id=project.id)
        return bool(scopes)
