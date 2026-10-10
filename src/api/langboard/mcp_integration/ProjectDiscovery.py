"""Compact native project discovery shared by independent MCP clients."""

from functools import wraps
from inspect import signature
from urllib.parse import quote
from langboard_shared.Env import Env
from pydantic import BaseModel, ConfigDict, Field


class ProjectSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    uid: str = Field(min_length=1)
    title: str = Field(min_length=1)
    project_type: str
    starred: bool
    current_auth_role_actions: list[str] | None
    project_url: str
    project_link_markdown: str


class ProjectDiscoveryResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    projects: list[ProjectSummary]


def with_project_discovery(handler):
    """Project only the already-authorized server list; never grant access."""

    @wraps(handler)
    async def compact(**kwargs):
        result = await handler(**kwargs)
        projects = []
        for project in result["projects"]:
            url = f"{Env.PUBLIC_UI_URL.rstrip('/')}/board/{quote(project['uid'], safe='')}"
            projects.append(
                ProjectSummary(
                    **{
                        key: project[key]
                        for key in ("uid", "title", "project_type", "starred", "current_auth_role_actions")
                    },
                    project_url=url,
                    project_link_markdown=f"[Open board in Langboard]({url})",
                )
            )
        return ProjectDiscoveryResponse(projects=projects)

    compact.__signature__ = signature(handler).replace(return_annotation=ProjectDiscoveryResponse)
    return compact
