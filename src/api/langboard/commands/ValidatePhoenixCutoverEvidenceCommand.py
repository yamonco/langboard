"""Validate required Phoenix ownership cutover evidence without changing runtime state."""

import argparse
import hashlib
import json
import math
import re
from datetime import UTC, datetime, timedelta
from itertools import pairwise
from pathlib import Path
from typing import Any, cast


MINIMUM_SOAK_SECONDS = 24 * 60 * 60
SHA256_PATTERN = re.compile(r"^[0-9a-f]{64}$")
SHA256_FILE_PATTERN = re.compile(r"^[0-9a-f]{64}\.ydoc$")
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


class EvidenceValidationError(ValueError):
    pass


def _read_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise EvidenceValidationError(f"Cannot read JSON evidence {path}: {error}") from error
    if not isinstance(value, dict):
        raise EvidenceValidationError(f"Evidence must be a JSON object: {path}")
    return value


def _parse_utc_timestamp(value: object, field: str) -> datetime:
    if not isinstance(value, str):
        raise EvidenceValidationError(f"{field} must be an ISO-8601 UTC timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise EvidenceValidationError(f"{field} must be an ISO-8601 UTC timestamp") from error
    if parsed.tzinfo is None or parsed.utcoffset() != UTC.utcoffset(parsed):
        raise EvidenceValidationError(f"{field} must use UTC")
    return parsed


def _validate_document(record: object, *, named: bool) -> str:
    if not isinstance(record, dict):
        raise EvidenceValidationError("Editor manifest document entries must be objects")
    file_name = record.get("file_name")
    if not isinstance(file_name, str) or SHA256_FILE_PATTERN.fullmatch(file_name) is None:
        raise EvidenceValidationError("Editor manifest contains an invalid document file name")
    if named and not isinstance(record.get("document_name"), str):
        raise EvidenceValidationError(f"Named editor document is missing document_name: {file_name}")
    if record.get("restore_status") != "verified":
        raise EvidenceValidationError(f"Editor document is not verified: {file_name}")
    source_checksum = record.get("source_checksum")
    destination_checksum = record.get("destination_checksum")
    if (
        not isinstance(source_checksum, str)
        or SHA256_PATTERN.fullmatch(source_checksum) is None
        or source_checksum != destination_checksum
    ):
        raise EvidenceValidationError(f"Editor document checksums do not match: {file_name}")
    source_bytes = record.get("source_bytes")
    if not isinstance(source_bytes, int) or isinstance(source_bytes, bool) or source_bytes < 0:
        raise EvidenceValidationError(f"Editor document byte count is invalid: {file_name}")
    return file_name


def validate_editor_manifest(manifest: dict[str, Any]) -> int:
    if manifest.get("format_version") != 2 or manifest.get("verified") is not True:
        raise EvidenceValidationError("Editor manifest must be a verified format-version 2 audit")
    _parse_utc_timestamp(manifest.get("generated_at"), "Editor manifest generated_at")
    source = manifest.get("source_directory")
    destination = manifest.get("destination_directory")
    if not isinstance(source, str) or not source or not isinstance(destination, str) or not destination:
        raise EvidenceValidationError("Editor manifest source and destination directories are required")
    if source == destination:
        raise EvidenceValidationError("Editor manifest source and destination directories must differ")
    if manifest.get("unmapped_source_files") != [] or manifest.get("unmapped_destination_files") != []:
        raise EvidenceValidationError("Editor manifest contains unmapped files")

    documents = manifest.get("documents")
    opaque_documents = manifest.get("opaque_documents")
    if not isinstance(documents, list) or not isinstance(opaque_documents, list):
        raise EvidenceValidationError("Editor manifest document lists are missing")
    file_names = [*(_validate_document(record, named=True) for record in documents)]
    file_names.extend(_validate_document(record, named=False) for record in opaque_documents)
    if not file_names:
        raise EvidenceValidationError("Editor manifest does not contain any restored documents")
    if len(file_names) != len(set(file_names)):
        raise EvidenceValidationError("Editor manifest contains duplicate document files")
    return len(file_names)


def _finite_nonnegative(value: object, field: str) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value) or value < 0:
        raise EvidenceValidationError(f"{field} must be a finite nonnegative number")
    return float(value)


def _sample_number(sample: dict[str, Any], field: str) -> float:
    return _finite_nonnegative(sample.get(field), f"OTel sample {field}")


