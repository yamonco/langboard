"""Small Prometheus text helpers shared by Phoenix OTel verification tools."""

import math
import re
from dataclasses import dataclass
from urllib.error import URLError
from urllib.request import urlopen


SAMPLE_PATTERN = re.compile(
    r"^(?P<name>[a-zA-Z_:][a-zA-Z0-9_:]*)"
    r"(?:\{(?P<labels>.*)\})?\s+"
    r"(?P<value>[-+]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][-+]?\d+)?)"
    r"(?:\s+\d+)?$"
)


class PrometheusMetricsError(RuntimeError):
    pass


@dataclass(frozen=True)
class MetricSample:
    labels: str
    value: float


def read_metrics(url: str, timeout_seconds: float) -> str:
    try:
        with urlopen(url, timeout=timeout_seconds) as response:
            if response.status != 200:
                raise PrometheusMetricsError(f"Metrics endpoint returned HTTP {response.status}: {url}")
            return response.read().decode("utf-8")
    except (OSError, UnicodeError, URLError) as error:
        raise PrometheusMetricsError(f"Cannot read metrics endpoint {url}: {error}") from error


def parse_samples(text: str) -> dict[str, list[MetricSample]]:
    samples: dict[str, list[MetricSample]] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        match = SAMPLE_PATTERN.fullmatch(line)
        if match is None:
            continue
        value = float(match.group("value"))
        if not math.isfinite(value):
            raise PrometheusMetricsError(f"Metric contains a non-finite value: {match.group('name')}")
        samples.setdefault(match.group("name"), []).append(
            MetricSample(labels=match.group("labels") or "", value=value)
        )
    return samples


def require_sample(
    samples: dict[str, list[MetricSample]],
    name: str,
    *,
    label: str | None = None,
) -> MetricSample:
    sample = find_sample(samples, name, label=label)
    if sample is None:
        suffix = f" with {label}" if label else ""
        raise PrometheusMetricsError(f"Missing metric {name}{suffix}")
    return sample


def find_sample(
    samples: dict[str, list[MetricSample]],
    name: str,
    *,
    label: str | None = None,
) -> MetricSample | None:
    return next((sample for sample in samples.get(name, []) if label is None or label in sample.labels), None)
