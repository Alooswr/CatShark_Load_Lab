from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

from .config import AppConfig
from .control import RunControl
from .events import EventCallback, emit_log, emit_metrics
from .metrics import MetricsCollector
from .report import build_report


async def run_load_test(
    config: AppConfig,
    event_callback: EventCallback | None = None,
    control: RunControl | None = None,
) -> dict[str, Any]:
    config.ensure_valid()
    control = control or RunControl()
    metrics = MetricsCollector()
    started_at = datetime.now().astimezone()
    duration_seconds = config.duration_seconds()
    control.mark_started()
    emit_log(event_callback, f"开始测试: {config.mode.upper()}")

    reporter = asyncio.create_task(_report_metrics(metrics, control, duration_seconds, event_callback))
    try:
        mode = config.mode.upper()
        if mode == "HTTP":
            from .http_runner import run_http_load

            await run_http_load(config.http, metrics, control, event_callback)
        elif mode == "MQTT":
            from .mqtt_runner import run_mqtt_load

            await run_mqtt_load(config.mqtt, metrics, control, event_callback)
        elif mode == "GB28181":
            from .gb28181.runner import run_gb28181_load

            await run_gb28181_load(config.gb28181, metrics, control, event_callback)
        else:
            raise ValueError(f"不支持的压测模式: {config.mode}")
        if not control.stop_event.is_set() and control.duration_reached(duration_seconds):
            control.request_stop("duration_complete")
    finally:
        reporter.cancel()
        await asyncio.gather(reporter, return_exceptions=True)

    ended_at = datetime.now().astimezone()
    final_snapshot = metrics.snapshot(control.active_elapsed())
    emit_metrics(event_callback, final_snapshot.to_dict())
    report = build_report(config, final_snapshot, started_at, ended_at, control.finish_reason)
    emit_log(event_callback, f"测试结束: {control.finish_reason}")
    return report


async def _report_metrics(
    metrics: MetricsCollector,
    control: RunControl,
    duration_seconds: float,
    event_callback: EventCallback | None,
) -> None:
    while not control.stop_event.is_set() and not control.duration_reached(duration_seconds):
        emit_metrics(event_callback, metrics.snapshot(control.active_elapsed()).to_dict())
        await asyncio.sleep(1.0)
