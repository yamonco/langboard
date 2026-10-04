import hashlib
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
import pytest
from langboard.commands.ValidatePhoenixCutoverEvidenceCommand import (
    EvidenceValidationError,
    main,
    validate,
    validate_editor_manifest,
)


CHECKSUM = "a" * 64
DOCUMENT_NAME = "card:known:description"
FILE_NAME = f"{hashlib.sha256(DOCUMENT_NAME.encode('utf-8')).hexdigest()}.ydoc"
DOCUMENT_BYTES = b"\x00\x00"
DOCUMENT_CHECKSUM = hashlib.sha256(DOCUMENT_BYTES).hexdigest()
RUNTIME_IMAGE = f"sha256:{CHECKSUM}"


def _write_json(path: Path, value: dict[str, Any]) -> Path:
    _ = path.write_text(json.dumps(value), encoding="utf-8")
    return path


def _manifest(tmp_path: Path) -> dict[str, Any]:
    source = tmp_path / "editor-source"
    destination = tmp_path / "editor-restore"
    source.mkdir()
    destination.mkdir()
    _ = (source / FILE_NAME).write_bytes(DOCUMENT_BYTES)
    _ = (destination / FILE_NAME).write_bytes(DOCUMENT_BYTES)
    return {
        "format_version": 2,
        "generated_at": "2026-09-19T16:40:54Z",
        "source_directory": str(source),
        "destination_directory": str(destination),
        "verified": True,
        "documents": [
            {
                "document_name": DOCUMENT_NAME,
                "file_name": FILE_NAME,
                "source_checksum": DOCUMENT_CHECKSUM,
                "destination_checksum": DOCUMENT_CHECKSUM,
                "source_bytes": len(DOCUMENT_BYTES),
                "restore_status": "verified",
            }
        ],
        "opaque_documents": [],
        "unmapped_source_files": [],
        "unmapped_destination_files": [],
    }


def test_accepts_opaque_only_editor_restore_without_guessing_names(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path)
    document = manifest["documents"].pop()
    del document["document_name"]
    manifest["opaque_documents"].append(document)

    assert validate_editor_manifest(manifest) == 1


def _soak() -> tuple[dict[str, Any], list[dict[str, Any]]]:
    started_at = datetime(2026, 9, 18, tzinfo=UTC)
    finished_at = started_at + timedelta(hours=24)
    samples = [
        {
            "captured_at": (started_at + timedelta(hours=hour)).isoformat(),
            "memory_total": 1000,
            "runtime_uptime_seconds": 5000 + hour * 3600,
            "mailbox_total": 2,
            "mailbox_max": 1,
            "sockets": 2,
            "outbound_queue_length": 0,
            "slow_client_queue_length": 0,
            "editor_authorization_requests": hour * 100,
            "editor_authorization_errors": 0,
            "editor_authorization_duration_microseconds": hour * 100_000,
            "workers": {"board_chat": 1, "editor_ai": 0, "editor_document": 0},
            "worker_availability": {"board_chat": 1, "editor_ai": 1, "editor_document": 1},
            "tasks": {"command": 1, "graph_stream": 0},
            "task_availability": {"command": 1, "graph_stream": 1},
            "scrape_up": 1,
            "accepted_spans": hour + 1,
            "exported_spans": hour + 1,
            "export_failed_spans": 0,
            "export_enqueue_failed_spans": 0,
            "accepted_metric_points": hour + 1,
            "failed_spans": 0,
            "refused_spans": 0,
            "failed_metric_points": 0,
            "refused_metric_points": 0,
        }
        for hour in range(25)
    ]
    report = {
        "format_version": 5,
        "evidence_type": "phoenix_otel_soak",
        "runtime_image": RUNTIME_IMAGE,
        "started_at": started_at.isoformat(),
        "finished_at": finished_at.isoformat(),
        "duration_seconds": 24 * 60 * 60,
        "warmup_seconds": 0,
        "sample_interval_seconds": 60 * 60,
        "sample_count": len(samples),
        "raw_sample_count": len(samples),
        "samples_file": "soak.samples.jsonl",
        "samples_sha256": "",
        "thresholds": {
            "memory_peak_bytes": 1500,
            "memory_growth_bytes": 100,
            "memory_slope_bytes_per_hour": 10,
            "mailbox_total": 10,
            "mailbox_max": 5,
            "outbound_queue_length": 5,
            "slow_client_queue_length": 5,
            "editor_authorization_error_ratio": 0.01,
            "editor_authorization_average_microseconds": 5000,
            "worker_active": {"board_chat": 2, "editor_ai": 2, "editor_document": 2},
            "task_active": {"command": 2, "graph_stream": 2},
        },
        "load_profile": {
            "profile_id": "production-peak-x1",
            "source": "measured production peak",
            "measured_at": "2026-09-17T00:00:00+00:00",
            "target_sockets": 2,
            "minimum_editor_authorization_requests": 2000,
            "required_worker_activity": ["board_chat"],
            "required_task_activity": ["command"],
            "observed_peak_sockets": 2,
        },
        "observations": {
            "memory_start_bytes": 1000,
            "memory_end_bytes": 1000,
            "memory_max_bytes": 1000,
            "memory_growth_bytes": 0,
            "memory_slope_bytes_per_hour": 0,
            "runtime_uptime_start_seconds": 5000,
            "runtime_uptime_end_seconds": 5000 + 24 * 3600,
            "mailbox_total_max": 2,
            "mailbox_max_max": 1,
            "outbound_queue_length_max": 0,
            "slow_client_queue_length_max": 0,
            "sockets_max": 2,
            "editor_authorization_requests_observed": 2400,
            "editor_authorization_errors_observed": 0,
            "editor_authorization_error_ratio": 0,
            "editor_authorization_average_microseconds": 1000,
            "worker_active_max": {"board_chat": 1, "editor_ai": 0, "editor_document": 0},
            "task_active_max": {"command": 1, "graph_stream": 0},
            "accepted_spans_end": 25,
            "exported_spans_end": 25,
            "accepted_metric_points_end": 25,
        },
        "representative_load": True,
        "telemetry_healthy": True,
        "runtime_continuity": True,
        "bounded": {
            "memory": True,
            "mailboxes": True,
            "buffers": True,
            "authorization": True,
            "task_registries": True,
        },
        "rollback_triggers": [],
        "success": True,
    }
    return report, samples


