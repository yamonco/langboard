import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from subprocess import CompletedProcess
from unittest.mock import patch
import pytest
from scripts.phoenix_otel_metrics import PrometheusMetricsError
from scripts.phoenix_otel_soak import (
    SoakConfiguration,
    SoakConfigurationError,
    SoakSample,
    _optional_value,
    collect_sample,
    evaluate_samples,
    inspect_runtime,
    load_configuration,
    record_soak,
)


RUNTIME_IMAGE = "sha256:" + "a" * 64


@pytest.mark.parametrize("running,image", [(True, RUNTIME_IMAGE), (False, RUNTIME_IMAGE), (True, "other")])
def test_runtime_inspection_requires_matching_live_image(running: bool, image: str) -> None:
    payload = [{"Id": "container", "Image": image, "State": {"Running": running, "StartedAt": "started"}}]
    with patch("scripts.phoenix_otel_soak.subprocess.run", return_value=CompletedProcess([], 0, json.dumps(payload))):
        if running and image == RUNTIME_IMAGE:
            assert inspect_runtime("runtime", RUNTIME_IMAGE) == ("container", RUNTIME_IMAGE, "started")
        else:
            with pytest.raises(SoakConfigurationError, match="container identity"):
                _ = inspect_runtime("runtime", RUNTIME_IMAGE)


@pytest.mark.parametrize(
    "changed", [("replacement", RUNTIME_IMAGE, "started"), ("container", RUNTIME_IMAGE, "restarted")]
)
@pytest.mark.parametrize("during_collection", [False, True])
def test_recorder_rejects_runtime_change_before_or_during_collection(
    tmp_path: Path, changed: tuple[str, str, str], during_collection: bool
) -> None:
    identity = ("container", RUNTIME_IMAGE, "started")
    identities = [identity, identity, changed] if during_collection else [identity, changed]
    with (
        patch("scripts.phoenix_otel_soak.inspect_runtime", side_effect=identities),
        patch("scripts.phoenix_otel_soak.collect_sample", return_value=_samples()[0]) as collect,
        pytest.raises(SoakConfigurationError, match="changed or restarted"),
    ):
        _ = record_soak(
            metrics_url="runtime",
            collector_metrics_url="collector",
            runtime_image=RUNTIME_IMAGE,
            runtime_container="runtime",
            output_path=tmp_path / "report.json",
            configuration=_configuration(),
            duration_seconds=1,
            warmup_seconds=0,
            sample_interval_seconds=1,
            request_timeout_seconds=1,
        )
    assert collect.call_count == int(during_collection)
    assert not (tmp_path / "report.json").exists()


def _configuration() -> SoakConfiguration:
    return SoakConfiguration(
        thresholds={
            "memory_peak_bytes": 1100,
            "memory_growth_bytes": 100,
            "memory_slope_bytes_per_hour": 1000,
            "mailbox_total": 10,
            "mailbox_max": 5,
            "outbound_queue_length": 5,
            "slow_client_queue_length": 5,
            "editor_authorization_error_ratio": 0.01,
            "editor_authorization_average_microseconds": 5000,
        },
        worker_limits={"board_chat": 2, "editor_ai": 2, "editor_document": 2},
        task_limits={"command": 2, "graph_stream": 2},
        load_profile={
            "profile_id": "test-profile",
            "source": "measured test baseline",
            "measured_at": "2026-09-19T00:00:00+00:00",
            "target_sockets": 2,
            "minimum_editor_authorization_requests": 20,
            "required_worker_activity": ["board_chat"],
            "required_task_activity": ["command"],
        },
    )


