"""Card to wiki links backed by one metadata row per wiki.

Keep authorization at read time: a link never grants access to a private wiki.
"""

import re
from langboard_shared.domain.models import Bot, Card, CardMetadata, Project, ProjectWiki, User
from langboard_shared.domain.services.DomainService import DomainService


KEY_PREFIX = "linked_wiki:"


def visible_linked_wikis(
    project: Project, card: Card, user: User | Bot, service: DomainService
) -> list[dict[str, str]]:
    metadata = service.metadata.get_all_as_api(CardMetadata, card, as_dict=True)
    links = []
    for key in sorted(metadata):
        if not key.startswith(KEY_PREFIX) or metadata[key] != "1":
            continue
        wiki_uid = key[len(KEY_PREFIX) :]
        if not re.fullmatch(r"[A-Za-z0-9]{1,24}", wiki_uid):
            continue
        wiki = service.project_wiki.get_by_id_like(wiki_uid)
        if wiki is None or wiki.project_id != project.id:
            continue
        if isinstance(user, User) and not service.project_wiki.is_assigned(user, wiki):
            continue
        if isinstance(user, Bot) and not wiki.is_public:
            continue
        links.append({"wiki_uid": wiki.get_uid(), "title": wiki.title})
    return links


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
