import hashlib
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any
import pytest
from langboard.commands.ValidatePhoenixCutoverEvidenceCommand import EvidenceValidationError, validate


CHECKSUM = "a" * 64
DOCUMENT_NAME = "card:known:description"
FILE_NAME = f"{hashlib.sha256(DOCUMENT_NAME.encode('utf-8')).hexdigest()}.ydoc"
RUNTIME_IMAGE = f"sha256:{CHECKSUM}"


def _write_json(path: Path, value: dict[str, Any]) -> Path:
    _ = path.write_text(json.dumps(value), encoding="utf-8")
    return path


def _manifest() -> dict[str, Any]:
    return {
        "format_version": 2,
        "generated_at": "2026-09-19T16:40:54Z",
        "source_directory": "/backup/editor-sync",
        "destination_directory": "/restore/editor-sync",
        "verified": True,
        "documents": [
            {
                "document_name": DOCUMENT_NAME,
                "file_name": FILE_NAME,
                "source_checksum": CHECKSUM,
                "destination_checksum": CHECKSUM,
                "source_bytes": 42,
                "restore_status": "verified",
            }
        ],
        "opaque_documents": [],
        "unmapped_source_files": [],
        "unmapped_destination_files": [],
    }


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
            "accepted_metric_points": hour + 1,
            "failed_spans": 0,
            "refused_spans": 0,
            "failed_metric_points": 0,
            "refused_metric_points": 0,
        }
        for hour in range(25)
    ]
    report = {
        "format_version": 3,
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
        _write_json(tmp_path / "manifest.json", _manifest()),
        _write_soak(tmp_path, soak, samples),
        RUNTIME_IMAGE,
    )

    assert result == (1, 24 * 60 * 60)


def test_rejects_a_single_connection_spike_during_the_soak(tmp_path: Path) -> None:
    soak, samples = _soak()
    for sample in samples[1:-1]:
        sample["sockets"] = 0

    with pytest.raises(EvidenceValidationError):
        validate(
            _write_json(tmp_path / "manifest.json", _manifest()),
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
            _write_json(tmp_path / "manifest.json", _manifest()),
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
    manifest = _manifest()
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
    manifest = _manifest()
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
            _write_json(tmp_path / "manifest.json", _manifest()),
            _write_soak(tmp_path, soak, samples),
            RUNTIME_IMAGE,
        )


def test_rejects_unbounded_resource_or_rollback_trigger(tmp_path: Path) -> None:
    soak, samples = _soak()
    soak["bounded"]["buffers"] = False
    soak["rollback_triggers"] = ["buffer-growth"]

    with pytest.raises(EvidenceValidationError):
        validate(
            _write_json(tmp_path / "manifest.json", _manifest()),
            _write_soak(tmp_path, soak, samples),
            RUNTIME_IMAGE,
        )


def test_rejects_a_different_deployment_image(tmp_path: Path) -> None:
    soak, samples = _soak()
    with pytest.raises(EvidenceValidationError):
        validate(
            _write_json(tmp_path / "manifest.json", _manifest()),
            _write_soak(tmp_path, soak, samples),
            f"sha256:{'c' * 64}",
        )


def test_rejects_tampered_otel_samples(tmp_path: Path) -> None:
    soak, samples = _soak()
    soak_path = _write_soak(tmp_path, soak, samples)
    with (tmp_path / soak["samples_file"]).open("a", encoding="utf-8") as file:
        _ = file.write("{}\n")

    with pytest.raises(EvidenceValidationError, match="checksum"):
        validate(_write_json(tmp_path / "manifest.json", _manifest()), soak_path, RUNTIME_IMAGE)


def test_rejects_runtime_restart_hidden_by_stable_memory(tmp_path: Path) -> None:
    soak, samples = _soak()
    samples[12]["runtime_uptime_seconds"] = 1

    with pytest.raises(EvidenceValidationError):
        validate(
            _write_json(tmp_path / "manifest.json", _manifest()),
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
            _write_json(tmp_path / "manifest.json", _manifest()),
            _write_soak(tmp_path, soak, samples),
            RUNTIME_IMAGE,
        )
