from __future__ import annotations

import argparse
import asyncio
import hashlib
import re


REALM = "4403060755"
NONCE = "mock-nonce"


def parse_headers(data: bytes) -> tuple[str, dict[str, str], str]:
    header, _, body = data.partition(b"\r\n\r\n")
    text = header.decode("utf-8", errors="replace")
    lines = text.split("\r\n")
    headers = {}
    for line in lines[1:]:
        if ":" in line:
            key, value = line.split(":", 1)
            headers[key.strip().lower()] = value.strip()
    length = int(headers.get("content-length", "0") or "0")
    return lines[0], headers, body[:length].decode("utf-8", errors="replace")


def response(request: bytes, code: int, reason: str, extra_headers: list[str] | None = None) -> bytes:
    _, headers, _ = parse_headers(request)
    lines = [f"SIP/2.0 {code} {reason}"]
    for name in ("via", "from", "to", "call-id", "cseq"):
        if name in headers:
            lines.append(f"{canonical(name)}: {headers[name]}")
    lines.extend(extra_headers or [])
    lines.extend(["Content-Length: 0", "", ""])
    return "\r\n".join(lines).encode("utf-8")


def canonical(name: str) -> str:
    return {"via": "Via", "from": "From", "to": "To", "call-id": "Call-ID", "cseq": "CSeq"}.get(name, name)


def needs_auth(start_line: str, headers: dict[str, str]) -> bool:
    return start_line.startswith("REGISTER") and "authorization" not in headers


class MockUdpProtocol(asyncio.DatagramProtocol):
    def connection_made(self, transport: asyncio.DatagramTransport) -> None:
        self.transport = transport

    def datagram_received(self, data: bytes, addr: tuple[str, int]) -> None:
        start_line, headers, body = parse_headers(data)
        if needs_auth(start_line, headers):
            packet = response(data, 401, "Unauthorized", [f'WWW-Authenticate: Digest realm="{REALM}", nonce="{NONCE}", algorithm=MD5'])
        else:
            packet = response(data, 200, "OK")
        self.transport.sendto(packet, addr)
        if "<CmdType>Keepalive</CmdType>" in body:
            catalog = build_catalog_query(headers)
            self.transport.sendto(catalog, addr)


async def handle_tcp(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        while True:
            data = await read_sip(reader)
            start_line, headers, body = parse_headers(data)
            if needs_auth(start_line, headers):
                packet = response(data, 401, "Unauthorized", [f'WWW-Authenticate: Digest realm="{REALM}", nonce="{NONCE}", algorithm=MD5'])
            else:
                packet = response(data, 200, "OK")
            writer.write(packet)
            await writer.drain()
            if "<CmdType>Keepalive</CmdType>" in body:
                writer.write(build_catalog_query(headers))
                await writer.drain()
    except (asyncio.IncompleteReadError, asyncio.LimitOverrunError, ConnectionError):
        pass
    finally:
        writer.close()
        try:
            await writer.wait_closed()
        except ConnectionError:
            pass


async def read_sip(reader: asyncio.StreamReader) -> bytes:
    header = await reader.readuntil(b"\r\n\r\n")
    match = re.search(br"Content-Length\s*:\s*(\d+)", header, flags=re.IGNORECASE)
    length = int(match.group(1)) if match else 0
    body = await reader.readexactly(length) if length else b""
    return header + body


def build_catalog_query(headers: dict[str, str]) -> bytes:
    body = (
        '<?xml version="1.0" encoding="GB2312"?>\r\n'
        "<Query>\r\n"
        "<CmdType>Catalog</CmdType>\r\n"
        "<SN>1</SN>\r\n"
        "<DeviceID>mock</DeviceID>\r\n"
        "</Query>\r\n"
    )
    body_bytes = body.encode("utf-8")
    lines = [
        "MESSAGE sip:mock SIP/2.0",
        f"Via: {headers.get('via', 'SIP/2.0/UDP 127.0.0.1:0')}",
        f"From: <sip:{REALM}@{REALM}>;tag=mock",
        f"To: {headers.get('from', f'<sip:mock@{REALM}>')}",
        "Call-ID: mock-catalog",
        "CSeq: 1 MESSAGE",
        "Content-Type: Application/MANSCDP+xml",
        f"Content-Length: {len(body_bytes)}",
        "",
        "",
    ]
    return "\r\n".join(lines).encode("utf-8") + body_bytes


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=15061)
    parser.add_argument("--transport", choices=["udp", "tcp"], default="udp")
    args = parser.parse_args()
    if args.transport == "udp":
        loop = asyncio.get_running_loop()
        transport, _ = await loop.create_datagram_endpoint(MockUdpProtocol, local_addr=(args.host, args.port))
        print(f"mock gb28181 udp server on {args.host}:{args.port}")
        try:
            await asyncio.Future()
        finally:
            transport.close()
    else:
        server = await asyncio.start_server(handle_tcp, args.host, args.port)
        print(f"mock gb28181 tcp server on {args.host}:{args.port}")
        async with server:
            await server.serve_forever()


if __name__ == "__main__":
    asyncio.run(main())