def _samples() -> list[SoakSample]:
    started_at = datetime(2026, 9, 19, tzinfo=UTC)
    return [
        {
            "captured_at": (started_at + timedelta(minutes=index)).isoformat(),
            "memory_total": 1000 + index * 10,
            "runtime_uptime_seconds": 100 + index * 60,
            "mailbox_total": 2,
            "mailbox_max": 1,
            "sockets": 2,
            "outbound_queue_length": 0,
            "slow_client_queue_length": 0,
            "editor_authorization_requests": index * 10,
            "editor_authorization_errors": 0,
            "editor_authorization_duration_microseconds": index * 10_000,
            "workers": {"board_chat": 1, "editor_ai": 0, "editor_document": 0},
            "worker_availability": {"board_chat": 1, "editor_ai": 1, "editor_document": 1},
            "tasks": {"command": 1, "graph_stream": 0},
            "task_availability": {"command": 1, "graph_stream": 1},
            "scrape_up": 1,
            "accepted_spans": index + 1,
            "exported_spans": index + 1,
            "export_failed_spans": 0,
            "export_enqueue_failed_spans": 0,
            "accepted_metric_points": index + 1,
            "failed_spans": 0,
            "refused_spans": 0,
            "failed_metric_points": 0,
            "refused_metric_points": 0,
        }
        for index in range(3)
    ]


def test_evaluates_samples_from_observed_metrics() -> None:
    result = evaluate_samples(_samples(), _configuration())

    assert result["representative_load"] is True
    assert result["runtime_continuity"] is True
    assert result["telemetry_healthy"] is True
    assert result["bounded"] == {
        "memory": True,
        "mailboxes": True,
        "buffers": True,
        "authorization": True,
        "task_registries": True,
    }
    assert result["rollback_triggers"] == []


def test_rejects_a_single_connection_spike_as_representative_load() -> None:
    samples = _samples()
    samples[0]["sockets"] = 0
    samples[-1]["sockets"] = 0

    result = evaluate_samples(samples, _configuration())

    assert result["observations"]["sockets_max"] == 2
    assert result["representative_load"] is False
    assert result["rollback_triggers"] == ["representative_load"]


def test_rejects_collector_counters_without_soak_delivery() -> None:
    samples = _samples()
    for sample in samples:
        sample["accepted_spans"] = 100
        sample["accepted_metric_points"] = 100

    result = evaluate_samples(samples, _configuration())

    assert result["telemetry_healthy"] is False
    assert result["rollback_triggers"] == ["telemetry_delivery"]


def test_rejects_trace_receipt_without_export() -> None:
    samples = _samples()
    for sample in samples:
        sample["exported_spans"] = 0

    result = evaluate_samples(samples, _configuration())

    assert result["telemetry_healthy"] is False
    assert result["rollback_triggers"] == ["telemetry_delivery"]


def test_detects_runtime_restart_and_resource_growth() -> None:
    samples = _samples()
    samples[-1]["runtime_uptime_seconds"] = 1
    samples[-1]["memory_total"] = 5000

    result = evaluate_samples(samples, _configuration())

    assert result["bounded"]["memory"] is False
    assert result["runtime_continuity"] is False
    assert result["rollback_triggers"] == ["memory", "runtime_restart"]


def test_rejects_high_steady_memory_without_growth() -> None:
    samples = _samples()
    for sample in samples:
        sample["memory_total"] = 2000

    result = evaluate_samples(samples, _configuration())

    assert result["observations"]["memory_growth_bytes"] == 0
    assert result["observations"]["memory_slope_bytes_per_hour"] == 0
    assert result["bounded"]["memory"] is False
    assert result["rollback_triggers"] == ["memory"]


def test_rejects_unbounded_editor_authorization_failures() -> None:
    samples = _samples()
    samples[-1]["editor_authorization_errors"] = 1

    result = evaluate_samples(samples, _configuration())

    assert result["bounded"]["authorization"] is False
    assert result["observations"]["editor_authorization_error_ratio"] == 0.05
    assert result["rollback_triggers"] == ["authorization"]


