from langboard_shared.core.db import DbSession
from langboard_shared.core.types import SafeDateTime
from langboard_shared.domain.models import ProjectAssignedUser, User
from langboard_shared.domain.services.CardVisibilityPolicy import CardVisibility


def test_personal_board_defaults_private_and_live_membership_changes_default(current_card):
    actor, project, _, service = current_card
    assert service.default_creation_visibility(project, actor) == CardVisibility.Private
    with DbSession.use(readonly=False) as db:
        customer = User(firstname="Customer", lastname="External", email="fixture@example.invalid",
                        password="fixture", activated_at=SafeDateTime.now())
        db.insert(customer)
        db.insert(ProjectAssignedUser(project_id=project.id, user_id=customer.id))
    assert service.default_creation_visibility(project, actor) == CardVisibility.Internal
    assert service.default_creation_visibility(project, customer) == CardVisibility.Internal
    with DbSession.use(readonly=False) as db:
        customer.activated_at = None
        db.update(customer)
    assert service.default_creation_visibility(project, actor) == CardVisibility.Private
    assert service.default_creation_visibility(project, object()) == CardVisibility.Internal
