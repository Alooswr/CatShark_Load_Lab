from __future__ import annotations

import asyncio
from dataclasses import dataclass
import socket

from .sip_parser import SipMessage, parse_sip_message, read_sip_message


class SipTransport:
    async def start(self) -> None:
        raise NotImplementedError

    async def send(self, data: bytes) -> None:
        raise NotImplementedError

    async def recv(self, timeout: float) -> SipMessage:
        raise NotImplementedError

    async def close(self) -> None:
        raise NotImplementedError


class _UdpProtocol(asyncio.DatagramProtocol):
    def __init__(self, queue: asyncio.Queue[bytes]) -> None:
        self.queue = queue

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        self.queue.put_nowait(data)

    def error_received(self, exc: Exception) -> None:
        self.queue.put_nowait(f"SIP/2.0 599 UDP Error\r\nContent-Length: 0\r\n\r\n".encode("utf-8"))


@dataclass(slots=True)
class UDPTransport(SipTransport):
    local_ip: str
    local_port: int
    remote_ip: str
    remote_port: int
    _transport: asyncio.DatagramTransport | None = None
    _queue: asyncio.Queue[bytes] | None = None

    async def start(self) -> None:
        loop = asyncio.get_running_loop()
        self._queue = asyncio.Queue()
        transport, _ = await loop.create_datagram_endpoint(
            lambda: _UdpProtocol(self._queue),
            local_addr=(self.local_ip, self.local_port),
            remote_addr=(self.remote_ip, self.remote_port),
        )
        self._transport = transport

    async def send(self, data: bytes) -> None:
        if not self._transport:
            raise RuntimeError("UDP transport is not started")
        self._transport.sendto(data)

    async def recv(self, timeout: float) -> SipMessage:
        if not self._queue:
            raise RuntimeError("UDP transport is not started")
        data = await asyncio.wait_for(self._queue.get(), timeout=timeout)
        return parse_sip_message(data)

    async def close(self) -> None:
        if self._transport:
            self._transport.close()
            self._transport = None


@dataclass(slots=True)
class TCPTransport(SipTransport):
    local_ip: str
    local_port: int
    remote_ip: str
    remote_port: int
    _reader: asyncio.StreamReader | None = None
    _writer: asyncio.StreamWriter | None = None

    async def start(self) -> None:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        sock.setblocking(False)
        sock.bind((self.local_ip, self.local_port))
        await asyncio.get_running_loop().sock_connect(sock, (self.remote_ip, self.remote_port))
        self._reader, self._writer = await asyncio.open_connection(sock=sock)

    async def send(self, data: bytes) -> None:
        if not self._writer:
            raise RuntimeError("TCP transport is not started")
        self._writer.write(data)
        await self._writer.drain()

    async def recv(self, timeout: float) -> SipMessage:
        if not self._reader:
            raise RuntimeError("TCP transport is not started")
        return parse_sip_message(await read_sip_message(self._reader, timeout))

    async def close(self) -> None:
        if self._writer:
            self._writer.close()
            try:
                await asyncio.wait_for(self._writer.wait_closed(), timeout=1.0)
            except (asyncio.TimeoutError, ConnectionError):
                pass
            self._writer = None
            self._reader = None


def make_transport(
    protocol: str,
    local_ip: str,
    local_port: int,
    remote_ip: str,
    remote_port: int,
) -> SipTransport:
    if protocol.upper() == "UDP":
        return UDPTransport(local_ip, local_port, remote_ip, remote_port)
    if protocol.upper() == "TCP":
        return TCPTransport(local_ip, local_port, remote_ip, remote_port)
    raise ValueError(f"Unsupported SIP transport: {protocol}")
