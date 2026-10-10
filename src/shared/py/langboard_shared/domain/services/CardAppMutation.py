"""App-exclusive cards reject unbound automation at native mutation services."""

from functools import wraps
from inspect import signature
from ...core.db import DbSession, SqlBuilder
from ...helpers import InfraHelper
from ..models import Bot, Card, CardAppOwnership, Project, User
from .AppGovernance import AppGovernanceDenied


def guard_card_app_mutation(operation):
    """Retain human service authorization; bots have no authenticated owner-app grant."""
    parameters = signature(operation)

    @wraps(operation)
    def guarded(*args, **kwargs):
        bound = parameters.bind(*args, **kwargs)
        actor = bound.arguments.get("user_or_bot", bound.arguments.get("user"))
        card = bound.arguments.get("card")
        # User-scoped REST/MCP retain their existing human permission checks.
        # Dedicated app credentials cannot authenticate as those users.
        if isinstance(actor, User) or card is None:
            return operation(*args, **kwargs)
        if not isinstance(actor, Bot):
            raise AppGovernanceDenied()
        with DbSession.atomic() as db:
            project = bound.arguments.get("project")
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
                    SqlBuilder.select.table(CardAppOwnership).where(
                        CardAppOwnership.card_id == current.id,
                    )
                ).first()
                if owner is not None and owner.app_key is not None:
                    # A bot's attributes, payload or readable card are not an app credential.
                    raise AppGovernanceDenied()
            return operation(*args, **kwargs)

    return guarded
