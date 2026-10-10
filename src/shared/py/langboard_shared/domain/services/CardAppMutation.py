"""App-exclusive cards reject unbound automation at native mutation services."""

from functools import wraps
from inspect import signature
from ...core.db import DbSession, SqlBuilder
from ...helpers import InfraHelper
from ..models import Bot, Card, CardAppOwnership, InternalBot, Project, User
from .AppGovernance import AppGovernanceDenied


def require_card_app_mutation(db: DbSession, actor: User | Bot | InternalBot, card, project=None) -> None:
    """Fence direct writers in their existing transaction before side effects."""
    if isinstance(actor, User):
        return
    if not isinstance(actor, (Bot, InternalBot)):
        raise AppGovernanceDenied()
    if project is not None:
        db.exec(
            SqlBuilder.select.table(Project)
            .where(Project.id == InfraHelper.convert_id(project))
            .with_for_update()
        ).first()
    current = db.exec(
        SqlBuilder.select.table(Card).where(Card.id == InfraHelper.convert_id(card)).with_for_update()
    ).first()
    if current is not None:
        owner = db.exec(
            SqlBuilder.select.table(CardAppOwnership).where(CardAppOwnership.card_id == current.id)
        ).first()
        if owner is not None and owner.app_key is not None:
            # Bot attributes and payloads are not authenticated app authority.
            raise AppGovernanceDenied()


def guard_card_app_mutation(operation):
    """Retain human service authorization; bots have no authenticated owner-app grant."""
    parameters = signature(operation)

    @wraps(operation)
    def guarded(*args, **kwargs):
        bound = parameters.bind(*args, **kwargs)
        actor = bound.arguments.get("user_or_bot", bound.arguments.get("user"))
        card = bound.arguments.get("card", bound.arguments.get("parent_card"))
        # User-scoped REST/MCP retain their existing human permission checks.
        # Dedicated app credentials cannot authenticate as those users.
        if isinstance(actor, User) or card is None:
            return operation(*args, **kwargs)
        if not isinstance(actor, Bot):
            raise AppGovernanceDenied()
        with DbSession.atomic() as db:
            project = bound.arguments.get("project")
            require_card_app_mutation(db, actor, card, project)
            return operation(*args, **kwargs)

    return guarded
