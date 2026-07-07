from __future__ import annotations

import asyncio
from collections.abc import Callable
from datetime import datetime
import inspect
import json
import random
import time
from typing import Any

from .config import MqttConfig
from .control import RunControl, controlled_sleep, wait_if_paused
from .events import EventCallback, emit_log
from .metrics import MetricsCollector


async def run_mqtt_load(
    config: MqttConfig,
    metrics: MetricsCollector,
    control: RunControl,
    event_callback: EventCallback | None,
) -> None:
    try:
        from gmqtt import Client as MQTTClient
    except ImportError as exc:
        raise RuntimeError("MQTT 模式需要安装 gmqtt：pip install -r requirements.txt") from exc

    host, port, tls = config.endpoint()
    emit_log(event_callback, f"MQTT broker: {host}:{port}, tls={tls}")
    semaphore = asyncio.Semaphore(config.max_concurrency)
    await _ramp_devices(
        config=config,
        control=control,
        log_callback=lambda message: emit_log(event_callback, message),
        device_runner=lambda device_id, index: _mqtt_device_loop(
            config, MQTTClient, host, port, tls, semaphore, metrics, control, device_id, index
        ),
    )


async def _ramp_devices(
    config: MqttConfig,
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
                log_callback(f"MQTT 已启动模拟设备: {index + 1}/{config.device_count}")
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


async def _mqtt_device_loop(
    config: MqttConfig,
    mqtt_client_cls: Any,
    host: str,
    port: int,
    tls: bool,
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
    client = mqtt_client_cls(device_id)
    username = config.username or (device_id if config.auth_token else "")
    password = config.password or config.auth_token
    if username or password:
        client.set_auth_credentials(username, password)

    metrics.device_started()
    connected = False
    try:
        started = time.perf_counter()
        try:
            async with semaphore:
                await client.connect(host, port, ssl=tls, keepalive=60)
            connected = True
            metrics.record_result(True, (time.perf_counter() - started) * 1000, code="mqtt_connect")
        except Exception as exc:
            metrics.record_result(False, (time.perf_counter() - started) * 1000, exception=_exception_name(exc))
            await controlled_sleep(2.0, control, config.duration_seconds)
            return

        while not control.stop_event.is_set() and not control.duration_reached(config.duration_seconds):
            await wait_if_paused(control)
            now = control.active_elapsed()
            if now >= next_heartbeat:
                sequence += 1
                await _publish_event(
                    client,
                    semaphore,
                    _mqtt_topic(config, device_id, "heartbeat"),
                    _make_payload(config, device_id, "heartbeat", sequence, rng),
                    metrics,
                )
                next_heartbeat += config.heartbeat_interval
            if now >= next_status:
                sequence += 1
                await _publish_event(
                    client,
                    semaphore,
                    _mqtt_topic(config, device_id, "status"),
                    _make_payload(config, device_id, "status", sequence, rng),
                    metrics,
                )
                if rng.random() < config.alarm_probability:
                    sequence += 1
                    await _publish_event(
                        client,
                        semaphore,
                        _mqtt_topic(config, device_id, "fault"),
                        _make_payload(config, device_id, "fault", sequence, rng),
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
        if connected:
            result = client.disconnect()
            if inspect.isawaitable(result):
                await result
        metrics.device_stopped()


async def _publish_event(
    client: Any,
    semaphore: asyncio.Semaphore,
    topic: str,
    payload: dict[str, Any],
    metrics: MetricsCollector,
) -> None:
    started = time.perf_counter()
    try:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        async with semaphore:
            result = client.publish(topic, body, qos=0)
            if inspect.isawaitable(result):
                await result
        metrics.record_result(True, (time.perf_counter() - started) * 1000, code="mqtt_publish")
    except Exception as exc:
        metrics.record_result(False, (time.perf_counter() - started) * 1000, exception=_exception_name(exc))


def _make_payload(
    config: MqttConfig,
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
    if event_type == "fault":
        payload["fault"] = {
            "code": rng.choice(["LOW_BATTERY", "TAMPER", "NETWORK_DROP", "VIDEO_FAULT"]),
            "level": rng.choice(["minor", "major", "critical"]),
        }

    encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    if config.payload_size > len(encoded):
        overhead = len(json.dumps({**payload, "padding": ""}, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
        payload["padding"] = "x" * max(0, config.payload_size - overhead)
    return payload


def _mqtt_topic(config: MqttConfig, device_id: str, suffix: str) -> str:
    prefix = config.topic_prefix.strip().strip("/") or "devices"
    return f"{prefix}/{device_id}/{suffix}"


def _exception_name(exc: Exception) -> str:
    message = str(exc).strip()
    if not message:
        return exc.__class__.__name__
    return f"{exc.__class__.__name__}: {message[:120]}"
