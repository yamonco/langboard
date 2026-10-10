from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator


class VerificationConflict(ValueError):
    """The card or its latest verification changed after the client read it."""


class VerificationEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    reference: str = Field(min_length=1, max_length=2048)
    source_revision: str = Field(min_length=1, max_length=128)
    environment: str = Field(min_length=1, max_length=128)
    checkitem_uid: str | None = Field(default=None, min_length=1, max_length=64)


class VerificationSubmission(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_change_seq: int = Field(ge=0)
    expected_record_uid: str | None = Field(default=None, min_length=1, max_length=64)
    decision: Literal["verified", "partial", "unverified"]
    evidence: list[VerificationEvidence] = Field(min_length=1, max_length=20)
    required_checkitem_uids: list[str] = Field(default_factory=list, max_length=100)

    @model_validator(mode="after")
    def validate_coverage(self):
        if len(set(self.required_checkitem_uids)) != len(self.required_checkitem_uids):
            raise ValueError("Required checkitems must be unique")
        if self.decision == "verified":
            evidence_items = {item.checkitem_uid for item in self.evidence}
            if None not in evidence_items or not set(self.required_checkitem_uids).issubset(evidence_items):
                raise ValueError("Verified requires card evidence and evidence for every declared required checkitem")
        return self