def _write_soak(tmp_path: Path, report: dict[str, Any], samples: list[dict[str, Any]]) -> Path:
    samples_path = tmp_path / report["samples_file"]
    content = "".join(json.dumps(sample, separators=(",", ":"), sort_keys=True) + "\n" for sample in samples)
    _ = samples_path.write_text(content, encoding="utf-8")
    report["samples_sha256"] = hashlib.sha256(samples_path.read_bytes()).hexdigest()
    return _write_json(tmp_path / "soak.json", report)


def test_accepts_verified_restore_and_24_hour_otel_soak(tmp_path: Path) -> None:
    soak, samples = _soak()
    result = validate(
        _write_json(tmp_path / "manifest.json", _manifest(tmp_path)),
        _write_soak(tmp_path, soak, samples),
        RUNTIME_IMAGE,
    )

    assert result == (1, 24 * 60 * 60)


def test_rejects_old_soak_without_trace_export_evidence(tmp_path: Path) -> None:
    soak, samples = _soak()
    soak["format_version"] = 4

    with pytest.raises(EvidenceValidationError, match="format-version 5"):
        validate(
            _write_json(tmp_path / "manifest.json", _manifest(tmp_path)),
            _write_soak(tmp_path, soak, samples),
            RUNTIME_IMAGE,
        )


def test_rejects_spans_received_but_not_exported(tmp_path: Path) -> None:
    soak, samples = _soak()
    for sample in samples:
        sample["exported_spans"] = 0
    soak["observations"]["exported_spans_end"] = 0

    with pytest.raises(EvidenceValidationError, match="health result"):
        validate(
            _write_json(tmp_path / "manifest.json", _manifest(tmp_path)),
            _write_soak(tmp_path, soak, samples),
            RUNTIME_IMAGE,
        )


def test_rejects_24_hour_soak_with_one_hour_warmup(tmp_path: Path) -> None:
    soak, samples = _soak()
    soak["warmup_seconds"] = 60 * 60
    soak["sample_count"] = len(samples) - 1
    soak["observations"]["runtime_uptime_start_seconds"] += 60 * 60
    soak["observations"]["editor_authorization_requests_observed"] -= 100

    with pytest.raises(EvidenceValidationError, match="24 hours after warm-up"):
        validate(
            _write_json(tmp_path / "manifest.json", _manifest(tmp_path)),
            _write_soak(tmp_path, soak, samples),
            RUNTIME_IMAGE,
        )


