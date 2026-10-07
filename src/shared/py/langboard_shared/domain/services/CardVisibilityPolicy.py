"""Card and whisper decisions from server-verified, project-scoped facts.

Callers must resolve membership and audience consistently before constructing
this context. A User reached through MCP or an API key is not a human UI actor.
"""

from collections.abc import Collection
from dataclasses import dataclass
from enum import Enum
from ...core.security.CollaborationChannel import CollaborationChannel as CollaborationChannel


class CardVisibility(str, Enum):
    Internal = "INTERNAL"
    Shared = "SHARED"
    Private = "PRIVATE"


@dataclass(frozen=True)
class CardVisibilityContext:
    channel: CollaborationChannel
    active: bool
    project_member: bool
    internal_member: bool | None
    can_update_card: bool = False
    actor_user_id: int | None = None

    @property
    def can_read_internal(self) -> bool:
        return self.active is True and self.project_member is True and self.internal_member is True

    def is_private_owner(self, owner_user_id: int | None) -> bool:
        return (
            self.active is True
            and self.project_member is True
            and self.channel in (CollaborationChannel.HumanUI, CollaborationChannel.Mcp)
            and _valid_user_id(self.actor_user_id)
            and _valid_user_id(owner_user_id)
            and self.actor_user_id == owner_user_id
        )

    def can_read_card(self, visibility: CardVisibility, *, owner_user_id: int | None = None) -> bool:
        if self.active is not True or self.project_member is not True:
            return False
        if visibility == CardVisibility.Private:
            return self.is_private_owner(owner_user_id)
        if visibility == CardVisibility.Internal:
            return self.can_read_internal
        return visibility == CardVisibility.Shared

    @property
    def can_use_whisper(self) -> bool:
        return self.channel == CollaborationChannel.HumanUI and self.can_read_internal

    def can_use_card_whisper(self, visibility: CardVisibility) -> bool:
        return visibility in (CardVisibility.Internal, CardVisibility.Shared) and self.can_use_whisper

    def can_link_cards(
        self,
        source: CardVisibility,
        target: CardVisibility,
        *,
        source_owner_user_id: int | None = None,
        target_owner_user_id: int | None = None,
    ) -> bool:
        if not self.can_read_card(source, owner_user_id=source_owner_user_id) or not self.can_read_card(
            target, owner_user_id=target_owner_user_id
        ):
            return False
        if CardVisibility.Private in (source, target):
            return source == target == CardVisibility.Private and source_owner_user_id == target_owner_user_id
        return True

    def can_change_visibility(
        self, current: CardVisibility, target: CardVisibility, *, confirmed: bool = False
    ) -> bool:
        # PRIVATE is a creation-only choice, including for the owner and MCP.
        if CardVisibility.Private in (current, target):
            return False
        if not self.can_read_internal or self.can_update_card is not True:
            return False
        if current not in (CardVisibility.Internal, CardVisibility.Shared) or target not in (
            CardVisibility.Internal,
            CardVisibility.Shared,
        ):
            return False
        if current == target:
            return True
        if target == CardVisibility.Shared:
            return self.channel == CollaborationChannel.HumanUI and confirmed is True
        return target == CardVisibility.Internal


DEFAULT_CARD_VISIBILITY = CardVisibility.Internal


def _valid_user_id(value: int | None) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def default_card_visibility(actor_user_id: int | None, participant_user_ids: Collection[int] | None) -> CardVisibility:
    """Use only the current server-resolved participant snapshot at creation.

    Unknown membership never creates an ownerless personal vault. Existing
    cards must not be passed through this default when participants change.
    """
    if (
        _valid_user_id(actor_user_id)
        and participant_user_ids is not None
        and all(_valid_user_id(user_id) for user_id in participant_user_ids)
        and set(participant_user_ids) == {actor_user_id}
    ):
        return CardVisibility.Private
    return DEFAULT_CARD_VISIBILITY
