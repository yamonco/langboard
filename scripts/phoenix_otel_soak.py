"""Record and evaluate a Phoenix OTel soak from Collector-exported metrics."""

import argparse
import hashlib
import json
import math
import os
import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from itertools import pairwise
from pathlib import Path
from time import monotonic, sleep
from typing import Any, Literal, TypedDict, cast
from scripts.phoenix_otel_metrics import MetricSample, find_sample, parse_samples, read_metrics, require_sample


RUNTIME_IMAGE_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
WORKER_KINDS = ("board_chat", "editor_ai", "editor_document")
TASK_KINDS = ("command", "graph_stream")
SCALAR_THRESHOLDS = (
    "memory_growth_bytes",
    "memory_slope_bytes_per_hour",
    "mailbox_total",
    "mailbox_max",
    "outbound_queue_length",
    "slow_client_queue_length",
    "editor_authorization_error_ratio",
    "editor_authorization_average_microseconds",
)
EDITOR_AUTHORIZATION_ROUTE = "/auth/socket/editor-document"
AUTHORIZATION_RESULTS = (
    "success",
    "client_error",
    "server_error",
    "invalid_response",
    "unexpected_status",
    "transport_error",
)
AUTHORIZATION_ERROR_RESULTS = ("server_error", "invalid_response", "unexpected_status", "transport_error")


class SoakConfigurationError(ValueError):
    pass


class LoadProfile(TypedDict):
    profile_id: str
    source: str
    measured_at: str
    target_sockets: int
    minimum_editor_authorization_requests: int
    required_worker_activity: list[str]
    required_task_activity: list[str]


class SoakSample(TypedDict):
    captured_at: str
    memory_total: float
    runtime_uptime_seconds: float
    mailbox_total: float
    mailbox_max: float
    sockets: float
    outbound_queue_length: float
    slow_client_queue_length: float
    editor_authorization_requests: float
    editor_authorization_errors: float
    editor_authorization_duration_microseconds: float
    workers: dict[str, float]
    worker_availability: dict[str, float]
    tasks: dict[str, float]
    task_availability: dict[str, float]
    scrape_up: float
    accepted_spans: float
    accepted_metric_points: float
    failed_spans: float
    refused_spans: float
    failed_metric_points: float
    refused_metric_points: float


class SoakObservations(TypedDict):
    memory_start_bytes: float
    memory_end_bytes: float
    memory_max_bytes: float
    memory_growth_bytes: float
    memory_slope_bytes_per_hour: float
    runtime_uptime_start_seconds: float
    runtime_uptime_end_seconds: float
    mailbox_total_max: float
    mailbox_max_max: float
    outbound_queue_length_max: float
    slow_client_queue_length_max: float
    sockets_max: float
    editor_authorization_requests_observed: float
    editor_authorization_errors_observed: float
    editor_authorization_error_ratio: float
    editor_authorization_average_microseconds: float
    worker_active_max: dict[str, float]
    task_active_max: dict[str, float]
    accepted_spans_end: float
    accepted_metric_points_end: float


class SoakEvaluation(TypedDict):
    representative_load: bool
    telemetry_healthy: bool
    runtime_continuity: bool
    bounded: dict[str, bool]
    rollback_triggers: list[str]
    observations: SoakObservations


ActivityField = Literal["workers", "worker_availability", "tasks", "task_availability"]


@dataclass(frozen=True)
class SoakConfiguration:
    thresholds: dict[str, float]
    worker_limits: dict[str, float]
    task_limits: dict[str, float]
    load_profile: LoadProfile


def _read_object(path: Path) -> dict[str, Any]:
    try:
        value: object = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise SoakConfigurationError(f"Cannot read JSON configuration {path}: {error}") from error
    if not isinstance(value, dict) or any(not isinstance(key, str) for key in value):
        raise SoakConfigurationError(f"Configuration must be a JSON object: {path}")
    return cast(dict[str, Any], value)


def _nonnegative_number(value: object, field: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value) or value < 0:
        raise SoakConfigurationError(f"{field} must be a finite nonnegative number")
    return float(value)