def test_load_configuration_requires_explicit_complete_bounds(tmp_path: Path) -> None:
    thresholds_path = tmp_path / "thresholds.json"
    load_profile_path = tmp_path / "load-profile.json"
    _ = thresholds_path.write_text(json.dumps({"memory_growth_bytes": 1}), encoding="utf-8")
    _ = load_profile_path.write_text("{}", encoding="utf-8")

    with pytest.raises(SoakConfigurationError, match="missing or unknown"):
        load_configuration(thresholds_path, load_profile_path)


def test_missing_optional_event_metric_is_zero() -> None:
    assert _optional_value({}, "langboard_socket_websocket_slow_client_queue_length") == 0


def test_collects_forwarded_authorization_counters(monkeypatch: pytest.MonkeyPatch) -> None:
    runtime_metrics = "\n".join(
        [
            "vm_memory_total 1000",
            "langboard_socket_runtime_uptime_seconds 100",
            "langboard_socket_runtime_mailbox_total 0",
            "langboard_socket_runtime_mailbox_max 0",
            "langboard_socket_runtime_sockets_count 1",
            "langboard_socket_websocket_outbound_queue_length 0",
            *[
                f'langboard_socket_runtime_workers_active{{kind="{kind}"}} 0'
                for kind in ("board_chat", "editor_ai", "editor_document")
            ],
            *[
                f'langboard_socket_runtime_workers_available{{kind="{kind}"}} 1'
                for kind in ("board_chat", "editor_ai", "editor_document")
            ],
            *[f'langboard_socket_runtime_tasks_active{{kind="{kind}"}} 0' for kind in ("command", "graph_stream")],
            *[f'langboard_socket_runtime_tasks_available{{kind="{kind}"}} 1' for kind in ("command", "graph_stream")],
            'up{job="langboard_socket_phoenix"} 1',
            'langboard_socket_authorization_request_count_total{result="success",route="/auth/socket/editor-document"} 3',
            'langboard_socket_authorization_request_count_total{result="server_error",route="/auth/socket/editor-document"} 1',
            'langboard_socket_authorization_request_count_total{result="invalid_response",route="/auth/socket/editor-document"} 1',
            'langboard_socket_authorization_request_duration_microseconds_total{result="success",route="/auth/socket/editor-document"} 12000',
            'langboard_socket_authorization_request_duration_microseconds_total{result="server_error",route="/auth/socket/editor-document"} 8000',
            'langboard_socket_authorization_request_duration_microseconds_total{result="invalid_response",route="/auth/socket/editor-document"} 5000',
        ]
    )
    collector_metrics = "\n".join(
        [
            'otelcol_receiver_accepted_spans{receiver="otlp"} 1',
            'otelcol_exporter_queue_capacity{data_type="traces",exporter="otlp_http/traces"} 1000',
            'otelcol_exporter_sent_spans{exporter="otlp_http/traces"} 1',
            'otelcol_receiver_accepted_metric_points{receiver="prometheus/socket_phoenix"} 1',
            'otelcol_receiver_failed_spans{receiver="otlp"} 0',
            'otelcol_receiver_refused_spans{receiver="otlp"} 0',
            'otelcol_receiver_failed_metric_points{receiver="prometheus/socket_phoenix"} 0',
            'otelcol_receiver_refused_metric_points{receiver="prometheus/socket_phoenix"} 0',
        ]
    )

    monkeypatch.setattr(
        "scripts.phoenix_otel_soak.read_metrics",
        lambda url, _timeout: collector_metrics if url == "collector" else runtime_metrics,
    )

    sample = collect_sample("runtime", "collector", 1)

    assert sample["editor_authorization_requests"] == 5
    assert sample["editor_authorization_errors"] == 2
    assert sample["editor_authorization_duration_microseconds"] == 25_000
    assert sample["exported_spans"] == 1


def test_rejects_nop_trace_exporter() -> None:
    with (
        patch("scripts.phoenix_otel_soak.read_metrics", return_value="otelcol_receiver_accepted_spans 1"),
        pytest.raises(PrometheusMetricsError, match="otlp_http/traces"),
    ):
        _ = collect_sample("runtime", "collector", 1)