def test_accepts_24_hours_after_one_hour_warmup(tmp_path: Path) -> None:
    soak, samples = _soak()
    last_sample = dict(samples[-1])
    last_sample["captured_at"] = (datetime.fromisoformat(soak["finished_at"]) + timedelta(hours=1)).isoformat()
    last_sample["runtime_uptime_seconds"] += 60 * 60
    last_sample["editor_authorization_requests"] += 100
    last_sample["editor_authorization_duration_microseconds"] += 100_000
    last_sample["accepted_spans"] += 1
    last_sample["exported_spans"] += 1
    last_sample["accepted_metric_points"] += 1
    samples.append(last_sample)
    soak["finished_at"] = last_sample["captured_at"]
    soak["duration_seconds"] = 25 * 60 * 60
    soak["warmup_seconds"] = 60 * 60
    soak["raw_sample_count"] = len(samples)
    soak["sample_count"] = len(samples) - 1
    soak["observations"]["runtime_uptime_start_seconds"] += 60 * 60
    soak["observations"]["runtime_uptime_end_seconds"] = last_sample["runtime_uptime_seconds"]
    soak["observations"]["accepted_spans_end"] = last_sample["accepted_spans"]
    soak["observations"]["exported_spans_end"] = last_sample["exported_spans"]
    soak["observations"]["accepted_metric_points_end"] = last_sample["accepted_metric_points"]

    assert validate(
        _write_json(tmp_path / "manifest.json", _manifest(tmp_path)),
        _write_soak(tmp_path, soak, samples),
        RUNTIME_IMAGE,
    ) == (1, 25 * 60 * 60)


def test_accepts_editor_activity_soak_without_board_chat_activity(tmp_path: Path) -> None:
    soak, samples = _soak()
    soak["load_profile"]["required_worker_activity"] = ["editor_document"]
    soak["load_profile"]["required_task_activity"] = []
    for sample in samples:
        sample["workers"]["board_chat"] = 0
        sample["workers"]["editor_document"] = 1
        sample["tasks"]["command"] = 0
    soak["observations"]["worker_active_max"] = {"board_chat": 0, "editor_ai": 0, "editor_document": 1}
    soak["observations"]["task_active_max"] = {"command": 0, "graph_stream": 0}

    assert validate(
        _write_json(tmp_path / "manifest.json", _manifest(tmp_path)),
        _write_soak(tmp_path, soak, samples),
        RUNTIME_IMAGE,
    ) == (1, 24 * 60 * 60)


