"""Additive assignment command boundaries; persistence concurrency is tested by its repository."""

from types import SimpleNamespace
from unittest.mock import Mock, patch
import pytest
from .CardService import CardService


MODULE = "langboard_shared.domain.services.factory.CardService"


def make_command(changed: bool = True):
    actor = SimpleNamespace(id=1)
    assignee = SimpleNamespace(id=2, deleted_at=None, activated_at=object(), get_uid=lambda: "member")
    existing = SimpleNamespace(id=3, get_uid=lambda: "existing")
    project, card, membership = object(), object(), object()
    assignments = SimpleNamespace(
        get_all_by_card=Mock(side_effect=[[(3, object())], [(existing, object()), (assignee, object())]]),
        add_member=Mock(return_value=changed),
    )
    repo = SimpleNamespace(
        project_assigned_user=SimpleNamespace(find_by_user_and_project=Mock(return_value=membership)),
        card_assigned_user=assignments,
    )
    service = CardService(lambda _: None, lambda _: None, repo)
    return service, actor, assignee, project, card, repo


@pytest.mark.parametrize("changed", [True, False])
def test_add_member_preserves_canonical_assignees_and_replay_emits_nothing(changed: bool):
    service, actor, assignee, project, card, repo = make_command(changed)
    notification = Mock()
    with (
        patch(f"{MODULE}.InfraHelper.get_records_with_foreign_by_params", return_value=(project, card)),
        patch(f"{MODULE}.InfraHelper.get_by_id_like", return_value=assignee),
        patch(f"{MODULE}.CardPublisher.assigned_users_updated") as publish,
        patch(f"{MODULE}.CardActivityTask.card_assigned_users_updated") as activity,
        patch.object(service, "_get_service", return_value=notification),
    ):
        assert service.assign_member(actor, "project", "card", "member") == {
            "changed": changed,
            "member_uids": ["existing", "member"],
        }
    repo.card_assigned_user.add_member.assert_called_once_with(
        card, repo.project_assigned_user.find_by_user_and_project.return_value
    )
    assert publish.call_count == activity.call_count == notification.notify_assigned_to_card.call_count == int(changed)
    if changed:
        notification.notify_assigned_to_card.assert_called_once_with(actor, assignee, project, card)
        activity.assert_called_once_with(actor, project, card, [3], [3, 2])


@pytest.mark.parametrize("invalid", ["absent", "deleted", "inactive", "nonmember"])
def test_unassignable_target_never_writes_or_creates_membership(invalid: str):
    service, actor, assignee, project, card, repo = make_command()
    if invalid == "deleted":
        assignee.deleted_at = object()
    if invalid == "inactive":
        assignee.activated_at = None
    if invalid == "nonmember":
        repo.project_assigned_user.find_by_user_and_project.return_value = None
    with (
        patch(f"{MODULE}.InfraHelper.get_records_with_foreign_by_params", return_value=(project, card)),
        patch(f"{MODULE}.InfraHelper.get_by_id_like", return_value=None if invalid == "absent" else assignee),
        pytest.raises(ValueError, match="active member"),
    ):
        service.assign_member(actor, "project", "card", "member")
    repo.card_assigned_user.add_member.assert_not_called()
    repo.card_assigned_user.get_all_by_card.assert_not_called()


def test_foreign_card_is_rejected_before_directory_lookup():
    service, actor, _, _, _, repo = make_command()
    with (
        patch(f"{MODULE}.InfraHelper.get_records_with_foreign_by_params", return_value=None),
        patch(f"{MODULE}.InfraHelper.get_by_id_like") as lookup,
        pytest.raises(LookupError),
    ):
        service.assign_member(actor, "project", "foreign-card", "member")
    lookup.assert_not_called()
    repo.card_assigned_user.add_member.assert_not_called()
