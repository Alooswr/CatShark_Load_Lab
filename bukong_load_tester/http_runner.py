from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import datetime
import json
import random
import time
from typing import Any
from urllib.parse import urljoin

import aiohttp

from .config import HttpConfig
from .control import RunControl, controlled_sleep, wait_if_paused
from .events import EventCallback, emit_log
from .metrics import MetricsCollector


async def run_http_load(
    config: HttpConfig,
    metrics: MetricsCollector,
    control: RunControl,
    event_callback: EventCallback | None,
) -> None:
    timeout = aiohttp.ClientTimeout(total=config.request_timeout)
    connector = aiohttp.TCPConnector(limit=config.max_concurrency, ttl_dns_cache=300)
    headers = {"User-Agent": "bukong-load-tester/0.2"}
    if config.auth_token:
        headers["Authorization"] = f"Bearer {config.auth_token}"

    async with aiohttp.ClientSession(timeout=timeout, connector=connector, headers=headers) as session:
        semaphore = asyncio.Semaphore(config.max_concurrency)
        await _ramp_devices(
            config=config,
            control=control,
            log_callback=lambda message: emit_log(event_callback, message),
            device_runner=lambda device_id, index: _http_device_loop(
                config, session, semaphore, metrics, control, device_id, index
            ),
        )


async def _ramp_devices(
    config: HttpConfig,
    control: RunControl,
    log_callback: Callable[[str], None],
    device_runner: Callable[[str, int], Any],
) -> None:
    tasks: list[asyncio.Task[Any]] = []
    interval = config.ramp_seconds / max(config.device_count - 1, 1) if config.device_count > 1 else 0.0
    try:
        for index in range(config.device_count):
            if control.stop_event.is_set() or control.duration_reached(config.duration_seconds):
                break
            await wait_if_paused(control)
            device_id = f"{config.device_id_prefix}{index + 1:06d}"
            tasks.append(asyncio.create_task(device_runner(device_id, index)))
            if (index + 1) % 50 == 0 or index == config.device_count - 1:
                log_callback(f"HTTP 已启动模拟设备: {index + 1}/{config.device_count}")
            if interval > 0 and index < config.device_count - 1:
                await controlled_sleep(interval, control, config.duration_seconds)

        while not control.stop_event.is_set() and not control.duration_reached(config.duration_seconds):
            await wait_if_paused(control)
            await asyncio.sleep(0.2)
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        if not control.stop_event.is_set():
            control.request_stop("duration_complete")


async def _http_device_loop(
    config: HttpConfig,
    session: aiohttp.ClientSession,
    semaphore: asyncio.Semaphore,
    metrics: MetricsCollector,
    control: RunControl,
    device_id: str,
    index: int,
) -> None:
    rng = random.Random(f"{device_id}:{index}")
    sequence = 0
    next_status = control.active_elapsed()
    next_heartbeat = control.active_elapsed()
    base_url = config.base_url()
    metrics.device_started()
    try:
        while not control.stop_event.is_set() and not control.duration_reached(config.duration_seconds):
            await wait_if_paused(control)
            now = control.active_elapsed()
            if now >= next_heartbeat:
                sequence += 1
                await _post_event(
                    session,
                    semaphore,
                    urljoin(base_url + "/", config.heartbeat_path.lstrip("/")),
                    _make_payload(config, device_id, "heartbeat", sequence, rng),
                    metrics,
                )
                next_heartbeat += config.heartbeat_interval
            if now >= next_status:
                sequence += 1
                await _post_event(
                    session,
                    semaphore,
                    urljoin(base_url + "/", config.status_path.lstrip("/")),
                    _make_payload(config, device_id, "status", sequence, rng),
                    metrics,
                )
                if rng.random() < config.alarm_probability:
                    sequence += 1
                    await _post_event(
                        session,
                        semaphore,
                        urljoin(base_url + "/", config.alarm_path.lstrip("/")),
                        _make_payload(config, device_id, "alarm", sequence, rng),
                        metrics,
                    )
                next_status += config.status_interval
            next_due = min(next_heartbeat, next_status)
            await controlled_sleep(
                max(0.05, min(1.0, next_due - control.active_elapsed())),
                control,
                config.duration_seconds,
            )
    finally:
        metrics.device_stopped()


async def _post_event(
    session: aiohttp.ClientSession,
    semaphore: asyncio.Semaphore,
    url: str,
    payload: dict[str, Any],
    metrics: MetricsCollector,
) -> None:
    started = time.perf_counter()
    try:
        async with semaphore:
            async with session.post(url, json=payload) as response:
                await response.read()
                latency_ms = (time.perf_counter() - started) * 1000
                metrics.record_result(200 <= response.status < 300, latency_ms, code=response.status)
    except Exception as exc:
        latency_ms = (time.perf_counter() - started) * 1000
        metrics.record_result(False, latency_ms, exception=_exception_name(exc))


def _make_payload(
    config: HttpConfig,
    device_id: str,
    event_type: str,
    sequence: int,
    rng: random.Random,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "deviceId": device_id,
        "eventType": event_type,
        "sequence": sequence,
        "timestamp": datetime.now().astimezone().isoformat(),
        "status": {
            "online": True,
            "battery": rng.randint(40, 100),
            "temperature": round(rng.uniform(20.0, 45.0), 1),
            "signal": rng.randint(1, 5),
        },
    }
    if event_type == "alarm":
        payload["fault"] = {
            "code": rng.choice(["LOW_BATTERY", "TAMPER", "NETWORK_DROP", "VIDEO_FAULT"]),
            "level": rng.choice(["minor", "major", "critical"]),
        }

    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if config.payload_size > len(encoded):
        overhead = len(json.dumps({**payload, "padding": ""}, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
        payload["padding"] = "x" * max(0, config.payload_size - overhead)
    return payload


def _exception_name(exc: Exception) -> str:
    message = str(exc).strip()
    if not message:
        return exc.__class__.__name__
    return f"{exc.__class__.__name__}: {message[:120]}"
