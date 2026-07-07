from __future__ import annotations

from dataclasses import dataclass
import asyncio
import re


@dataclass(slots=True)
class SipMessage:
    raw: bytes
    start_line: str
    headers: dict[str, str]
    body: str

    @property
    def is_response(self) -> bool:
        return self.start_line.upper().startswith("SIP/2.0")

    @property
    def method(self) -> str:
        if self.is_response:
            cseq = self.header("cseq")
            parts = cseq.split()
            return parts[1].upper() if len(parts) > 1 else ""
        return self.start_line.split()[0].upper() if self.start_line else ""

    @property
    def status_code(self) -> int | None:
        if not self.is_response:
            return None
        parts = self.start_line.split()
        if len(parts) < 2:
            return None
        try:
            return int(parts[1])
        except ValueError:
            return None

    def header(self, name: str, default: str = "") -> str:
        return self.headers.get(name.lower(), default)


def parse_sip_message(data: bytes) -> SipMessage:
    header_bytes, _, body_bytes = data.partition(b"\r\n\r\n")
    header_text = header_bytes.decode("utf-8", errors="replace")
    lines = header_text.split("\r\n")
    start_line = lines[0] if lines else ""
    headers: dict[str, str] = {}
    for line in lines[1:]:
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        headers[key.strip().lower()] = value.strip()
    content_length = int(headers.get("content-length", "0") or "0")
    body = body_bytes[:content_length].decode("utf-8", errors="replace")
    return SipMessage(raw=data, start_line=start_line, headers=headers, body=body)


async def read_sip_message(reader: asyncio.StreamReader, timeout: float) -> bytes:
    header = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout=timeout)
    match = re.search(br"Content-Length\s*:\s*(\d+)", header, flags=re.IGNORECASE)
    content_length = int(match.group(1)) if match else 0
    body = b""
    if content_length:
        body = await asyncio.wait_for(reader.readexactly(content_length), timeout=timeout)
    return header + body


def xml_value(body: str, tag: str) -> str:
    match = re.search(rf"<{tag}>\s*([^<]+)\s*</{tag}>", body, flags=re.IGNORECASE)
    return match.group(1).strip() if match else ""


def parse_sdp_target(body: str) -> tuple[str, int] | None:
    ip = ""
    port = 0
    for line in body.replace("\r\n", "\n").split("\n"):
        line = line.strip()
        if line.startswith("c=IN IP4 "):
            ip = line.split()[-1]
        elif line.startswith("m=video "):
            parts = line.split()
            if len(parts) >= 2:
                try:
                    port = int(parts[1])
                except ValueError:
                    port = 0
    if ip and port:
        return ip, port
    return None
