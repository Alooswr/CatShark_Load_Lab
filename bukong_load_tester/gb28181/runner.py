from __future__ import annotations

import asyncio

from ..config import Gb28181Config
from ..control import RunControl, controlled_sleep, wait_if_paused
from ..events import EventCallback, emit_log
from ..metrics import MetricsCollector
from .device import Gb28181Device
from .media import MediaCoordinator


async def run_gb28181_load(
    config: Gb28181Config,
    metrics: MetricsCollector,
    control: RunControl,
    event_callback: EventCallback | None,
) -> None:
    sip = config.sip
    media = MediaCoordinator(config.media, sip.local_device_ip, metrics, control, event_callback)
    emit_log(
        event_callback,
        f"GB28181 SIP {sip.transport.upper()} -> {sip.server_ip}:{sip.server_port}, devices={sip.device_count}",
    )
    if config.media.enabled:
        emit_log(
            event_callback,
            f"媒体压测启用: RTP {config.media.rtp_transport.upper()}, 第一版硬限制 {config.media.max_first_version_streams} 路。",
        )
        if config.media.trigger_mode == "active_test_stream":
            emit_log(event_callback, "主动测试推流需要外部 RTP 目标，第一版仅预留 sender，实际推流等待 INVITE/SDP。")

    tasks: list[asyncio.Task[None]] = []
    interval = sip.ramp_seconds / max(sip.device_count - 1, 1) if sip.device_count > 1 else 0.0
    try:
        for index in range(sip.device_count):
            if control.stop_event.is_set() or control.duration_reached(sip.duration_seconds):
                break
            await wait_if_paused(control)
            device_id = sip.device_id(index)
            device = Gb28181Device(config, metrics, control, media, device_id, index)
            tasks.append(asyncio.create_task(device.run()))
            if (index + 1) % 100 == 0 or index == sip.device_count - 1:
                emit_log(event_callback, f"GB28181 已启动模拟设备: {index + 1}/{sip.device_count}")
            if interval > 0 and index < sip.device_count - 1:
                await controlled_sleep(interval, control, sip.duration_seconds)

        while not control.stop_event.is_set() and not control.duration_reached(sip.duration_seconds):
            await wait_if_paused(control)
            await asyncio.sleep(0.2)
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        await media.close()
        if not control.stop_event.is_set():
            control.request_stop("duration_complete")
