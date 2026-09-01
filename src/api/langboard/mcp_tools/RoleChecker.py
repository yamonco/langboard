from typing import Callable
from langboard_shared.domain.models import Bot, User
from langboard_shared.domain.services.DomainService import DomainService
from ..mcp_integration import McpRoleFilter


class McpRoleChecker:
    def __init__(self, service: DomainService):
        self.service = service

    def check_permission(
        self,
        method: Callable,
        user_or_bot: User | Bot,
        arguments: dict,
    ) -> bool:
        if isinstance(user_or_bot, Bot):
            return True

        if not McpRoleFilter.exists(method):
            return True

        required_actions = McpRoleFilter.get_filtered(method)

        project_uid = arguments.get("project_uid")
        if not project_uid:
            return True

        project = self.service.project.get_by_id_like(project_uid)
        if not project:
            return False

        actions = self.service.project.get_user_role_actions_by_project(user_or_bot, project)

        for action in required_actions:
            if action not in actions:
                return False

        return True