def test_cutover_requires_otel_even_with_editor_manifest(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    manifest_path = _write_json(tmp_path / "manifest.json", _manifest(tmp_path))
    monkeypatch.setattr(sys, "argv", ["validate", str(manifest_path)])

    with pytest.raises(SystemExit, match="2"):
        _ = main()


def test_accepts_explicit_host_paths_for_a_container_generated_manifest(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path)
    source = Path(manifest["source_directory"])
    destination = Path(manifest["destination_directory"])
    manifest["source_directory"] = "/container/editor-source"
    manifest["destination_directory"] = "/container/editor-restore"
    soak, samples = _soak()

    assert validate(
        _write_json(tmp_path / "manifest.json", manifest),
        _write_soak(tmp_path, soak, samples),
        RUNTIME_IMAGE,
        source_directory=source,
        destination_directory=destination,
    ) == (1, 24 * 60 * 60)

    with pytest.raises(EvidenceValidationError, match="Both editor source and restore"):
        validate(
            tmp_path / "manifest.json",
            tmp_path / "soak.json",
            RUNTIME_IMAGE,
            source_directory=source,
        )


@pytest.mark.parametrize("change", ["missing", "changed", "extra", "linked"])
def test_rejects_editor_restore_changed_after_manifest(tmp_path: Path, change: str) -> None:
    manifest = _manifest(tmp_path)
    source_file = Path(manifest["source_directory"]) / FILE_NAME
    destination = Path(manifest["destination_directory"])
    destination_file = destination / FILE_NAME
    if change == "missing":
        destination_file.unlink()
    elif change == "changed":
        _ = destination_file.write_bytes(b"changed")
    elif change == "extra":
        _ = (destination / f"{'b' * 64}.ydoc").write_bytes(DOCUMENT_BYTES)
    else:
        destination_file.unlink()
        destination_file.hardlink_to(source_file)
    soak, samples = _soak()

    with pytest.raises(EvidenceValidationError, match="Editor manifest|Editor document"):
        validate(
            _write_json(tmp_path / "manifest.json", manifest),
            _write_soak(tmp_path, soak, samples),
            RUNTIME_IMAGE,
        )


def test_rejects_a_single_connection_spike_during_the_soak(tmp_path: Path) -> None:
    soak, samples = _soak()
    for sample in samples[1:-1]:
        sample["sockets"] = 0

    with pytest.raises(EvidenceValidationError):
        validate(
            _write_json(tmp_path / "manifest.json", _manifest(tmp_path)),
            _write_soak(tmp_path, soak, samples),
            RUNTIME_IMAGE,
        )


def test_rejects_a_soak_with_a_long_telemetry_gap(tmp_path: Path) -> None:
    soak, samples = _soak()
    started_at = datetime.fromisoformat(soak["started_at"])
    for index, sample in enumerate(samples[1:-1], start=1):
        sample["captured_at"] = (started_at + timedelta(minutes=index)).isoformat()

    with pytest.raises(EvidenceValidationError, match="sample coverage"):
        validate(
            _write_json(tmp_path / "manifest.json", _manifest(tmp_path)),
            _write_soak(tmp_path, soak, samples),
            RUNTIME_IMAGE,
        )


def test_rejects_duplicate_otel_sample_timestamps(tmp_path: Path) -> None:
    soak, samples = _soak()
    samples[1]["captured_at"] = samples[0]["captured_at"]

    with pytest.raises(EvidenceValidationError, match="sample timestamps"):
        validate(
            _write_json(tmp_path / "manifest.json", _manifest(tmp_path)),
            _write_soak(tmp_path, soak, samples),
            RUNTIME_IMAGE,
        )


def test_rejects_zero_socket_load_profile(tmp_path: Path) -> None:
    soak, samples = _soak()
    soak["load_profile"]["target_sockets"] = 0

    with pytest.raises(EvidenceValidationError, match="target_sockets"):
        validate(
            _write_json(tmp_path / "manifest.json", _manifest(tmp_path)),
            _write_soak(tmp_path, soak, samples),
            RUNTIME_IMAGE,
        )


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("profile_id", ""),
        ("source", " "),
        ("measured_at", "2026-09-20T00:00:00Z"),
        ("required_worker_activity", ["board_chat", "board_chat"]),
        ("target_sockets", 1.5),
    ),
)
def test_rejects_invalid_otel_load_profile(tmp_path: Path, field: str, value: object) -> None:
    soak, samples = _soak()
    soak["load_profile"][field] = value

    with pytest.raises(EvidenceValidationError, match="OTel load"):
        validate(
            _write_json(tmp_path / "manifest.json", _manifest(tmp_path)),
            _write_soak(tmp_path, soak, samples),
            RUNTIME_IMAGE,
        )


def test_rejects_collector_counters_without_soak_delivery(tmp_path: Path) -> None:
    soak, samples = _soak()
    for sample in samples:
        sample["accepted_spans"] = 100
        sample["accepted_metric_points"] = 100

    with pytest.raises(EvidenceValidationError):
        validate(
            _write_json(tmp_path / "manifest.json", _manifest(tmp_path)),
            _write_soak(tmp_path, soak, samples),
            RUNTIME_IMAGE,
        )


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("verified", False),
        ("unmapped_source_files", ["unknown.ydoc"]),
        ("unmapped_destination_files", ["unexpected.ydoc"]),
    ),
)
def test_rejects_incomplete_editor_restore(tmp_path: Path, field: str, value: object) -> None:
    manifest = _manifest(tmp_path)
    manifest[field] = value
    soak, samples = _soak()

    with pytest.raises(EvidenceValidationError):
        validate(
            _write_json(tmp_path / "manifest.json", manifest),
            _write_soak(tmp_path, soak, samples),
            RUNTIME_IMAGE,
        )


@pytest.mark.parametrize("document_name", ["", "card:other:description", "a" * 513])
def test_rejects_editor_restore_with_invalid_document_mapping(tmp_path: Path, document_name: str) -> None:
    manifest = _manifest(tmp_path)
    manifest["documents"][0]["document_name"] = document_name
    soak, samples = _soak()

    with pytest.raises(EvidenceValidationError, match="document_name|file name"):
        validate(
            _write_json(tmp_path / "manifest.json", manifest),
            _write_soak(tmp_path, soak, samples),
            RUNTIME_IMAGE,
        )


