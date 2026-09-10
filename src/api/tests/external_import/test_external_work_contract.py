from copy import deepcopy
from hashlib import sha256
import pytest
from langboard.commands.ImportExternalWorkCommand import (
    ImportExternalWorkCommand,
    ImportExternalWorkCommandOptions,
    load_bounded_bundle,
)
from langboard.external_import import ExternalWorkBundle
from langboard.external_import.importer import ExternalImportError, ExternalWorkImporter
from langboard_shared.core.storage import FileModel, Storage
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


def test_attachment_upload_reuses_a_deterministic_object_key(tmp_path, monkeypatch) -> None:
    content = b"safe"
    source_file = tmp_path / "card-1" / "document.txt"
    source_file.parent.mkdir()
    source_file.write_bytes(content)
    payload = bundle_payload()
    payload["attachments"][0].update(sha256=sha256(content).hexdigest(), size=len(content))
    bundle = ExternalWorkBundle.model_validate(payload)
    uploads: list[tuple[str, bytes]] = []

    def upload_named(_self, stream, storage_name, stored_filename, original_filename):
        uploads.append((stored_filename, stream.read()))
        return FileModel(
            storage_type="local",
            storage_name=storage_name.value,
            original_filename=original_filename,
            filename=stored_filename,
            path=f"/file/local/{storage_name.value}/{stored_filename}",
        )

    monkeypatch.setattr(type(Storage), "upload_named", upload_named)
    importer = ExternalWorkImporter(tmp_path)
    files = importer._verify_attachments(bundle.attachments)

    first = importer._upload_attachment("project-a", bundle, bundle.attachments[0], files)
    second = importer._upload_attachment("project-a", bundle, bundle.attachments[0], files)

    assert first.filename == second.filename
    assert uploads == [(first.filename, content), (first.filename, content)]

    other_project = importer._upload_attachment("project-b", bundle, bundle.attachments[0], files)
    assert other_project.filename != first.filename


def test_attachment_upload_and_compensation_fail_closed(tmp_path, monkeypatch) -> None:
    content = b"safe"
    source_file = tmp_path / "card-1" / "document.txt"
    source_file.parent.mkdir()
    source_file.write_bytes(content)
    payload = bundle_payload()
    payload["attachments"][0].update(sha256=sha256(content).hexdigest(), size=len(content))
    bundle = ExternalWorkBundle.model_validate(payload)
    importer = ExternalWorkImporter(tmp_path)
    files = importer._verify_attachments(bundle.attachments)

    monkeypatch.setattr(type(Storage), "upload_named", lambda *_args: None)
    with pytest.raises(ExternalImportError, match="attachment upload failed"):
        importer._upload_attachment("project-a", bundle, bundle.attachments[0], files)

    staged = FileModel(
        storage_type="local",
        storage_name="card_attachment",
        original_filename="document.txt",
        filename="stable.txt",
        path="/file/local/card_attachment/stable.txt",
    )
    monkeypatch.setattr(type(Storage), "delete", lambda *_args: False)
    with pytest.raises(ExternalImportError, match="failed to compensate"):
        importer._delete_staged_file(staged)


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


def test_bounded_bundle_loader_accepts_payload_at_limit(tmp_path) -> None:
    bundle_file = tmp_path / "bundle.json"
    payload = ExternalWorkBundle.model_validate(bundle_payload()).model_dump_json().encode()
    bundle_file.write_bytes(payload)

    loaded = load_bounded_bundle(bundle_file, max_bytes=len(payload))

    assert loaded.source.container_id == "project-1"


def test_bounded_bundle_loader_rejects_payload_over_limit(tmp_path) -> None:
    bundle_file = tmp_path / "bundle.json"
    payload = ExternalWorkBundle.model_validate(bundle_payload()).model_dump_json().encode()
    bundle_file.write_bytes(payload)

    with pytest.raises(ValueError, match="input limit"):
        load_bounded_bundle(bundle_file, max_bytes=len(payload) - 1)
