"""Existing-label selection and explicitly requested project-local label creation."""

import re
from typing import Any
from langboard_shared.domain.models import Bot, GlobalLabel, ProjectRole, User
from langboard_shared.domain.models.ProjectRole import ProjectRoleAction
from langboard_shared.domain.services.DomainService import DomainService
from langboard_shared.helpers import InfraHelper
from langboard_shared.security import RoleFinder
from ..card_workspace.application.projections import public_label
from ..mcp_integration import McpRoleFilter, McpTool


def _project(service: DomainService, project_uid: str):
    project = service.project.get_by_id_like(project_uid)
    if not project:
        raise ValueError("Project not found")
    return project


def _local_named(service: DomainService, project: Any, name: str) -> dict | None:
    return next(
        (
            label
            for label in service.project_label.get_api_list_by_project(project)
            if label["name"].strip().casefold() == name.casefold()
        ),
        None,
    )


@McpTool.add(description="Read existing labels, board-local first then global; no label creation.")
@McpRoleFilter.add(ProjectRole, [ProjectRoleAction.Read], RoleFinder.project)
def get_project_label_catalog(
    project_uid: str, service: DomainService, query: str = "", offset: int = 0, limit: int = 25
) -> dict[str, Any]:
    project = _project(service, project_uid)
    if len(query) > 100 or offset < 0 or not 1 <= limit <= 25:
        raise ValueError("Invalid label query bounds")
    query = query.strip().casefold()
    local = [
        {**public_label(label), "source": "local"} for label in service.project_label.get_api_list_by_project(project)
    ]
    global_labels = [
        {
            "uid": label.get_uid(),
            "name": label.name,
            "color": label.color,
            "description": label.description,
            "source": "global",
        }
        for label in sorted(InfraHelper.get_all(GlobalLabel), key=lambda label: label.name.casefold())
    ]
    labels = [label for label in [*local, *global_labels] if not query or query in label["name"].casefold()]
    return {
        "items": labels[offset : offset + limit],
        "total_count": len(labels),
        "next_offset": offset + limit if len(labels) > offset + limit else None,
    }


@McpTool.add(description="Create a board-local label only on explicit user instruction; never a global label.")
@McpRoleFilter.add(ProjectRole, [ProjectRoleAction.Update], RoleFinder.project)
def create_local_project_label(
    project_uid: str,
    name: str,
    user_or_bot: User | Bot,
    service: DomainService,
    explicit_user_request: bool = False,
    color: str = "#4A90E2",
    description: str = "",
) -> dict[str, Any]:
    if explicit_user_request is not True:
        raise ValueError("LOCAL_LABEL_CREATION_REQUIRES_EXPLICIT_USER_REQUEST")
    name = name.strip()
    if not name or len(name) > 100 or not re.fullmatch(r"#[0-9A-Fa-f]{6}", color) or len(description) > 4000:
        raise ValueError("Invalid label fields")
    project = _project(service, project_uid)
    existing = _local_named(service, project, name)
    if existing:
        return {"label": public_label(existing), "created": False}
    result = service.project_label.create(user_or_bot, project, name, color.upper(), description)
    if not result:
        raise RuntimeError("Local label creation failed")
    return {"label": public_label(result[1]), "created": True}


@McpTool.add(
    description="Reuse an existing global label in a board; prefer an existing local name match. Never create a global label."
)
@McpRoleFilter.add(ProjectRole, [ProjectRoleAction.Update], RoleFinder.project)
def use_global_project_label(
    project_uid: str, global_label_uid: str, user_or_bot: User | Bot, service: DomainService
) -> dict[str, Any]:
    project = _project(service, project_uid)
    global_label = InfraHelper.get_by_id_like(GlobalLabel, global_label_uid)
    if not global_label:
        raise ValueError("Global label not found")
    existing = _local_named(service, project, global_label.name.strip())
    if existing:
        return {"label": public_label(existing), "created": False, "global_label_uid": global_label_uid}
    result = service.project_label.create(
        user_or_bot, project, global_label.name, global_label.color, global_label.description
    )
    if not result:
        raise RuntimeError("Global label reuse failed")
    return {"label": public_label(result[1]), "created": True, "global_label_uid": global_label_uid}


@McpTool.add(description="Attach/detach an existing local label while preserving other card labels.")
@McpRoleFilter.add(ProjectRole, [ProjectRoleAction.CardUpdate], RoleFinder.project)
def change_card_label(
    project_uid: str, card_uid: str, label_uid: str, action: str, user_or_bot: User | Bot, service: DomainService
) -> dict[str, Any]:
    from .CardMcp import _require_task_card

    if action not in {"attach", "detach"}:
        raise ValueError("Unsupported card label action")
    project, card = _require_task_card(project_uid, card_uid)
    available = service.project_label.get_api_list_by_project(project, where_in=[label_uid])
    if not any(label["uid"] == label_uid for label in available):
        raise ValueError("Unknown local label")
    current = service.project_label.get_api_list_by_card(card)
    uids = [label["uid"] for label in current]
    changed = label_uid not in uids if action == "attach" else label_uid in uids
    if changed:
        uids = [*uids, label_uid] if action == "attach" else [uid for uid in uids if uid != label_uid]
        if not service.card.update_labels(user_or_bot, project, card, uids):
            raise RuntimeError("Card label change failed")
    return {
        "labels": [public_label(label) for label in service.project_label.get_api_list_by_card(card)],
        "changed": changed,
    }
