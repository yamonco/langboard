"""Verify that the local OTel Collector receives Phoenix metrics and traces."""

import argparse
from time import monotonic, sleep
from scripts.phoenix_otel_metrics import (
    MetricSample,
    PrometheusMetricsError,
    parse_samples,
    read_metrics,
    require_sample,
)


OTelCheckError = PrometheusMetricsError


def verify_forwarded_metrics(samples: dict[str, list[MetricSample]]) -> None:
    if require_sample(samples, "up", label='job="langboard_socket_phoenix"').value != 1:
        raise OTelCheckError("Phoenix Prometheus scrape target is not up")

    for name in (
        "vm_memory_total",
        "vm_memory_binary",
        "vm_memory_processes",
        "langboard_socket_runtime_process_count",
        "langboard_socket_runtime_sockets_count",
        "langboard_socket_runtime_mailbox_total",
        "langboard_socket_runtime_mailbox_max",
    ):
        if require_sample(samples, name).value < 0:
            raise OTelCheckError(f"Metric must not be negative: {name}")

    for kind in ("board_chat", "editor_ai", "editor_document"):
        _ = require_sample(samples, "langboard_socket_runtime_workers_active", label=f'kind="{kind}"')
        available = require_sample(
            samples,
            "langboard_socket_runtime_workers_available",
            label=f'kind="{kind}"',
        )
        if available.value != 1:
            raise OTelCheckError(f"Phoenix worker metrics are unavailable: {kind}")

    for kind in ("command", "graph_stream"):
        _ = require_sample(samples, "langboard_socket_runtime_tasks_active", label=f'kind="{kind}"')
        available = require_sample(
            samples,
            "langboard_socket_runtime_tasks_available",
            label=f'kind="{kind}"',
        )
        if available.value != 1:
            raise OTelCheckError(f"Phoenix task metrics are unavailable: {kind}")

    authorization_count = require_sample(
        samples,
        "langboard_socket_authorization_request_count_total",
        label='route="/health"',
    )
    if authorization_count.value < 1 or 'result="success"' not in authorization_count.labels:
        raise OTelCheckError("Phoenix authorization request metrics do not include a successful health check")

    authorization_duration = require_sample(
        samples,
        "langboard_socket_authorization_request_duration_microseconds_total",
        label='route="/health"',
    )
    if authorization_duration.value < 0 or 'result="success"' not in authorization_duration.labels:
        raise OTelCheckError("Phoenix authorization duration metrics are invalid")


def verify_collector_metrics(samples: dict[str, list[MetricSample]]) -> None:
    accepted_spans = require_sample(
        samples,
        "otelcol_receiver_accepted_spans",
        label='receiver="otlp"',
    )
    if accepted_spans.value < 1:
        raise OTelCheckError("Collector has not accepted a Phoenix OTLP span")

    accepted_metrics = require_sample(
        samples,
        "otelcol_receiver_accepted_metric_points",
        label='receiver="prometheus/socket_phoenix"',
    )
    if accepted_metrics.value < 1:
        raise OTelCheckError("Collector has not accepted a Phoenix metric point")

    for name, receiver in (
        ("otelcol_receiver_failed_spans", "otlp"),
        ("otelcol_receiver_refused_spans", "otlp"),
        ("otelcol_receiver_failed_metric_points", "prometheus/socket_phoenix"),
        ("otelcol_receiver_refused_metric_points", "prometheus/socket_phoenix"),
    ):
        if require_sample(samples, name, label=f'receiver="{receiver}"').value != 0:
            raise OTelCheckError(f"Collector reports rejected telemetry: {name}")


def wait_for_delivery(
    metrics_url: str,
    collector_metrics_url: str,
    request_timeout_seconds: float,
    wait_seconds: float,
    retry_interval_seconds: float,
) -> None:
    deadline = monotonic() + wait_seconds
    while True:
        try:
            verify_forwarded_metrics(parse_samples(read_metrics(metrics_url, request_timeout_seconds)))
            verify_collector_metrics(parse_samples(read_metrics(collector_metrics_url, request_timeout_seconds)))
            return
        except OTelCheckError:
            remaining_seconds = deadline - monotonic()
            if remaining_seconds <= 0:
                raise
            sleep(min(retry_interval_seconds, remaining_seconds))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    _ = parser.add_argument("--metrics-url", required=True)
    _ = parser.add_argument("--collector-metrics-url", required=True)
    _ = parser.add_argument("--timeout-seconds", type=float, default=10.0)
    _ = parser.add_argument("--wait-seconds", type=float, default=30.0)
    _ = parser.add_argument("--retry-interval-seconds", type=float, default=1.0)
    args = parser.parse_args()

    try:
        if args.timeout_seconds <= 0 or args.wait_seconds < 0 or args.retry_interval_seconds <= 0:
            raise OTelCheckError("Timeouts must be positive and wait-seconds must not be negative")
        wait_for_delivery(
            args.metrics_url,
            args.collector_metrics_url,
            args.timeout_seconds,
            args.wait_seconds,
            args.retry_interval_seconds,
        )
    except OTelCheckError as error:
        parser.error(str(error))

    print("Phoenix OTel delivery passed: metrics=accepted traces=accepted rejected=0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