def _sample_kind_values(sample: dict[str, Any], field: str, kinds: tuple[str, ...]) -> dict[str, float]:
    value = sample.get(field)
    if not isinstance(value, dict) or set(value) != set(kinds):
        raise EvidenceValidationError(f"OTel sample {field} must define exactly: {', '.join(kinds)}")
    return {kind: _finite_nonnegative(value[kind], f"OTel sample {field}.{kind}") for kind in kinds}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as file:
            for chunk in iter(lambda: file.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as error:
        raise EvidenceValidationError(f"Cannot read OTel sample evidence {path}: {error}") from error
    return digest.hexdigest()


def _read_soak_samples(
    report: dict[str, Any], report_path: Path, started_at: datetime, finished_at: datetime
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    file_name = report.get("samples_file")
    checksum = report.get("samples_sha256")
    if (
        not isinstance(file_name, str)
        or not file_name
        or Path(file_name).name != file_name
        or not isinstance(checksum, str)
        or SHA256_PATTERN.fullmatch(checksum) is None
    ):
        raise EvidenceValidationError("OTel soak sample file evidence is invalid")
    samples_path = report_path.parent / file_name
    if _sha256(samples_path) != checksum:
        raise EvidenceValidationError("OTel soak sample checksum does not match")

    samples: list[dict[str, Any]] = []
    try:
        lines = samples_path.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise EvidenceValidationError(f"Cannot read OTel sample evidence {samples_path}: {error}") from error
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            continue
        try:
            sample = json.loads(line)
        except json.JSONDecodeError as error:
            raise EvidenceValidationError(f"Invalid OTel sample JSON at line {line_number}") from error
        if not isinstance(sample, dict):
            raise EvidenceValidationError(f"OTel sample at line {line_number} must be an object")
        samples.append(sample)

    raw_sample_count = report.get("raw_sample_count")
    if not isinstance(raw_sample_count, int) or isinstance(raw_sample_count, bool) or raw_sample_count != len(samples):
        raise EvidenceValidationError("OTel soak raw sample count does not match its sample file")
    if len(samples) < 2:
        raise EvidenceValidationError("OTel soak requires at least two raw samples")

    timestamps = [_parse_utc_timestamp(sample.get("captured_at"), "OTel sample captured_at") for sample in samples]
    if timestamps != sorted(timestamps) or timestamps[0] < started_at or timestamps[-1] > finished_at:
        raise EvidenceValidationError("OTel sample timestamps are outside the ordered soak interval")

    warmup_seconds = _finite_nonnegative(report.get("warmup_seconds"), "OTel soak warmup_seconds")
    warmup_finished_at = started_at + timedelta(seconds=warmup_seconds)
    post_warmup = [
        sample for sample, timestamp in zip(samples, timestamps, strict=True) if timestamp >= warmup_finished_at
    ]
    sample_count = report.get("sample_count")
    if not isinstance(sample_count, int) or isinstance(sample_count, bool) or sample_count != len(post_warmup):
        raise EvidenceValidationError("OTel soak sample count does not match its post-warmup samples")
    if len(post_warmup) < 2:
        raise EvidenceValidationError("OTel soak requires at least two post-warmup samples")
    return samples, post_warmup


def _linear_slope_per_hour(samples: list[dict[str, Any]], field: str) -> float:
    timestamps = [
        _parse_utc_timestamp(sample.get("captured_at"), "OTel sample captured_at").timestamp() for sample in samples
    ]
    values = [_sample_number(sample, field) for sample in samples]
    origin = timestamps[0]
    x_values = [timestamp - origin for timestamp in timestamps]
    x_mean = sum(x_values) / len(x_values)
    y_mean = sum(values) / len(values)
    denominator = sum((value - x_mean) ** 2 for value in x_values)
    if denominator == 0:
        return 0.0
    return (
        sum((x_value - x_mean) * (y_value - y_mean) for x_value, y_value in zip(x_values, values, strict=True))
        / denominator
        * 3600
    )


def _assert_reported_number(observations: dict[str, Any], field: str, expected: float) -> None:
    reported = observations.get(field)
    if (
        not isinstance(reported, (int, float))
        or isinstance(reported, bool)
        or not math.isfinite(reported)
        or not math.isclose(float(reported), expected, rel_tol=1e-9, abs_tol=1e-6)
    ):
        raise EvidenceValidationError(f"OTel soak observation does not match raw samples: {field}")


def _validate_thresholds(report: dict[str, Any]) -> tuple[dict[str, float], dict[str, float], dict[str, float]]:
    thresholds = report.get("thresholds")
    if not isinstance(thresholds, dict) or set(thresholds) != {*SCALAR_THRESHOLDS, "worker_active", "task_active"}:
        raise EvidenceValidationError("OTel soak thresholds contain missing or unknown fields")
    scalar = {field: _finite_nonnegative(thresholds[field], f"OTel threshold {field}") for field in SCALAR_THRESHOLDS}
    if scalar["editor_authorization_error_ratio"] > 1:
        raise EvidenceValidationError("OTel editor authorization error ratio threshold must not exceed 1")
    workers = _sample_kind_values({"value": thresholds["worker_active"]}, "value", WORKER_KINDS)
    tasks = _sample_kind_values({"value": thresholds["task_active"]}, "value", TASK_KINDS)
    return scalar, workers, tasks


def validate_otel_soak(report: dict[str, Any], report_path: Path, expected_runtime_image: str) -> float:
    if report.get("format_version") != 3 or report.get("evidence_type") != "phoenix_otel_soak":
        raise EvidenceValidationError("OTel evidence must be a format-version 3 Phoenix soak report")
    runtime_image = report.get("runtime_image")
    if not isinstance(runtime_image, str) or SHA256_PATTERN.fullmatch(runtime_image.removeprefix("sha256:")) is None:
        raise EvidenceValidationError("OTel soak runtime_image is missing")
    if runtime_image != expected_runtime_image:
        raise EvidenceValidationError("OTel soak runtime image does not match the Phoenix deployment image")

    started_at = _parse_utc_timestamp(report.get("started_at"), "OTel soak started_at")
    finished_at = _parse_utc_timestamp(report.get("finished_at"), "OTel soak finished_at")
    elapsed_seconds = (finished_at - started_at).total_seconds()
    duration_seconds = report.get("duration_seconds")
    if not isinstance(duration_seconds, (int, float)) or isinstance(duration_seconds, bool):
        raise EvidenceValidationError("OTel soak duration_seconds is invalid")
    if elapsed_seconds < MINIMUM_SOAK_SECONDS or duration_seconds < MINIMUM_SOAK_SECONDS:
        raise EvidenceValidationError("OTel soak must cover at least 24 hours")

    sample_interval_seconds = report.get("sample_interval_seconds")
    if (
        not isinstance(sample_interval_seconds, (int, float))
        or isinstance(sample_interval_seconds, bool)
        or sample_interval_seconds <= 0
    ):
        raise EvidenceValidationError("OTel soak sample interval is invalid")
    if not math.isfinite(duration_seconds) or not math.isfinite(sample_interval_seconds):
        raise EvidenceValidationError("OTel soak duration or sample interval is not finite")
    duration_tolerance = max(60.0, sample_interval_seconds * 2)
    if abs(elapsed_seconds - duration_seconds) > duration_tolerance:
        raise EvidenceValidationError("OTel soak reported duration does not match its timestamps")

    raw_samples, samples = _read_soak_samples(report, report_path, started_at, finished_at)
    warmup_seconds = _finite_nonnegative(report.get("warmup_seconds"), "OTel soak warmup_seconds")
    if warmup_seconds >= elapsed_seconds:
        raise EvidenceValidationError("OTel soak warm-up must be shorter than its duration")
    minimum_raw_samples = math.floor(elapsed_seconds / sample_interval_seconds * 0.9)
    minimum_samples = math.floor((elapsed_seconds - warmup_seconds) / sample_interval_seconds * 0.9)
    if len(raw_samples) < minimum_raw_samples or len(samples) < minimum_samples:
        raise EvidenceValidationError("OTel soak has insufficient metric samples")

    thresholds, worker_limits, task_limits = _validate_thresholds(report)
    observations = report.get("observations")
    if not isinstance(observations, dict):
        raise EvidenceValidationError("OTel soak observations are missing")
    workers = [_sample_kind_values(sample, "workers", WORKER_KINDS) for sample in samples]
    worker_availability = [_sample_kind_values(sample, "worker_availability", WORKER_KINDS) for sample in samples]
    tasks = [_sample_kind_values(sample, "tasks", TASK_KINDS) for sample in samples]
    task_availability = [_sample_kind_values(sample, "task_availability", TASK_KINDS) for sample in samples]
    worker_maxima = {kind: max(value[kind] for value in workers) for kind in WORKER_KINDS}
    task_maxima = {kind: max(value[kind] for value in tasks) for kind in TASK_KINDS}
    authorization_metrics_monotonic = all(
        _sample_number(current, field) >= _sample_number(previous, field)
        for previous, current in pairwise(samples)
        for field in (
            "editor_authorization_requests",
            "editor_authorization_errors",
            "editor_authorization_duration_microseconds",
        )
    )
    authorization_requests = _sample_number(samples[-1], "editor_authorization_requests") - _sample_number(
        samples[0], "editor_authorization_requests"
    )
    authorization_errors = _sample_number(samples[-1], "editor_authorization_errors") - _sample_number(
        samples[0], "editor_authorization_errors"
    )
    authorization_duration = _sample_number(samples[-1], "editor_authorization_duration_microseconds") - _sample_number(
        samples[0], "editor_authorization_duration_microseconds"
    )
    authorization_error_ratio = authorization_errors / authorization_requests if authorization_requests > 0 else 0.0
    authorization_average = authorization_duration / authorization_requests if authorization_requests > 0 else 0.0
    expected_observations = {
        "memory_start_bytes": _sample_number(samples[0], "memory_total"),
        "memory_end_bytes": _sample_number(samples[-1], "memory_total"),
        "memory_max_bytes": max(_sample_number(sample, "memory_total") for sample in samples),
        "memory_growth_bytes": _sample_number(samples[-1], "memory_total") - _sample_number(samples[0], "memory_total"),
        "memory_slope_bytes_per_hour": _linear_slope_per_hour(samples, "memory_total"),
        "runtime_uptime_start_seconds": _sample_number(samples[0], "runtime_uptime_seconds"),
        "runtime_uptime_end_seconds": _sample_number(samples[-1], "runtime_uptime_seconds"),
        "mailbox_total_max": max(_sample_number(sample, "mailbox_total") for sample in samples),
        "mailbox_max_max": max(_sample_number(sample, "mailbox_max") for sample in samples),
        "outbound_queue_length_max": max(_sample_number(sample, "outbound_queue_length") for sample in samples),
        "slow_client_queue_length_max": max(_sample_number(sample, "slow_client_queue_length") for sample in samples),
        "sockets_max": max(_sample_number(sample, "sockets") for sample in samples),
        "editor_authorization_requests_observed": authorization_requests,
        "editor_authorization_errors_observed": authorization_errors,
        "editor_authorization_error_ratio": authorization_error_ratio,
        "editor_authorization_average_microseconds": authorization_average,
        "accepted_spans_end": _sample_number(samples[-1], "accepted_spans"),
        "accepted_metric_points_end": _sample_number(samples[-1], "accepted_metric_points"),
    }
    for field, expected in expected_observations.items():
        _assert_reported_number(observations, field, expected)
    if observations.get("worker_active_max") != worker_maxima or observations.get("task_active_max") != task_maxima:
        raise EvidenceValidationError("OTel soak activity observations do not match raw samples")

    memory_bounded = (
        expected_observations["memory_growth_bytes"] <= thresholds["memory_growth_bytes"]
        and expected_observations["memory_slope_bytes_per_hour"] <= thresholds["memory_slope_bytes_per_hour"]
    )
    mailboxes_bounded = (
        expected_observations["mailbox_total_max"] <= thresholds["mailbox_total"]
        and expected_observations["mailbox_max_max"] <= thresholds["mailbox_max"]
    )
    buffers_bounded = (
        expected_observations["outbound_queue_length_max"] <= thresholds["outbound_queue_length"]
        and expected_observations["slow_client_queue_length_max"] <= thresholds["slow_client_queue_length"]
    )
    authorization_bounded = (
        authorization_metrics_monotonic
        and authorization_requests > 0
        and authorization_error_ratio <= thresholds["editor_authorization_error_ratio"]
        and authorization_average <= thresholds["editor_authorization_average_microseconds"]
    )
    registries_bounded = all(value[kind] == 1 for value in worker_availability for kind in WORKER_KINDS)
    registries_bounded = registries_bounded and all(
        value[kind] == 1 for value in task_availability for kind in TASK_KINDS
    )
    registries_bounded = registries_bounded and all(worker_maxima[kind] <= worker_limits[kind] for kind in WORKER_KINDS)
    registries_bounded = registries_bounded and all(task_maxima[kind] <= task_limits[kind] for kind in TASK_KINDS)
    expected_bounded = {
        "memory": memory_bounded,
        "mailboxes": mailboxes_bounded,
        "buffers": buffers_bounded,
        "authorization": authorization_bounded,
        "task_registries": registries_bounded,
    }
    if report.get("bounded") != expected_bounded:
        raise EvidenceValidationError("OTel soak bounded result does not match raw samples and thresholds")

    load_profile = report.get("load_profile")
    if not isinstance(load_profile, dict):
        raise EvidenceValidationError("OTel soak load profile is missing")
    target_sockets = _finite_nonnegative(load_profile.get("target_sockets"), "OTel load target_sockets")
    minimum_authorization_requests = _finite_nonnegative(
        load_profile.get("minimum_editor_authorization_requests"),
        "OTel load minimum_editor_authorization_requests",
    )
    required_workers = load_profile.get("required_worker_activity")
    required_tasks = load_profile.get("required_task_activity")
    if (
        not isinstance(required_workers, list)
        or not isinstance(required_tasks, list)
        or any(kind not in WORKER_KINDS for kind in required_workers)
        or any(kind not in TASK_KINDS for kind in required_tasks)
        or not minimum_authorization_requests.is_integer()
        or minimum_authorization_requests < 1
    ):
        raise EvidenceValidationError("OTel soak required activity profile is invalid")
    representative_load = expected_observations["sockets_max"] >= target_sockets
    representative_load = representative_load and authorization_requests >= minimum_authorization_requests
    representative_load = representative_load and all(worker_maxima[kind] >= 1 for kind in required_workers)
    representative_load = representative_load and all(task_maxima[kind] >= 1 for kind in required_tasks)
    _assert_reported_number(load_profile, "observed_peak_sockets", expected_observations["sockets_max"])

    telemetry_healthy = all(_sample_number(sample, "scrape_up") == 1 for sample in samples)
    telemetry_healthy = telemetry_healthy and expected_observations["accepted_spans_end"] >= 1
    telemetry_healthy = telemetry_healthy and expected_observations["accepted_metric_points_end"] >= 1
    telemetry_healthy = telemetry_healthy and all(
        _sample_number(sample, field) == 0
        for sample in samples
        for field in ("failed_spans", "refused_spans", "failed_metric_points", "refused_metric_points")
    )
    telemetry_healthy = telemetry_healthy and authorization_metrics_monotonic
    telemetry_healthy = telemetry_healthy and all(
        _sample_number(current, field) >= _sample_number(previous, field)
        for previous, current in pairwise(samples)
        for field in ("accepted_spans", "accepted_metric_points")
    )
    runtime_continuity = all(
        _sample_number(current, "runtime_uptime_seconds") >= _sample_number(previous, "runtime_uptime_seconds")
        for previous, current in pairwise(samples)
    )
    if report.get("representative_load") is not representative_load:
        raise EvidenceValidationError("OTel soak representative-load result does not match raw samples")
    if (
        report.get("telemetry_healthy") is not telemetry_healthy
        or report.get("runtime_continuity") is not runtime_continuity
    ):
        raise EvidenceValidationError("OTel soak health result does not match raw samples")

    expected_triggers = [name for name, passed in expected_bounded.items() if not passed]
    if not representative_load:
        expected_triggers.append("representative_load")
    if not telemetry_healthy:
        expected_triggers.append("telemetry_delivery")
    if not runtime_continuity:
        expected_triggers.append("runtime_restart")
    if report.get("rollback_triggers") != expected_triggers or report.get("success") is not (not expected_triggers):
        raise EvidenceValidationError("OTel soak success result does not match its evidence")
    if expected_triggers:
        raise EvidenceValidationError("OTel soak contains rollback triggers")
    return elapsed_seconds


def validate(editor_manifest_path: Path, otel_soak_path: Path, expected_runtime_image: str) -> tuple[int, float]:
    editor_document_count = validate_editor_manifest(_read_object(editor_manifest_path))
    soak_seconds = validate_otel_soak(_read_object(otel_soak_path), otel_soak_path, expected_runtime_image)
    return editor_document_count, soak_seconds


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    _ = parser.add_argument("editor_manifest", type=Path)
    _ = parser.add_argument("otel_soak_report", type=Path)
    _ = parser.add_argument("runtime_image", help="Exact sha256 image ID selected for deployment")
    args = parser.parse_args()
    editor_manifest = cast(Path, args.editor_manifest).resolve()
    otel_soak_report = cast(Path, args.otel_soak_report).resolve()
    try:
        editor_document_count, soak_seconds = validate(editor_manifest, otel_soak_report, args.runtime_image)
    except EvidenceValidationError as error:
        parser.error(str(error))
    print(
        f"Phoenix cutover evidence passed: editor_documents={editor_document_count} "
        f"otel_soak_hours={soak_seconds / 3600:.1f}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
