"""Typed content and verification responses; receipts never imply approval."""

from typing import Annotated, Literal
from pydantic import Field
from .Outputs import CommandOutput


class CodePayloadOutput(CommandOutput):
    language: str
    source: str
    title: str | None


class DiagramPayloadOutput(CommandOutput):
    engine: Literal["mermaid", "plantuml", "graphviz", "flowchart"]
    source: str
    view_mode: Literal["source", "rendered", "both"]


class RichTextPayloadOutput(CommandOutput):
    text: str


class ContentBlockOutput(CommandOutput):
    block_uid: str
    order: int = Field(ge=0)
    revision: int = Field(ge=1)
    updated_at: str | None


class CodeBlockOutput(ContentBlockOutput):
    type: Literal["code"]
    payload: CodePayloadOutput


class DiagramBlockOutput(ContentBlockOutput):
    type: Literal["diagram"]
    payload: DiagramPayloadOutput


class RichTextBlockOutput(ContentBlockOutput):
    type: Literal["rich_text"]
    payload: RichTextPayloadOutput


class ContentBlockMutationOutput(CommandOutput):
    content_block: Annotated[CodeBlockOutput | DiagramBlockOutput | RichTextBlockOutput, Field(discriminator="type")]


class EvidenceOutput(CommandOutput):
    reference: str
    source_revision: str
    environment: str
    checkitem_uid: str | None


class VerificationRecordOutput(CommandOutput):
    uid: str
    source_change_seq: int = Field(ge=0)
    decision: Literal["verified", "partial", "unverified"]
    recorded_at: str
    recorded_by_user_uid: str | None
    recorded_by_bot_uid: str | None
    evidence: list[EvidenceOutput]
    required_checkitem_uids: list[str]


class VerificationMutationOutput(CommandOutput):
    verification: VerificationRecordOutput


CONTENT_OUTPUTS = {
    "create_card_content_block": ContentBlockMutationOutput,
    "update_card_content_block": ContentBlockMutationOutput,
    "record_card_verification_evidence": VerificationMutationOutput,
}
