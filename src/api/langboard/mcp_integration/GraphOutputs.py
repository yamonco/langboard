"""Typed native graph mutation results; transaction ownership stays in domain."""

from datetime import datetime
from .CreationOutputs import NativeCardCreationOutput
from .Outputs import CommandOutput


class CreatedRelationshipOutput(CommandOutput):
    uid: str
    created_at: datetime | str | None
    updated_at: datetime | str | None
    relationship_type_uid: str
    parent_card_uid: str
    child_card_uid: str


class GraphPatchOutput(CommandOutput):
    anchor_card_uid: str
    created_cards: list[NativeCardCreationOutput]
    created_relationships: list[CreatedRelationshipOutput]
    removed_relationship_uids: list[str]


GRAPH_OUTPUTS = {"apply_card_graph_patch": GraphPatchOutput}
