"""Route committed external records to their native domain effect owners."""

from typing import Any
from langboard_shared.domain.models import Project, ProjectAssignedUser, User
from langboard_shared.domain.services import DomainService
from pydantic import BaseModel
from .contract import (
    ExternalAttachment,
    ExternalCard,
    ExternalCheckitem,
    ExternalChecklist,
    ExternalColumn,
    ExternalComment,
    ExternalLabel,
    ExternalRelationship,
)


def dispatch_imported_effects(
    domain: DomainService,
    kind: str,
    record: BaseModel,
    target: Any,
    project: Project,
    actor: User,
    targets: dict[tuple[str, str], Any],
    principals: dict[str, tuple[User, ProjectAssignedUser]],
) -> None:
    """Emit historical publisher/activity effects without live bots or notifications."""

    if kind == "column" and isinstance(record, ExternalColumn):
        domain.project_column.dispatch_created(actor, project, target, include_bot=False)
    elif kind == "label" and isinstance(record, ExternalLabel):
        domain.project_label.dispatch_created(actor, project, target, include_bot=False)
    elif kind == "card" and isinstance(record, ExternalCard):
        column = targets[("column", record.column_source_id)]
        member_uids = [principals[external_id][0].get_uid() for external_id in record.assignee_scim_external_ids]
        labels = [targets[("label", source_id)].api_response() for source_id in record.label_source_ids]
        domain.card.dispatch_created(
            actor,
            project,
            column,
            target,
            {"card": target.board_api_response(0, member_uids, [], labels)},
            include_bot=False,
            include_notifications=False,
        )
    elif kind == "checklist" and isinstance(record, ExternalChecklist):
        card = targets[("card", record.card_source_id)]
        domain.checklist.dispatch_created(actor, project, card, target, include_bot=False)
    elif kind == "checkitem" and isinstance(record, ExternalCheckitem):
        checklist = targets[("checklist", record.checklist_source_id)]
        card = domain.card.get_by_id_like(checklist.card_id)
        if card is None:
            raise ValueError("checklist card disappeared before side-effect dispatch")
        domain.checkitem.dispatch_created(actor, project, card, checklist, target, include_bot=False)
    elif kind == "relationship" and isinstance(record, ExternalRelationship):
        parent = targets[("card", record.parent_card_source_id)]
        child = targets[("card", record.child_card_source_id)]
        domain.card_relationship.dispatch_updated(actor, project, parent, [], [child.id], False, include_bot=False)
    elif kind == "comment" and isinstance(record, ExternalComment):
        card = targets[("card", record.card_source_id)]
        author, _ = principals[record.author_scim_external_id]
        domain.card_comment.dispatch_created(
            author, project, card, target, include_notifications=False, include_bot=False
        )
    elif kind == "attachment" and isinstance(record, ExternalAttachment):
        card = targets[("card", record.card_source_id)]
        author, _ = principals[record.author_scim_external_id]
        domain.card_attachment.dispatch_created(author, project, card, target, include_bot=False)
    else:
        raise ValueError(f"unsupported side-effect record: {kind}")