def _parse_utc_timestamp(value: object, field: str) -> str:
    if not isinstance(value, str):
        raise SoakConfigurationError(f"{field} must be an ISO-8601 UTC timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise SoakConfigurationError(f"{field} must be an ISO-8601 UTC timestamp") from error
    if parsed.tzinfo is None or parsed.utcoffset() != UTC.utcoffset(parsed):
        raise SoakConfigurationError(f"{field} must use UTC")
    return value


def _parse_kind_limits(value: object, kinds: tuple[str, ...], field: str) -> dict[str, float]:
    if not isinstance(value, dict) or set(value) != set(kinds):
        raise SoakConfigurationError(f"{field} must define exactly: {', '.join(kinds)}")
    return {kind: _nonnegative_number(value[kind], f"{field}.{kind}") for kind in kinds}


def _parse_required_activity(value: object, kinds: tuple[str, ...], field: str) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise SoakConfigurationError(f"{field} must be a list")
    values = cast(list[str], value)
    if len(values) != len(set(values)) or any(item not in kinds for item in values):
        raise SoakConfigurationError(f"{field} contains an unknown or duplicate kind")
    return values


def load_configuration(thresholds_path: Path, load_profile_path: Path) -> SoakConfiguration:
    raw_thresholds = _read_object(thresholds_path)
    if set(raw_thresholds) != {*SCALAR_THRESHOLDS, "worker_active", "task_active"}:
        raise SoakConfigurationError("Threshold configuration contains missing or unknown fields")
    thresholds = {field: _nonnegative_number(raw_thresholds[field], field) for field in SCALAR_THRESHOLDS}
    if thresholds["editor_authorization_error_ratio"] > 1:
        raise SoakConfigurationError("editor_authorization_error_ratio must not exceed 1")
    worker_limits = _parse_kind_limits(raw_thresholds["worker_active"], WORKER_KINDS, "worker_active")
    task_limits = _parse_kind_limits(raw_thresholds["task_active"], TASK_KINDS, "task_active")

    raw_load_profile = _read_object(load_profile_path)
    expected_profile_fields = {
        "profile_id",
        "source",
        "measured_at",
        "target_sockets",
        "minimum_editor_authorization_requests",
        "required_worker_activity",
        "required_task_activity",
    }
    if set(raw_load_profile) != expected_profile_fields:
        raise SoakConfigurationError("Load profile contains missing or unknown fields")
    for field in ("profile_id", "source"):
        if not isinstance(raw_load_profile[field], str) or not raw_load_profile[field].strip():
            raise SoakConfigurationError(f"Load profile {field} is required")
    target_sockets = _nonnegative_number(raw_load_profile["target_sockets"], "target_sockets")
    if not target_sockets.is_integer() or target_sockets < 1:
        raise SoakConfigurationError("target_sockets must be a positive integer")
    minimum_authorization_requests = _nonnegative_number(
        raw_load_profile["minimum_editor_authorization_requests"],
        "minimum_editor_authorization_requests",
    )
    if not minimum_authorization_requests.is_integer() or minimum_authorization_requests < 1:
        raise SoakConfigurationError("minimum_editor_authorization_requests must be a positive integer")
    load_profile = LoadProfile(
        profile_id=cast(str, raw_load_profile["profile_id"]),
        source=cast(str, raw_load_profile["source"]),
        measured_at=_parse_utc_timestamp(raw_load_profile["measured_at"], "measured_at"),
        target_sockets=int(target_sockets),
        minimum_editor_authorization_requests=int(minimum_authorization_requests),
        required_worker_activity=_parse_required_activity(
            raw_load_profile["required_worker_activity"], WORKER_KINDS, "required_worker_activity"
        ),
        required_task_activity=_parse_required_activity(
            raw_load_profile["required_task_activity"], TASK_KINDS, "required_task_activity"
        ),
    )
    return SoakConfiguration(thresholds, worker_limits, task_limits, load_profile)


def _value(samples: dict[str, list[MetricSample]], name: str, label: str | None = None) -> float:
    return require_sample(samples, name, label=label).value


def _optional_value(
    samples: dict[str, list[MetricSample]],
    name: str,
    *,
    label: str | None = None,
    default: float = 0.0,
) -> float:
    sample = find_sample(samples, name, label=label)
    return sample.value if sample is not None else default


def _authorization_value(
    samples: dict[str, list[MetricSample]],
    metric_name: str,
    results: tuple[str, ...] = AUTHORIZATION_RESULTS,
) -> float:
    route_label = f'route="{EDITOR_AUTHORIZATION_ROUTE}"'
    return sum(
        sample.value
        for sample in samples.get(metric_name, [])
        if route_label in sample.labels and any(f'result="{result}"' in sample.labels for result in results)
    )


def collect_sample(metrics_url: str, collector_metrics_url: str, timeout_seconds: float) -> SoakSample:
    metrics = parse_samples(read_metrics(metrics_url, timeout_seconds))
    collector = parse_samples(read_metrics(collector_metrics_url, timeout_seconds))
    workers = {
        kind: _value(metrics, "langboard_socket_runtime_workers_active", f'kind="{kind}"') for kind in WORKER_KINDS
    }
    worker_availability = {
        kind: _value(metrics, "langboard_socket_runtime_workers_available", f'kind="{kind}"') for kind in WORKER_KINDS
    }
    tasks = {kind: _value(metrics, "langboard_socket_runtime_tasks_active", f'kind="{kind}"') for kind in TASK_KINDS}
    task_availability = {
        kind: _value(metrics, "langboard_socket_runtime_tasks_available", f'kind="{kind}"') for kind in TASK_KINDS
    }
    return SoakSample(
        captured_at=datetime.now(UTC).isoformat(),
        memory_total=_value(metrics, "vm_memory_total"),
        runtime_uptime_seconds=_value(metrics, "langboard_socket_runtime_uptime_seconds"),
        mailbox_total=_value(metrics, "langboard_socket_runtime_mailbox_total"),
        mailbox_max=_value(metrics, "langboard_socket_runtime_mailbox_max"),
        sockets=_value(metrics, "langboard_socket_runtime_sockets_count"),
        outbound_queue_length=_value(metrics, "langboard_socket_websocket_outbound_queue_length"),
        slow_client_queue_length=_optional_value(
            metrics,
            "langboard_socket_websocket_slow_client_queue_length",
        ),
        editor_authorization_requests=_authorization_value(
            metrics,
            "langboard_socket_authorization_request_count_total",
        ),
        editor_authorization_errors=_authorization_value(
            metrics,
            "langboard_socket_authorization_request_count_total",
            AUTHORIZATION_ERROR_RESULTS,
        ),
        editor_authorization_duration_microseconds=_authorization_value(
            metrics,
            "langboard_socket_authorization_request_duration_microseconds_total",
        ),
        workers=workers,
        worker_availability=worker_availability,
        tasks=tasks,
        task_availability=task_availability,
        scrape_up=_value(metrics, "up", 'job="langboard_socket_phoenix"'),
        accepted_spans=_value(collector, "otelcol_receiver_accepted_spans", 'receiver="otlp"'),
        accepted_metric_points=_value(
            collector,
            "otelcol_receiver_accepted_metric_points",
            'receiver="prometheus/socket_phoenix"',
        ),
        failed_spans=_value(collector, "otelcol_receiver_failed_spans", 'receiver="otlp"'),
        refused_spans=_value(collector, "otelcol_receiver_refused_spans", 'receiver="otlp"'),
        failed_metric_points=_value(
            collector,
            "otelcol_receiver_failed_metric_points",
            'receiver="prometheus/socket_phoenix"',
        ),
        refused_metric_points=_value(
            collector,
            "otelcol_receiver_refused_metric_points",
            'receiver="prometheus/socket_phoenix"',
        ),
    )


def _maximum(values: Iterable[float]) -> float:
    return max(values)


def _kind_maximum(samples: list[SoakSample], field: ActivityField, kind: str) -> float:
    return _maximum(sample[field][kind] for sample in samples)


def _linear_memory_slope_per_hour(samples: list[SoakSample]) -> float:
    timestamps = [datetime.fromisoformat(sample["captured_at"]).timestamp() for sample in samples]
    values = [sample["memory_total"] for sample in samples]
    origin = timestamps[0]
    x_values = [timestamp - origin for timestamp in timestamps]
    x_mean = sum(x_values) / len(x_values)
    y_mean = sum(values) / len(values)
    denominator = sum((value - x_mean) ** 2 for value in x_values)
    if denominator == 0:
        return 0.0
    slope_per_second = (
        sum((x_value - x_mean) * (y_value - y_mean) for x_value, y_value in zip(x_values, values, strict=True))
        / denominator
    )
    return slope_per_second * 3600


def evaluate_samples(samples: list[SoakSample], configuration: SoakConfiguration) -> SoakEvaluation:
    if len(samples) < 2:
        raise SoakConfigurationError("At least two post-warmup samples are required")

    thresholds = configuration.thresholds
    memory_growth = samples[-1]["memory_total"] - samples[0]["memory_total"]
    memory_slope = _linear_memory_slope_per_hour(samples)
    worker_maxima = {kind: _kind_maximum(samples, "workers", kind) for kind in WORKER_KINDS}
    task_maxima = {kind: _kind_maximum(samples, "tasks", kind) for kind in TASK_KINDS}
    authorization_requests = samples[-1]["editor_authorization_requests"] - samples[0]["editor_authorization_requests"]
    authorization_errors = samples[-1]["editor_authorization_errors"] - samples[0]["editor_authorization_errors"]
    authorization_duration = (
        samples[-1]["editor_authorization_duration_microseconds"]
        - samples[0]["editor_authorization_duration_microseconds"]
    )
    authorization_error_ratio = authorization_errors / authorization_requests if authorization_requests > 0 else 0.0
    authorization_average = authorization_duration / authorization_requests if authorization_requests > 0 else 0.0
    observations = SoakObservations(
        memory_start_bytes=samples[0]["memory_total"],
        memory_end_bytes=samples[-1]["memory_total"],
        memory_max_bytes=_maximum(sample["memory_total"] for sample in samples),
        memory_growth_bytes=memory_growth,
        memory_slope_bytes_per_hour=memory_slope,
        runtime_uptime_start_seconds=samples[0]["runtime_uptime_seconds"],
        runtime_uptime_end_seconds=samples[-1]["runtime_uptime_seconds"],
        mailbox_total_max=_maximum(sample["mailbox_total"] for sample in samples),
        mailbox_max_max=_maximum(sample["mailbox_max"] for sample in samples),
        outbound_queue_length_max=_maximum(sample["outbound_queue_length"] for sample in samples),
        slow_client_queue_length_max=_maximum(sample["slow_client_queue_length"] for sample in samples),
        sockets_max=_maximum(sample["sockets"] for sample in samples),
        editor_authorization_requests_observed=authorization_requests,
        editor_authorization_errors_observed=authorization_errors,
        editor_authorization_error_ratio=authorization_error_ratio,
        editor_authorization_average_microseconds=authorization_average,
        worker_active_max=worker_maxima,
        task_active_max=task_maxima,
        accepted_spans_end=samples[-1]["accepted_spans"],
        accepted_metric_points_end=samples[-1]["accepted_metric_points"],
    )

    memory_bounded = (
        memory_growth <= thresholds["memory_growth_bytes"] and memory_slope <= thresholds["memory_slope_bytes_per_hour"]
    )
    mailboxes_bounded = (
        observations["mailbox_total_max"] <= thresholds["mailbox_total"]
        and observations["mailbox_max_max"] <= thresholds["mailbox_max"]
    )
    buffers_bounded = (
        observations["outbound_queue_length_max"] <= thresholds["outbound_queue_length"]
        and observations["slow_client_queue_length_max"] <= thresholds["slow_client_queue_length"]
    )
    authorization_metrics_monotonic = all(
        current[field] >= previous[field]
        for previous, current in pairwise(samples)
        for field in (
            "editor_authorization_requests",
            "editor_authorization_errors",
            "editor_authorization_duration_microseconds",
        )
    )
    authorization_bounded = (
        authorization_metrics_monotonic
        and authorization_requests > 0
        and authorization_error_ratio <= thresholds["editor_authorization_error_ratio"]
        and authorization_average <= thresholds["editor_authorization_average_microseconds"]
    )
    supervisors_available = all(
        _kind_maximum(samples, "worker_availability", kind) == 1
        and min(sample["worker_availability"][kind] for sample in samples) == 1
        for kind in WORKER_KINDS
    ) and all(
        _kind_maximum(samples, "task_availability", kind) == 1
        and min(sample["task_availability"][kind] for sample in samples) == 1
        for kind in TASK_KINDS
    )
    registries_bounded = (
        supervisors_available
        and all(worker_maxima[kind] <= configuration.worker_limits[kind] for kind in WORKER_KINDS)
        and all(task_maxima[kind] <= configuration.task_limits[kind] for kind in TASK_KINDS)
    )

    load_profile = configuration.load_profile
    representative_load = observations["sockets_max"] >= load_profile["target_sockets"]
    representative_load = (
        representative_load and authorization_requests >= load_profile["minimum_editor_authorization_requests"]
    )
    representative_load = representative_load and all(
        worker_maxima[kind] >= 1 for kind in load_profile["required_worker_activity"]
    )
    representative_load = representative_load and all(
        task_maxima[kind] >= 1 for kind in load_profile["required_task_activity"]
    )
    telemetry_healthy = all(sample["scrape_up"] == 1 for sample in samples)
    telemetry_healthy = telemetry_healthy and observations["accepted_spans_end"] >= 1
    telemetry_healthy = telemetry_healthy and observations["accepted_metric_points_end"] >= 1
    telemetry_healthy = telemetry_healthy and all(
        sample[field] == 0
        for sample in samples
        for field in ("failed_spans", "refused_spans", "failed_metric_points", "refused_metric_points")
    )
    telemetry_healthy = telemetry_healthy and authorization_metrics_monotonic
    telemetry_healthy = telemetry_healthy and all(
        current[metric] >= previous[metric]
        for previous, current in pairwise(samples)
        for metric in ("accepted_spans", "accepted_metric_points")
    )
    runtime_continuity = all(
        current["runtime_uptime_seconds"] >= previous["runtime_uptime_seconds"]
        for previous, current in pairwise(samples)
    )

    bounded = {
        "memory": memory_bounded,
        "mailboxes": mailboxes_bounded,
        "buffers": buffers_bounded,
        "authorization": authorization_bounded,
        "task_registries": registries_bounded,
    }
    rollback_triggers = [name for name, passed in bounded.items() if not passed]
    if not representative_load:
        rollback_triggers.append("representative_load")
    if not telemetry_healthy:
        rollback_triggers.append("telemetry_delivery")
    if not runtime_continuity:
        rollback_triggers.append("runtime_restart")
    return SoakEvaluation(
        representative_load=representative_load,
        telemetry_healthy=telemetry_healthy,
        runtime_continuity=runtime_continuity,
        bounded=bounded,
        rollback_triggers=rollback_triggers,
        observations=observations,
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_report(path: Path, report: dict[str, Any]) -> None:
    temporary_path = path.with_suffix(f"{path.suffix}.tmp")
    temporary_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary_path, path)


def record_soak(
    *,
    metrics_url: str,
    collector_metrics_url: str,
    runtime_image: str,
    output_path: Path,
    configuration: SoakConfiguration,
    duration_seconds: float,
    warmup_seconds: float,
    sample_interval_seconds: float,
    request_timeout_seconds: float,
) -> dict[str, Any]:
    if RUNTIME_IMAGE_PATTERN.fullmatch(runtime_image) is None:
        raise SoakConfigurationError("runtime-image must be an exact sha256 image ID")
    if duration_seconds <= 0 or sample_interval_seconds <= 0 or request_timeout_seconds <= 0:
        raise SoakConfigurationError("Duration, sample interval, and request timeout must be positive")
    if warmup_seconds < 0 or warmup_seconds >= duration_seconds:
        raise SoakConfigurationError("Warm-up must be nonnegative and shorter than the duration")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    samples_path = output_path.with_suffix(".samples.jsonl")
    started_at = datetime.now(UTC)
    started_monotonic = monotonic()
    deadline = started_monotonic + duration_seconds
    next_sample_at = started_monotonic
    post_warmup_samples: list[SoakSample] = []
    raw_sample_count = 0

    with samples_path.open("w", encoding="utf-8", buffering=1) as samples_file:
        while True:
            now = monotonic()
            if now < next_sample_at:
                sleep(next_sample_at - now)
            sample = collect_sample(metrics_url, collector_metrics_url, request_timeout_seconds)
            samples_file.write(json.dumps(sample, separators=(",", ":"), sort_keys=True) + "\n")
            samples_file.flush()
            raw_sample_count += 1
            if monotonic() - started_monotonic >= warmup_seconds:
                post_warmup_samples.append(sample)
            if monotonic() >= deadline:
                break
            next_sample_at += sample_interval_seconds

    finished_at = datetime.now(UTC)
    evaluation = evaluate_samples(post_warmup_samples, configuration)
    report = {
        "format_version": 3,
        "evidence_type": "phoenix_otel_soak",
        "runtime_image": runtime_image,
        "started_at": started_at.isoformat(),
        "finished_at": finished_at.isoformat(),
        "duration_seconds": (finished_at - started_at).total_seconds(),
        "warmup_seconds": warmup_seconds,
        "sample_interval_seconds": sample_interval_seconds,
        "sample_count": len(post_warmup_samples),
        "raw_sample_count": raw_sample_count,
        "samples_file": samples_path.name,
        "samples_sha256": _sha256(samples_path),
        "thresholds": {
            **configuration.thresholds,
            "worker_active": configuration.worker_limits,
            "task_active": configuration.task_limits,
        },
        "load_profile": {
            **configuration.load_profile,
            "observed_peak_sockets": evaluation["observations"]["sockets_max"],
        },
        **evaluation,
        "success": not evaluation["rollback_triggers"],
    }
    _write_report(output_path, report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    _ = parser.add_argument("--metrics-url", required=True)
    _ = parser.add_argument("--collector-metrics-url", required=True)
    _ = parser.add_argument("--runtime-image", required=True)
    _ = parser.add_argument("--thresholds", type=Path, required=True)
    _ = parser.add_argument("--load-profile", type=Path, required=True)
    _ = parser.add_argument("--output", type=Path, required=True)
    _ = parser.add_argument("--duration-seconds", type=float, default=24 * 60 * 60)
    _ = parser.add_argument("--warmup-seconds", type=float, default=60 * 60)
    _ = parser.add_argument("--sample-interval-seconds", type=float, default=10.0)
    _ = parser.add_argument("--request-timeout-seconds", type=float, default=5.0)
    args = parser.parse_args()
    try:
        configuration = load_configuration(args.thresholds, args.load_profile)
        report = record_soak(
            metrics_url=args.metrics_url,
            collector_metrics_url=args.collector_metrics_url,
            runtime_image=args.runtime_image,
            output_path=args.output,
            configuration=configuration,
            duration_seconds=args.duration_seconds,
            warmup_seconds=args.warmup_seconds,
            sample_interval_seconds=args.sample_interval_seconds,
            request_timeout_seconds=args.request_timeout_seconds,
        )
    except (OSError, SoakConfigurationError, RuntimeError) as error:
        parser.error(str(error))
    print(
        f"Phoenix OTel soak recorded: success={str(report['success']).lower()} "
        f"samples={report['sample_count']} output={args.output}"
    )
    return 0 if report["success"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
