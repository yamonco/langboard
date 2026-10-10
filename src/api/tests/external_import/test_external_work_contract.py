from copy import deepcopy
from hashlib import sha256
import pytest
from langboard.commands.ImportExternalWorkCommand import ImportExternalWorkCommand, ImportExternalWorkCommandOptions
from langboard.external_import import ExternalWorkBundle
from langboard.external_import.importer import ExternalImportError, ExternalWorkImporter
from pydantic import ValidationError


def bundle_payload() -> dict:
    return {
        "schema_version": "1",
        "source": {"namespace": "tracker", "container_id": "project-1", "batch_id": "batch-1"},
        "columns": [{"source_id": "column-1", "name": "Backlog", "order": 0}],
        "labels": [
            {
                "source_id": "label-1",
                "name": "Important",
                "color": "#336699",
                "description": "Accepted by the source adapter",
                "order": 0,
            }
        ],
        "cards": [
            {
                "source_id": "card-1",
                "column_source_id": "column-1",
                "title": "Parent",
                "order": 0,
                "label_source_ids": ["label-1"],
            },
            {
                "source_id": "card-2",
                "column_source_id": "column-1",
                "title": "Child",
                "order": 1,
            },
        ],
        "checklists": [{"source_id": "checklist-1", "card_source_id": "card-1", "title": "Steps", "order": 0}],
        "checkitems": [
            {
                "source_id": "checkitem-1",
                "checklist_source_id": "checklist-1",
                "title": "Confirm",
                "order": 0,
            }
        ],
        "relationships": [
            {
                "source_id": "relationship-1",
                "parent_card_source_id": "card-1",
                "child_card_source_id": "card-2",
                "relationship_type_uid": "type-1",
            }
        ],
        "comments": [
            {
                "source_id": "comment-1",
                "card_source_id": "card-1",
                "author_scim_external_id": "person-1",
                "created_at": "2026-01-02T03:04:05Z",
                "content": "Historical comment",
            }
        ],
        "attachments": [
            {
                "source_id": "attachment-1",
                "card_source_id": "card-1",
                "author_scim_external_id": "person-1",
                "created_at": "2026-01-02T03:04:05Z",
                "relative_path": "card-1/document.txt",
                "original_filename": "document.txt",
                "sha256": "a" * 64,
                "size": 4,
            }
        ],
    }


def test_accepts_native_records_and_has_stable_fingerprints() -> None:
    first = ExternalWorkBundle.model_validate(bundle_payload())
    second = ExternalWorkBundle.model_validate(deepcopy(bundle_payload()))

    assert [(kind, item.fingerprint()) for kind, item in first.records()] == [
        (kind, item.fingerprint()) for kind, item in second.records()
    ]


@pytest.mark.parametrize(
    "mutate, message",
    [
        (lambda value: value["cards"].append(deepcopy(value["cards"][0])), "duplicate card source_id"),
        (lambda value: value["cards"][0].update(column_source_id="missing"), "unknown card column"),
        (
            lambda value: value["relationships"].append(
                {
                    "source_id": "relationship-2",
                    "parent_card_source_id": "card-2",
                    "child_card_source_id": "card-1",
                    "relationship_type_uid": "type-1",
                }
            ),
            "relationships contain a cycle",
        ),
        (lambda value: value["cards"][0].update(bot_comment_status="approved"), "Extra inputs are not permitted"),
        (lambda value: value["attachments"][0].update(relative_path="../secret"), "attachments root"),
    ],
)
def test_rejects_ambiguous_or_legacy_runtime_state(mutate, message: str) -> None:
    payload = bundle_payload()
    mutate(payload)

    with pytest.raises(ValidationError, match=message):
        ExternalWorkBundle.model_validate(payload)


def test_attachment_integrity_is_checked_before_database_access(tmp_path) -> None:
    content = b"safe"
    source_file = tmp_path / "card-1" / "document.txt"
    source_file.parent.mkdir()
    source_file.write_bytes(content)
    payload = bundle_payload()
    payload["attachments"][0].update(sha256=sha256(content).hexdigest(), size=len(content))
    bundle = ExternalWorkBundle.model_validate(payload)

    assert ExternalWorkImporter(tmp_path)._verify_attachments(bundle.attachments) == {"attachment-1": source_file}

    source_file.write_bytes(b"changed")
    with pytest.raises(ExternalImportError, match="integrity mismatch"):
        ExternalWorkImporter(tmp_path)._verify_attachments(bundle.attachments)


def test_attachment_bundle_requires_explicit_root() -> None:
    bundle = ExternalWorkBundle.model_validate(bundle_payload())

    with pytest.raises(ExternalImportError, match="attachments_root is required"):
        ExternalWorkImporter()._verify_attachments(bundle.attachments)


def test_import_command_namespace_can_be_constructed_before_argparse_populates_it() -> None:
    options = ImportExternalWorkCommandOptions()

    assert options.project_uid == ""
    assert options.actor_uid == ""


@pytest.mark.parametrize(
    ("options", "message"),
    [
        (ImportExternalWorkCommandOptions(actor_uid="actor"), "--project-uid is required"),
        (ImportExternalWorkCommandOptions(project_uid="project"), "--actor-uid is required"),
    ],
)
def test_import_command_rejects_missing_scope_before_reading_bundle(options, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        ImportExternalWorkCommand().execute("missing.json", options)
