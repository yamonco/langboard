"""Card to wiki links backed by one metadata row per wiki.

Keep authorization at read time: a link never grants access to a private wiki.
"""

import re
from langboard_shared.core.db import DbSession, SqlBuilder
from langboard_shared.domain.models import Bot, Card, CardMetadata, Project, ProjectWiki, ProjectWikiAssignedUser, User
from langboard_shared.domain.services.DomainService import DomainService
from langboard_shared.helpers import InfraHelper
from sqlalchemy import or_, select


KEY_PREFIX = "linked_wiki:"


def visible_linked_wikis(
    project: Project, card: Card, user: User | Bot, service: DomainService
) -> list[dict[str, str]]:
    metadata = service.metadata.get_all_as_api(CardMetadata, card, as_dict=True)
    wiki_uids = []
    for key in sorted(metadata):
        if not key.startswith(KEY_PREFIX) or metadata[key] != "1":
            continue
        wiki_uid = key[len(KEY_PREFIX) :]
        if re.fullmatch(r"[A-Za-z0-9]{1,24}", wiki_uid):
            wiki_uids.append(wiki_uid)
    if not wiki_uids:
        return []
    statement = SqlBuilder.select.columns(ProjectWiki.column("id"), ProjectWiki.column("title")).where(
        (ProjectWiki.column("project_id") == project.id)
        & ProjectWiki.column("deleted_at").is_(None)
        & ProjectWiki.column("id").in_([InfraHelper.convert_id(uid) for uid in wiki_uids])
    )
    if isinstance(user, User):
        if not user.is_admin:
            assigned = select(ProjectWikiAssignedUser.project_wiki_id).where(ProjectWikiAssignedUser.user_id == user.id)
            statement = statement.where(
                or_(ProjectWiki.column("is_public").is_(True), ProjectWiki.column("id").in_(assigned))
            )
    else:
        statement = statement.where(ProjectWiki.column("is_public").is_(True))
    # Read current grants from the primary database, including immediately after unlink/revoke.
    with DbSession.use(readonly=False) as db:
        rows = db.exec(statement).all()
    visible = {row[0].to_short_code(): row[1] for row in rows}
    return [{"wiki_uid": uid, "title": visible[uid]} for uid in wiki_uids if uid in visible]


def change_link(
    project: Project, card: Card, wiki_uid: str, action: str, user: User, service: DomainService
) -> list[dict[str, str]]:
    if card.is_linked_resource:
        raise ValueError("Linked resource cards cannot have wiki links")
    if action not in {"link", "unlink"}:
        raise ValueError("action must be link or unlink")
    wiki: ProjectWiki | None = service.project_wiki.get_by_id_like(wiki_uid)
    if wiki is None or wiki.project_id != project.id:
        raise ValueError("Wiki not found in project")
    if action == "link":
        if not service.project_wiki.is_assigned(user, wiki):
            raise ValueError("Wiki access denied")
        if service.metadata.save(CardMetadata, card, KEY_PREFIX + wiki.get_uid(), "1") is None:
            raise ValueError("Wiki link could not be saved")
    else:
        service.metadata.delete(CardMetadata, card, KEY_PREFIX + wiki.get_uid())
    return visible_linked_wikis(project, card, user, service)
