"""Card and whisper decisions from server-verified, project-scoped facts.

Callers must resolve membership and audience consistently before constructing
this context. A User reached through MCP or an API key is not a human UI actor.
"""

from dataclasses import dataclass
from enum import Enum


class CardVisibility(str, Enum):
    Internal = "INTERNAL"
    Shared = "SHARED"


class CollaborationChannel(str, Enum):
    HumanUI = "human_ui"
    Mcp = "mcp"
    Api = "api"
    Bot = "bot"


@dataclass(frozen=True)
class CardVisibilityContext:
    channel: CollaborationChannel
    active: bool
    project_member: bool
    internal_member: bool | None
    can_update_card: bool = False

    @property
    def can_read_internal(self) -> bool:
        return self.active is True and self.project_member is True and self.internal_member is True

    def can_read_card(self, visibility: CardVisibility) -> bool:
        if self.active is not True or self.project_member is not True:
            return False
        if visibility == CardVisibility.Internal:
            return self.can_read_internal
        return visibility == CardVisibility.Shared

    @property
    def can_use_whisper(self) -> bool:
        return self.channel == CollaborationChannel.HumanUI and self.can_read_internal

    def can_change_visibility(
        self, current: CardVisibility, target: CardVisibility, *, confirmed: bool = False
    ) -> bool:
        if not self.can_read_internal or self.can_update_card is not True:
            return False
        if current not in (CardVisibility.Internal, CardVisibility.Shared) or target not in (
            CardVisibility.Internal, CardVisibility.Shared
        ):
            return False
        if current == target:
            return True
        if target == CardVisibility.Shared:
            return self.channel == CollaborationChannel.HumanUI and confirmed is True
        return target == CardVisibility.Internal


DEFAULT_CARD_VISIBILITY = CardVisibility.Internal
