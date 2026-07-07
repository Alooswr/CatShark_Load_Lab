from __future__ import annotations

from collections import Counter, deque
from dataclasses import dataclass
import threading
import time
from typing import Any


def _percentile(sorted_values: list[float], percentile: float) -> float:
    if not sorted_values:
        return 0.0
    if len(sorted_values) == 1:
        return sorted_values[0]
    rank = (len(sorted_values) - 1) * percentile
    lower = int(rank)
    upper = min(lower + 1, len(sorted_values) - 1)
    weight = rank - lower
    return sorted_values[lower] * (1 - weight) + sorted_values[upper] * weight


@dataclass(slots=True)
class MetricsSnapshot:
    active_devices: int
    total_requests: int
    success_count: int
    failure_count: int
    throughput: float
    avg_latency_ms: float
    p50_latency_ms: float
    p95_latency_ms: float
    p99_latency_ms: float
    status_codes: dict[str, int]
    exceptions: dict[str, int]
    counters: dict[str, int]
    gauges: dict[str, float]
    active_elapsed_seconds: float

    def to_dict(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "active_devices": self.active_devices,
            "total_requests": self.total_requests,
            "success_count": self.success_count,
            "failure_count": self.failure_count,
            "throughput": self.throughput,
            "avg_latency_ms": self.avg_latency_ms,
            "p50_latency_ms": self.p50_latency_ms,
            "p95_latency_ms": self.p95_latency_ms,
            "p99_latency_ms": self.p99_latency_ms,
            "status_codes": self.status_codes,
            "exceptions": self.exceptions,
            "counters": self.counters,
            "gauges": self.gauges,
            "active_elapsed_seconds": self.active_elapsed_seconds,
        }
        data.update(self.counters)
        data.update(self.gauges)
        return data


class MetricsCollector:
    def __init__(self, latency_sample_limit: int = 200_000, throughput_window: float = 5.0) -> None:
        self._lock = threading.Lock()
        self._active_devices = 0
        self._total_requests = 0
        self._success_count = 0
        self._failure_count = 0
        self._latency_sum_ms = 0.0
        self._latencies_ms: deque[float] = deque(maxlen=latency_sample_limit)
        self._event_times: deque[float] = deque()
        self._status_codes: Counter[str] = Counter()
        self._exceptions: Counter[str] = Counter()
        self._counters: Counter[str] = Counter()
        self._gauges: dict[str, float] = {}
        self._throughput_window = throughput_window

    def device_started(self) -> None:
        with self._lock:
            self._active_devices += 1

    def device_stopped(self) -> None:
        with self._lock:
            self._active_devices = max(0, self._active_devices - 1)

    def increment(self, name: str, value: int = 1) -> None:
        with self._lock:
            self._counters[name] += value

    def set_gauge(self, name: str, value: float) -> None:
        with self._lock:
            self._gauges[name] = value

    def adjust_gauge(self, name: str, delta: float) -> None:
        with self._lock:
            next_value = self._gauges.get(name, 0.0) + delta
            self._gauges[name] = next_value
            peak_name = f"peak_{name}"
            if next_value > self._gauges.get(peak_name, 0.0):
                self._gauges[peak_name] = next_value

    def record_result(
        self,
        success: bool,
        latency_ms: float,
        code: str | int | None = None,
        exception: str | None = None,
    ) -> None:
        now = time.monotonic()
        with self._lock:
            self._total_requests += 1
            if success:
                self._success_count += 1
            else:
                self._failure_count += 1
            self._latency_sum_ms += max(0.0, latency_ms)
            self._latencies_ms.append(max(0.0, latency_ms))
            self._event_times.append(now)
            if code is not None:
                self._status_codes[str(code)] += 1
            if exception:
                self._exceptions[exception] += 1

    def record_message(self, code: str | int | None = None) -> None:
        now = time.monotonic()
        with self._lock:
            self._total_requests += 1
            self._success_count += 1
            self._event_times.append(now)
            if code is not None:
                self._status_codes[str(code)] += 1

    def record_failure(self, exception: str, code: str | int | None = None) -> None:
        now = time.monotonic()
        with self._lock:
            self._total_requests += 1
            self._failure_count += 1
            self._event_times.append(now)
            if code is not None:
                self._status_codes[str(code)] += 1
            self._exceptions[exception] += 1

    def snapshot(self, active_elapsed_seconds: float) -> MetricsSnapshot:
        now = time.monotonic()
        with self._lock:
            while self._event_times and now - self._event_times[0] > self._throughput_window:
                self._event_times.popleft()
            latencies = sorted(self._latencies_ms)
            total = self._total_requests
            throughput = len(self._event_times) / self._throughput_window
            avg_latency = self._latency_sum_ms / total if total else 0.0
            return MetricsSnapshot(
                active_devices=self._active_devices,
                total_requests=total,
                success_count=self._success_count,
                failure_count=self._failure_count,
                throughput=throughput,
                avg_latency_ms=avg_latency,
                p50_latency_ms=_percentile(latencies, 0.50),
                p95_latency_ms=_percentile(latencies, 0.95),
                p99_latency_ms=_percentile(latencies, 0.99),
                status_codes=dict(sorted(self._status_codes.items())),
                exceptions=dict(self._exceptions.most_common(20)),
                counters=dict(self._counters),
                gauges=dict(self._gauges),
                active_elapsed_seconds=active_elapsed_seconds,
            )
