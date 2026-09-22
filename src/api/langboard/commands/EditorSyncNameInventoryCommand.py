"""Match stored Yjs hashes to names derived from existing domain records.

Run against the database snapshot taken with the editor-sync volume backup.
Unknown hashes are reported, never guessed or excluded from the restore audit.
"""

import argparse
import hashlib
import json
from collections.abc import Iterator
from pathlib import Path
from typing import cast
from langboard_shared.core.db import BaseDbModel, DbSession, SqlBuilder
from langboard_shared.core.routing import EEditorCollaborationType, create_editor_collaboration_document_id
from langboard_shared.core.types import SnowflakeID
from langboard_shared.domain.models import (
    ApiComfortTool,
    Bot,
    Card,
    CardAttachment,
    CardBotSchedule,
    CardComment,
    CardMetadata,
    ChatTemplate,
    Checkitem,
    Checklist,
    GlobalCardRelationshipType,
    InternalBot,
    McpToolGroup,
    NotificationScheduleRule,
    Project,
    ProjectBotSchedule,
    ProjectColumn,
    ProjectColumnBotSchedule,
    ProjectLabel,
    ProjectWiki,
    ProjectWikiMetadata,
    User,
    WebhookSetting,
)
from langboard_shared.domain.models.InternalBot import InternalBotType


PAGE_SIZE = 250


def _uid(value: int) -> str:
    return SnowflakeID(value).to_short_code()


def _rows(
    db: DbSession,
    model: type[BaseDbModel],
    *fields: str,
    relation: tuple[type[BaseDbModel], str, tuple[str, ...]] | None = None,
) -> Iterator[tuple[object, ...]]:
    id_column = model.column("id", SnowflakeID)
    columns = [id_column, *(model.column(field) for field in fields)]
    if relation is not None:
        parent, _, parent_fields = relation
        columns.extend(parent.column(field) for field in parent_fields)
    cursor = 0
    while True:
        statement = SqlBuilder.select.columns(*columns, with_deleted=True)
        if relation is not None:
            parent, foreign_key, _ = relation
            statement = statement.join(
                parent,
                model.column(foreign_key, SnowflakeID) == parent.column("id", SnowflakeID),
            )
        statement = statement.where(id_column > cursor).order_by(id_column).limit(PAGE_SIZE)
        page = db.exec(statement).all()
        if not page:
            return
        for row in page:
            values = tuple(row)
            if not isinstance(values[0], int):
                raise ValueError(f"Unexpected ID in {model.__name__}")
            cursor = values[0]
            yield values


