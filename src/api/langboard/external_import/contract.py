from datetime import datetime
from hashlib import sha256
from json import dumps
from pathlib import PurePosixPath
from typing import Annotated, Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator


SourceId = Annotated[str, Field(min_length=1, max_length=255)]
Content = Annotated[str, Field(max_length=1_000_000)]


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    def fingerprint(self) -> str:
        payload = self.model_dump(mode="json", exclude_none=True)
        return sha256(dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


class ImportSource(StrictModel):
    namespace: SourceId
    container_id: SourceId
    batch_id: SourceId


class ExternalColumn(StrictModel):
    source_id: SourceId
    name: Annotated[str, Field(min_length=1, max_length=255)]
    order: int = Field(ge=0)


class ExternalLabel(StrictModel):
    source_id: SourceId
    name: Annotated[str, Field(min_length=1, max_length=255)]
    color: str = Field(pattern=r"^#[0-9A-Fa-f]{6}$")
    description: str = ""
    order: int = Field(ge=0)


class ExternalCard(StrictModel):
    source_id: SourceId
    column_source_id: SourceId
    title: Annotated[str, Field(min_length=1, max_length=500)]
    description: Content = ""
    order: int = Field(ge=0)
    deadline_at: datetime | None = None
    label_source_ids: list[SourceId] = Field(default_factory=list)
    assignee_scim_external_ids: list[SourceId] = Field(default_factory=list)

    @model_validator(mode="after")
    def reject_duplicate_assignments(self):
        if len(self.label_source_ids) != len(set(self.label_source_ids)):
            raise ValueError("duplicate card label")
        if len(self.assignee_scim_external_ids) != len(set(self.assignee_scim_external_ids)):
            raise ValueError("duplicate card assignee")
        return self


class ExternalChecklist(StrictModel):
    source_id: SourceId
    card_source_id: SourceId
    title: Annotated[str, Field(min_length=1, max_length=255)]
    order: int = Field(ge=0)


class ExternalCheckitem(StrictModel):
    source_id: SourceId
    checklist_source_id: SourceId
    title: Annotated[str, Field(min_length=1, max_length=500)]
    order: int = Field(ge=0)
    is_checked: bool = False


class ExternalRelationship(StrictModel):
    source_id: SourceId
    parent_card_source_id: SourceId
    child_card_source_id: SourceId
    relationship_type_uid: SourceId


class ExternalComment(StrictModel):
    source_id: SourceId
    card_source_id: SourceId
    author_scim_external_id: SourceId
    created_at: datetime
    content: Annotated[str, Field(min_length=1, max_length=1_000_000)]


class ExternalAttachment(StrictModel):
    source_id: SourceId
    card_source_id: SourceId
    author_scim_external_id: SourceId
    created_at: datetime
    relative_path: SourceId
    original_filename: Annotated[str, Field(min_length=1, max_length=255)]
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size: int = Field(ge=0)

    @model_validator(mode="after")
    def reject_unsafe_path(self):
        path = PurePosixPath(self.relative_path)
        if path.is_absolute() or ".." in path.parts:
            raise ValueError("attachment path must stay below the attachments root")
        return self


class ExternalWorkBundle(StrictModel):
    schema_version: Literal["1"]
    source: ImportSource
    columns: list[ExternalColumn] = Field(default_factory=list, max_length=10_000)
    labels: list[ExternalLabel] = Field(default_factory=list, max_length=10_000)
    cards: list[ExternalCard] = Field(default_factory=list, max_length=10_000)
    checklists: list[ExternalChecklist] = Field(default_factory=list, max_length=10_000)
    checkitems: list[ExternalCheckitem] = Field(default_factory=list, max_length=10_000)
    relationships: list[ExternalRelationship] = Field(default_factory=list, max_length=10_000)
    comments: list[ExternalComment] = Field(default_factory=list, max_length=10_000)
    attachments: list[ExternalAttachment] = Field(default_factory=list, max_length=10_000)

    @model_validator(mode="after")
    def validate_references(self):
        collections = {
            "column": self.columns,
            "label": self.labels,
            "card": self.cards,
            "checklist": self.checklists,
            "checkitem": self.checkitems,
            "relationship": self.relationships,
            "comment": self.comments,
            "attachment": self.attachments,
        }
        ids: dict[str, set[str]] = {}
        for record_type, records in collections.items():
            source_ids = [record.source_id for record in records]
            if len(source_ids) != len(set(source_ids)):
                raise ValueError(f"duplicate {record_type} source_id")
            ids[record_type] = set(source_ids)

        for card in self.cards:
            self._require(ids["column"], card.column_source_id, "card column")
            for label_id in card.label_source_ids:
                self._require(ids["label"], label_id, "card label")
        for checklist in self.checklists:
            self._require(ids["card"], checklist.card_source_id, "checklist card")
        for checkitem in self.checkitems:
            self._require(ids["checklist"], checkitem.checklist_source_id, "checkitem checklist")
        for relationship in self.relationships:
            self._require(ids["card"], relationship.parent_card_source_id, "relationship parent")
            self._require(ids["card"], relationship.child_card_source_id, "relationship child")
            if relationship.parent_card_source_id == relationship.child_card_source_id:
                raise ValueError("relationship cannot connect a card to itself")
        for comment in self.comments:
            self._require(ids["card"], comment.card_source_id, "comment card")
        for attachment in self.attachments:
            self._require(ids["card"], attachment.card_source_id, "attachment card")

        edges = {(item.parent_card_source_id, item.child_card_source_id) for item in self.relationships}
        if len(edges) != len(self.relationships):
            raise ValueError("duplicate relationship edge")
        if self._has_cycle(edges):
            raise ValueError("relationships contain a cycle")
        return self

    @staticmethod
    def _require(known: set[str], value: str, label: str) -> None:
        if value not in known:
            raise ValueError(f"unknown {label}: {value}")

    @staticmethod
    def _has_cycle(edges: set[tuple[str, str]]) -> bool:
        children: dict[str, set[str]] = {}
        indegree: dict[str, int] = {}
        for parent, child in edges:
            children.setdefault(parent, set()).add(child)
            indegree.setdefault(parent, 0)
            indegree[child] = indegree.get(child, 0) + 1
        pending = [node for node, degree in indegree.items() if degree == 0]
        visited = 0
        while pending:
            node = pending.pop()
            visited += 1
            for child in children.get(node, set()):
                indegree[child] -= 1
                if indegree[child] == 0:
                    pending.append(child)
        return visited != len(indegree)

    def records(self):
        for record_type in (
            "column",
            "label",
            "card",
            "checklist",
            "checkitem",
            "relationship",
            "comment",
            "attachment",
        ):
            for record in getattr(self, f"{record_type}s"):
                yield record_type, record
