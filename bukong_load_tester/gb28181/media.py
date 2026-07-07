from __future__ import annotations

import asyncio
import os
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from ..config import GbMediaConfig
from ..control import RunControl, controlled_sleep
from ..events import EventCallback, emit_log
from ..metrics import MetricsCollector


class RtpSender(Protocol):
    async def send_for(self, seconds: float) -> None:
        ...


@dataclass(slots=True)
class RtpUdpSender:
    local_ip: str
    local_port: int
    remote_ip: str
    remote_port: int
    bitrate_kbps: int
    fps: int
    payload_source: bytes

    async def send_for(self, seconds: float) -> None:
        loop = asyncio.get_running_loop()
        transport, _ = await loop.create_datagram_endpoint(
            asyncio.DatagramProtocol,
            local_addr=(self.local_ip, self.local_port),
            remote_addr=(self.remote_ip, self.remote_port),
        )
        try:
            await _send_rtp_packets(lambda packet: transport.sendto(packet), self.bitrate_kbps, self.fps, self.payload_source, seconds)
        finally:
            transport.close()


@dataclass(slots=True)
class RtpTcpSender:
    local_ip: str
    local_port: int
    remote_ip: str
    remote_port: int
    bitrate_kbps: int
    fps: int
    payload_source: bytes

    async def send_for(self, seconds: float) -> None:
        reader, writer = await asyncio.open_connection(
            host=self.remote_ip,
            port=self.remote_port,
            local_addr=(self.local_ip, self.local_port),
        )
        del reader
        try:
            async def send(packet: bytes) -> None:
                writer.write(packet)
                await writer.drain()

            await _send_rtp_packets(send, self.bitrate_kbps, self.fps, self.payload_source, seconds)
        finally:
            writer.close()
            await writer.wait_closed()


class MediaCoordinator:
    def __init__(
        self,
        config: GbMediaConfig,
        local_ip: str,
        metrics: MetricsCollector,
        control: RunControl,
        event_callback: EventCallback | None,
    ) -> None:
        self.config = config
        self.local_ip = local_ip
        self.metrics = metrics
        self.control = control
        self.event_callback = event_callback
        self._semaphore = asyncio.Semaphore(config.concurrent_streams or 1)
        self._next_port = config.local_port_start
        self._tasks: set[asyncio.Task[None]] = set()
        self._payload_source = _load_payload_source(config.video_file_path)

    def allocate_port(self) -> int:
        port = self._next_port
        self._next_port += 1
        if self._next_port > self.config.local_port_end:
            self._next_port = self.config.local_port_start
        return port

    def start_stream(self, device_id: str, remote_ip: str, remote_port: int) -> None:
        if not self.config.enabled:
            return
        task = asyncio.create_task(self._run_stream(device_id, remote_ip, remote_port))
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    async def close(self) -> None:
        for task in list(self._tasks):
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)

    async def _run_stream(self, device_id: str, remote_ip: str, remote_port: int) -> None:
        if self._semaphore.locked():
            self.metrics.increment("media_rejected_count")
            emit_log(self.event_callback, f"媒体并发已达第一版硬限制，忽略 {device_id} 的新流。")
            return
        async with self._semaphore:
            local_port = self.allocate_port()
            sender: RtpSender
            if self.config.rtp_transport.upper() == "UDP":
                sender = RtpUdpSender(
                    self.local_ip,
                    local_port,
                    remote_ip,
                    remote_port,
                    self.config.bitrate_kbps,
                    self.config.fps,
                    self._payload_source,
                )
            else:
                sender = RtpTcpSender(
                    self.local_ip,
                    local_port,
                    remote_ip,
                    remote_port,
                    self.config.bitrate_kbps,
                    self.config.fps,
                    self._payload_source,
                )
            self.metrics.increment("media_stream_started_count")
            self.metrics.adjust_gauge("media_active_streams", 1)
            try:
                while not self.control.stop_event.is_set():
                    await sender.send_for(1.0)
                    if not self.config.loop:
                        break
                    await controlled_sleep(0.01, self.control, 10**9)
            except Exception as exc:
                self.metrics.record_failure(f"media_{exc.__class__.__name__}: {str(exc)[:120]}")
            finally:
                self.metrics.adjust_gauge("media_active_streams", -1)
                self.metrics.increment("media_stream_stopped_count")


async def _send_rtp_packets(send_func, bitrate_kbps: int, fps: int, payload_source: bytes, seconds: float) -> None:
    packet_payload_size = max(160, min(1200, int((bitrate_kbps * 1000 / 8) / max(fps, 1))))
    end_time = asyncio.get_running_loop().time() + seconds
    sequence = 0
    timestamp = 0
    ssrc = 0x12345678
    while asyncio.get_running_loop().time() < end_time:
        payload = payload_source[:packet_payload_size] or (b"\x00" * packet_payload_size)
        header = struct.pack("!BBHII", 0x80, 96, sequence & 0xFFFF, timestamp & 0xFFFFFFFF, ssrc)
        result = send_func(header + payload)
        if asyncio.iscoroutine(result):
            await result
        sequence += 1
        timestamp += 3600
        await asyncio.sleep(1.0 / max(fps, 1))


def _load_payload_source(path: str) -> bytes:
    if path and Path(path).exists():
        data = Path(path).read_bytes()
        if data:
            return data[:4096]
    return os.urandom(1400)