def _candidates(db: DbSession) -> Iterator[str]:
    simple = (
        (
            Card,
            EEditorCollaborationType.Card,
            (
                "title",
                "description",
                "deadline",
                "members",
                "labels",
                "relationships-parents",
                "relationships-children",
            ),
        ),
        (Project, EEditorCollaborationType.BoardSettings, (None, "members")),
        (ProjectWiki, EEditorCollaborationType.Wiki, ("title", "content", "private-assignees")),
        (User, EEditorCollaborationType.AppSettings, ("user",)),
        (Bot, EEditorCollaborationType.AppSettings, ("bot", "bot-value")),
        (InternalBot, EEditorCollaborationType.AppSettings, ("internal-bot", "internal-bot-value")),
        (McpToolGroup, EEditorCollaborationType.AppSettings, ("mcp-tool-group",)),
        (WebhookSetting, EEditorCollaborationType.AppSettings, ("webhook",)),
        (NotificationScheduleRule, EEditorCollaborationType.AppSettings, ("notification-schedule-rule",)),
        (GlobalCardRelationshipType, EEditorCollaborationType.AppSettings, ("global-relationship",)),
    )
    for model, collaboration_type, sections in simple:
        for (record_id,) in _rows(db, model):
            if not isinstance(record_id, int):
                raise ValueError(f"Unexpected ID in {model.__name__}")
            for section in sections:
                yield create_editor_collaboration_document_id(collaboration_type, _uid(record_id), section)
            if model is Project:
                for bot_type in InternalBotType:
                    yield create_editor_collaboration_document_id(
                        EEditorCollaborationType.BoardSettings,
                        _uid(record_id),
                        f"internal-bot-prompt-{bot_type.value}",
                    )

    card_children = (
        (CardComment, "comment-"),
        (CardAttachment, "attachment-"),
        (Checklist, "checklist-"),
    )
    for model, prefix in card_children:
        for record_id, card_id in _rows(db, model, "card_id"):
            if isinstance(record_id, int) and isinstance(card_id, int):
                yield create_editor_collaboration_document_id(
                    EEditorCollaborationType.Card, _uid(card_id), f"{prefix}{_uid(record_id)}"
                )

    for checkitem_id, card_id in _rows(db, Checkitem, relation=(Checklist, "checklist_id", ("card_id",))):
        if not isinstance(checkitem_id, int) or not isinstance(card_id, int):
            continue
        section = f"checkitem-{_uid(checkitem_id)}"
        yield create_editor_collaboration_document_id(EEditorCollaborationType.Card, _uid(card_id), section)
        yield create_editor_collaboration_document_id(
            EEditorCollaborationType.Card, _uid(card_id), f"{section}-deadline"
        )

    for _, card_id, key in _rows(db, CardMetadata, "card_id", "key"):
        if isinstance(card_id, int) and isinstance(key, str):
            yield create_editor_collaboration_document_id(
                EEditorCollaborationType.Card, _uid(card_id), f"metadata-{key}"
            )
    for _, wiki_id, key in _rows(db, ProjectWikiMetadata, "project_wiki_id", "key"):
        if isinstance(wiki_id, int) and isinstance(key, str):
            yield create_editor_collaboration_document_id(
                EEditorCollaborationType.Wiki, _uid(wiki_id), f"metadata-{key}"
            )

    for label_id, project_id in _rows(db, ProjectLabel, "project_id"):
        if isinstance(label_id, int) and isinstance(project_id, int):
            yield create_editor_collaboration_document_id(
                EEditorCollaborationType.BoardSettings, _uid(project_id), f"label-{_uid(label_id)}"
            )
    for template_id, table, project_id in _rows(db, ChatTemplate, "filterable_table", "filterable_id"):
        if isinstance(template_id, int) and table == "project" and isinstance(project_id, int):
            yield create_editor_collaboration_document_id(
                EEditorCollaborationType.BoardSettings, _uid(project_id), f"chat-template-{_uid(template_id)}"
            )
    for column_id, project_id in _rows(db, ProjectColumn, "project_id"):
        if isinstance(column_id, int) and isinstance(project_id, int):
            yield create_editor_collaboration_document_id(
                EEditorCollaborationType.BoardColumnName, _uid(project_id), _uid(column_id)
            )
    for _, name in _rows(db, ApiComfortTool, "name"):
        if isinstance(name, str):
            yield create_editor_collaboration_document_id(
                EEditorCollaborationType.AppSettings, name, "api-comfort-tool"
            )

    for _, project_id, schedule_id in _rows(db, ProjectBotSchedule, "project_id", "bot_schedule_id"):
        if isinstance(project_id, int) and isinstance(schedule_id, int):
            project_uid = _uid(project_id)
            yield create_editor_collaboration_document_id(
                EEditorCollaborationType.BotSchedule, project_uid, f"project-{project_uid}-{_uid(schedule_id)}"
            )
    for _, card_id, schedule_id, project_id in _rows(
        db, CardBotSchedule, "card_id", "bot_schedule_id", relation=(Card, "card_id", ("project_id",))
    ):
        if isinstance(card_id, int) and isinstance(schedule_id, int) and isinstance(project_id, int):
            yield create_editor_collaboration_document_id(
                EEditorCollaborationType.BotSchedule,
                _uid(project_id),
                f"card-{_uid(card_id)}-{_uid(schedule_id)}",
            )
    for _, column_id, schedule_id, project_id in _rows(
        db,
        ProjectColumnBotSchedule,
        "project_column_id",
        "bot_schedule_id",
        relation=(ProjectColumn, "project_column_id", ("project_id",)),
    ):
        if isinstance(column_id, int) and isinstance(schedule_id, int) and isinstance(project_id, int):
            yield create_editor_collaboration_document_id(
                EEditorCollaborationType.BotSchedule,
                _uid(project_id),
                f"project_column-{_uid(column_id)}-{_uid(schedule_id)}",
            )


def inventory(source: Path, db: DbSession) -> tuple[list[str], list[str]]:
    file_names = {file.name for file in source.iterdir()}
    matched: dict[str, str] = {}
    for name in _candidates(db):
        file_name = f"{hashlib.sha256(name.encode('utf-8')).hexdigest()}.ydoc"
        if file_name in file_names:
            matched[file_name] = name
    return sorted(matched.values()), sorted(file_names - matched.keys())


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    _ = parser.add_argument(
        "source", type=Path, help="Editor-sync directory from the same backup as the database snapshot"
    )
    _ = parser.add_argument("output", type=Path, help="JSON document-name list outside the editor-sync directory")
    args = parser.parse_args()
    source = cast(Path, args.source).resolve()
    output = cast(Path, args.output).resolve()
    if not source.is_dir() or output.parent == source:
        parser.error("Source must exist and the output must be outside the editor-sync directory")
    with DbSession.use(readonly=True) as db:
        names, unknown = inventory(source, db)
    output.write_text(json.dumps(names, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"matched": len(names), "unmapped_source_files": unknown}, indent=2))
    return 0 if not unknown else 1


if __name__ == "__main__":
    raise SystemExit(main())
