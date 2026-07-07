from __future__ import annotations

import asyncio
import random
import time

from ..config import Gb28181Config
from ..control import RunControl, controlled_sleep, wait_if_paused
from ..metrics import MetricsCollector
from .auth import build_digest_authorization, parse_www_authenticate
from .media import MediaCoordinator
from .sip_messages import (
    SipIdentity,
    build_catalog_response,
    build_invite_ok,
    build_keepalive,
    build_register,
    build_sip_response,
    make_identity,
)
from .sip_parser import SipMessage, parse_sdp_target, xml_value
from .transports import SipTransport, make_transport


class Gb28181Device:
    def __init__(
        self,
        config: Gb28181Config,
        metrics: MetricsCollector,
        control: RunControl,
        media: MediaCoordinator,
        device_id: str,
        index: int,
    ) -> None:
        self.config = config
        self.sip = config.sip
        self.metrics = metrics
        self.control = control
        self.media = media
        self.device_id = device_id
        self.index = index
        self.local_port = self.sip.local_sip_start_port + index
        self.identity: SipIdentity | None = None
        self.transport: SipTransport | None = None
        self.cseq = 1
        self.sn = 1
        self.online = False
        self.rng = random.Random(f"{device_id}:{index}")

    async def run(self) -> None:
        self.metrics.device_started()
        try:
            try:
                await self._connect()
            except Exception as exc:
                self.metrics.record_failure(f"sip_connect_{exc.__class__.__name__}: {str(exc)[:120]}")
                return
            registered = await self._register()
            if not registered:
                return
            next_heartbeat = self.control.active_elapsed()
            while not self.control.stop_event.is_set() and not self.control.duration_reached(self.sip.duration_seconds):
                await wait_if_paused(self.control)
                await self._process_incoming(timeout=0.05)
                now = self.control.active_elapsed()
                if now >= next_heartbeat:
                    await self._send_keepalive()
                    next_heartbeat += self.sip.heartbeat_interval
                    if self._should_go_offline():
                        await self._simulate_offline()
                        next_heartbeat = self.control.active_elapsed() + self.sip.heartbeat_interval
                await asyncio.sleep(0.02)
        finally:
            try:
                await self._set_online(False)
            except Exception:
                pass
            try:
                await self._close_transport()
            except (Exception, asyncio.CancelledError):
                pass
            self.metrics.device_stopped()

    async def _connect(self) -> None:
        self.identity = make_identity(
            self.device_id,
            self.sip.domain_id,
            self.sip.server_ip,
            self.sip.server_port,
            self.sip.local_device_ip,
            self.local_port,
            self.sip.transport,
        )
        self.transport = make_transport(
            self.sip.transport,
            self.sip.local_device_ip,
            self.local_port,
            self.sip.server_ip,
            self.sip.server_port,
        )
        await self.transport.start()

    async def _register(self) -> bool:
        assert self.identity and self.transport
        started = time.perf_counter()
        await self._send(build_register(self.identity, self._next_cseq(), self.sip.register_expires))
        response = await self._recv_response_or_timeout()
        if response and response.status_code == 401 and self.sip.password:
            challenge = parse_www_authenticate(response.header("www-authenticate"))
            authorization = build_digest_authorization(
                username=self.device_id,
                password=self.sip.password,
                method="REGISTER",
                uri=f"sip:{self.sip.domain_id}",
                challenge=challenge,
            )
            await self._send(build_register(self.identity, self._next_cseq(), self.sip.register_expires, authorization))
            response = await self._recv_response_or_timeout()
        latency_ms = (time.perf_counter() - started) * 1000
        if response and response.status_code == 200:
            self.metrics.record_result(True, latency_ms, code=200)
            self.metrics.increment("register_success_count")
            await self._set_online(True)
            return True
        self.metrics.record_result(False, latency_ms, code=response.status_code if response else "timeout")
        self.metrics.increment("register_failure_count")
        return False

    async def _send_keepalive(self) -> None:
        assert self.identity
        await self._send(build_keepalive(self.identity, self._next_cseq(), self._next_sn()))
        self.metrics.increment("heartbeat_sent_count")
        response = await self._recv_response_or_timeout()
        if response is None:
            self.metrics.increment("timeout_count")

    async def _process_incoming(self, timeout: float) -> None:
        if not self.transport:
            return
        try:
            message = await self.transport.recv(timeout)
        except TimeoutError:
            return
        except asyncio.TimeoutError:
            return
        except Exception as exc:
            self.metrics.record_failure(f"sip_recv_{exc.__class__.__name__}: {str(exc)[:120]}")
            return
        await self._handle_message(message)

    async def _recv_response_or_timeout(self) -> SipMessage | None:
        if not self.transport:
            return None
        try:
            while True:
                message = await self.transport.recv(self.sip.sip_timeout)
                if message.is_response:
                    if message.status_code is not None:
                        self.metrics.record_message(code=message.status_code)
                    return message
                await self._handle_message(message)
        except asyncio.TimeoutError:
            self.metrics.record_failure("sip_timeout", code="timeout")
            self.metrics.increment("timeout_count")
            return None
        except Exception as exc:
            self.metrics.record_failure(f"sip_recv_{exc.__class__.__name__}: {str(exc)[:120]}")
            return None

    async def _handle_message(self, message: SipMessage) -> None:
        self.metrics.record_message()
        if message.is_response:
            if message.status_code is not None:
                self.metrics.record_message(code=message.status_code)
            return
        if message.method == "MESSAGE":
            await self._send(build_sip_response(message, 200, "OK"))
            cmd = xml_value(message.body, "CmdType")
            if cmd.lower() == "catalog":
                self.metrics.increment("catalog_query_count")
                assert self.identity
                await self._send(build_catalog_response(self.identity, message, self._next_cseq(), self.sip.channels_per_device))
                self.metrics.increment("catalog_response_count")
        elif message.method == "INVITE":
            self.metrics.increment("media_invite_count")
            assert self.identity
            target = parse_sdp_target(message.body)
            media_port = self.media.allocate_port()
            codec_name = "PS" if self.config.media.payload_format.upper() == "PS_OVER_RTP" else self.config.media.video_codec.upper()
            payload_type = "96" if self.config.media.video_codec.upper() == "H264" else "98"
            await self._send(build_invite_ok(self.identity, message, media_port, payload_type, codec_name))
            if target:
                self.media.start_stream(self.device_id, target[0], target[1])
            else:
                self.metrics.increment("media_invite_without_sdp_target_count")
        else:
            await self._send(build_sip_response(message, 200, "OK"))

    async def _send(self, data: bytes) -> None:
        if not self.transport:
            return
        await self.transport.send(data)
        self.metrics.record_message()

    async def _set_online(self, online: bool) -> None:
        if self.online == online:
            return
        self.online = online
        self.metrics.adjust_gauge("online_devices", 1 if online else -1)

    def _next_cseq(self) -> int:
        value = self.cseq
        self.cseq += 1
        return value

    def _next_sn(self) -> int:
        value = self.sn
        self.sn += 1
        return value

    def _should_go_offline(self) -> bool:
        return self.sip.offline_simulation_enabled and self.rng.random() < self.sip.offline_probability

    async def _simulate_offline(self) -> None:
        self.metrics.increment("offline_count")
        await self._set_online(False)
        await self._close_transport()
        await controlled_sleep(self.sip.offline_duration_seconds, self.control, self.sip.duration_seconds)
        if self.control.stop_event.is_set() or self.control.duration_reached(self.sip.duration_seconds):
            return
        self.metrics.increment("reconnect_count")
        await self._connect()
        if await self._register():
            self.metrics.increment("reconnect_success_count")

    async def _close_transport(self) -> None:
        if self.transport:
            await self.transport.close()
            self.transport = None