def test_rejects_short_otel_delivery_probe(tmp_path: Path) -> None:
    soak, samples = _soak()
    soak.update(
        {
            "evidence_type": None,
            "started_at": "2026-09-19T11:30:00Z",
            "finished_at": "2026-09-19T11:38:00Z",
            "duration_seconds": 480,
        }
    )

    with pytest.raises(EvidenceValidationError):
        validate(
            _write_json(tmp_path / "manifest.json", _manifest(tmp_path)),
            _write_soak(tmp_path, soak, samples),
            RUNTIME_IMAGE,
        )


def test_rejects_unbounded_resource_or_rollback_trigger(tmp_path: Path) -> None:
    soak, samples = _soak()
    soak["bounded"]["buffers"] = False
    soak["rollback_triggers"] = ["buffer-growth"]

    with pytest.raises(EvidenceValidationError):
        validate(
            _write_json(tmp_path / "manifest.json", _manifest(tmp_path)),
            _write_soak(tmp_path, soak, samples),
            RUNTIME_IMAGE,
        )


def test_rejects_a_different_deployment_image(tmp_path: Path) -> None:
    soak, samples = _soak()
    with pytest.raises(EvidenceValidationError):
        validate(
            _write_json(tmp_path / "manifest.json", _manifest(tmp_path)),
            _write_soak(tmp_path, soak, samples),
            f"sha256:{'c' * 64}",
        )


def test_rejects_tampered_otel_samples(tmp_path: Path) -> None:
    soak, samples = _soak()
    soak_path = _write_soak(tmp_path, soak, samples)
    with (tmp_path / soak["samples_file"]).open("a", encoding="utf-8") as file:
        _ = file.write("{}\n")

    with pytest.raises(EvidenceValidationError, match="checksum"):
        validate(_write_json(tmp_path / "manifest.json", _manifest(tmp_path)), soak_path, RUNTIME_IMAGE)


def test_rejects_runtime_restart_hidden_by_stable_memory(tmp_path: Path) -> None:
    soak, samples = _soak()
    samples[12]["runtime_uptime_seconds"] = 1

    with pytest.raises(EvidenceValidationError):
        validate(
            _write_json(tmp_path / "manifest.json", _manifest(tmp_path)),
            _write_soak(tmp_path, soak, samples),
            RUNTIME_IMAGE,
        )


def test_rejects_high_steady_memory_with_no_growth(tmp_path: Path) -> None:
    soak, samples = _soak()
    for sample in samples:
        sample["memory_total"] = 2000
    soak["observations"].update({"memory_start_bytes": 2000, "memory_end_bytes": 2000, "memory_max_bytes": 2000})
    soak["bounded"]["memory"] = False
    soak["rollback_triggers"] = ["memory"]
    soak["success"] = False

    with pytest.raises(EvidenceValidationError, match="rollback triggers"):
        validate(
            _write_json(tmp_path / "manifest.json", _manifest(tmp_path)),
            _write_soak(tmp_path, soak, samples),
            RUNTIME_IMAGE,
        )


def test_rejects_legacy_soak_without_peak_bound(tmp_path: Path) -> None:
    soak, samples = _soak()
    soak["format_version"] = 3
    del soak["thresholds"]["memory_peak_bytes"]

    with pytest.raises(EvidenceValidationError, match="format-version 5"):
        validate(
            _write_json(tmp_path / "manifest.json", _manifest(tmp_path)),
            _write_soak(tmp_path, soak, samples),
            RUNTIME_IMAGE,
        )


def test_rejects_editor_authorization_errors_above_the_recorded_threshold(tmp_path: Path) -> None:
    soak, samples = _soak()
    samples[-1]["editor_authorization_errors"] = 48
    soak["observations"]["editor_authorization_errors_observed"] = 48
    soak["observations"]["editor_authorization_error_ratio"] = 0.02
    soak["bounded"]["authorization"] = False
    soak["rollback_triggers"] = ["authorization"]
    soak["success"] = False

    with pytest.raises(EvidenceValidationError, match="rollback triggers"):
        validate(
            _write_json(tmp_path / "manifest.json", _manifest(tmp_path)),
            _write_soak(tmp_path, soak, samples),
            RUNTIME_IMAGE,
        )
