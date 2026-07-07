from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import random
import time

from .sip_parser import SipMessage, xml_value


MANSCDP_XML = "Application/MANSCDP+xml"


@dataclass(slots=True)
class SipIdentity:
    device_id: str
    domain_id: str
    server_ip: str
    server_port: int
    local_ip: str
    local_port: int
    transport: str
    call_id: str
    from_tag: str


def make_identity(
    device_id: str,
    domain_id: str,
    server_ip: str,
    server_port: int,
    local_ip: str,
    local_port: int,
    transport: str,
) -> SipIdentity:
    nonce = f"{time.time_ns()}{random.randint(1000, 9999)}"
    return SipIdentity(
        device_id=device_id,
        domain_id=domain_id,
        server_ip=server_ip,
        server_port=server_port,
        local_ip=local_ip,
        local_port=local_port,
        transport=transport.upper(),
        call_id=f"{device_id}-{nonce}",
        from_tag=f"{random.randint(100000, 999999)}",
    )


def build_register(identity: SipIdentity, cseq: int, expires: int, authorization: str = "") -> bytes:
    headers = _base_headers(identity, "REGISTER", cseq)
    headers.extend(
        [
            f"Contact: <sip:{identity.device_id}@{identity.local_ip}:{identity.local_port};transport={identity.transport.lower()}>",
            f"Expires: {expires}",
            "User-Agent: bukong-load-tester",
        ]
    )
    if authorization:
        headers.append(f"Authorization: {authorization}")
    return _message(f"REGISTER sip:{identity.domain_id} SIP/2.0", headers, "")


def build_keepalive(identity: SipIdentity, cseq: int, sn: int) -> bytes:
    body = (
        '<?xml version="1.0" encoding="GB2312"?>\r\n'
        "<Notify>\r\n"
        "<CmdType>Keepalive</CmdType>\r\n"
        f"<SN>{sn}</SN>\r\n"
        f"<DeviceID>{identity.device_id}</DeviceID>\r\n"
        "<Status>OK</Status>\r\n"
        "</Notify>\r\n"
    )
    headers = _base_headers(identity, "MESSAGE", cseq)
    headers.append(f"Content-Type: {MANSCDP_XML}")
    return _message(f"MESSAGE sip:{identity.domain_id}@{identity.server_ip}:{identity.server_port} SIP/2.0", headers, body)


def build_catalog_response(identity: SipIdentity, request: SipMessage, cseq: int, channels_per_device: int) -> bytes:
    sn = xml_value(request.body, "SN") or str(cseq)
    now = datetime.now().strftime("%Y-%m-%dT%H:%M:%S")
    items = []
    for index in range(channels_per_device):
        channel_id = f"{identity.device_id[:-1]}{index + 1}"
        items.append(
            "<Item>\r\n"
            f"<DeviceID>{channel_id}</DeviceID>\r\n"
            f"<Name>Channel-{index + 1}</Name>\r\n"
            "<Manufacturer>BukongLoadTester</Manufacturer>\r\n"
            "<Model>SimulatedCamera</Model>\r\n"
            "<Owner>Test</Owner>\r\n"
            "<CivilCode>000000</CivilCode>\r\n"
            "<Address>LoadTest</Address>\r\n"
            "<Parental>0</Parental>\r\n"
            "<ParentID></ParentID>\r\n"
            "<SafetyWay>0</SafetyWay>\r\n"
            "<RegisterWay>1</RegisterWay>\r\n"
            "<Secrecy>0</Secrecy>\r\n"
            "<Status>ON</Status>\r\n"
            "</Item>\r\n"
        )
    body = (
        '<?xml version="1.0" encoding="GB2312"?>\r\n'
        "<Response>\r\n"
        "<CmdType>Catalog</CmdType>\r\n"
        f"<SN>{sn}</SN>\r\n"
        f"<DeviceID>{identity.device_id}</DeviceID>\r\n"
        f"<SumNum>{channels_per_device}</SumNum>\r\n"
        "<DeviceList Num=\"" + str(channels_per_device) + "\">\r\n"
        + "".join(items)
        + "</DeviceList>\r\n"
        f"<UpdateTime>{now}</UpdateTime>\r\n"
        "</Response>\r\n"
    )
    headers = _base_headers(identity, "MESSAGE", cseq)
    headers.append(f"Content-Type: {MANSCDP_XML}")
    return _message(f"MESSAGE sip:{identity.domain_id}@{identity.server_ip}:{identity.server_port} SIP/2.0", headers, body)


def build_sip_response(request: SipMessage, code: int = 200, reason: str = "OK", body: str = "", content_type: str = "") -> bytes:
    headers = []
    for name in ("via", "from", "to", "call-id", "cseq"):
        value = request.header(name)
        if value:
            headers.append(f"{_canonical_header(name)}: {value}")
    if content_type:
        headers.append(f"Content-Type: {content_type}")
    return _message(f"SIP/2.0 {code} {reason}", headers, body)


def build_invite_ok(
    identity: SipIdentity,
    request: SipMessage,
    media_port: int,
    payload_type: str = "96",
    codec_name: str = "PS",
) -> bytes:
    body = (
        "v=0\r\n"
        f"o={identity.device_id} 0 0 IN IP4 {identity.local_ip}\r\n"
        f"s=Play\r\n"
        f"c=IN IP4 {identity.local_ip}\r\n"
        "t=0 0\r\n"
        f"m=video {media_port} RTP/AVP {payload_type}\r\n"
        f"a=rtpmap:{payload_type} {codec_name}/90000\r\n"
        f"a=recvonly\r\n"
        f"y={identity.device_id[-10:]}\r\n"
    )
    return build_sip_response(request, 200, "OK", body, "application/sdp")


def _base_headers(identity: SipIdentity, method: str, cseq: int) -> list[str]:
    branch = f"z9hG4bK{time.time_ns()}{random.randint(1000, 9999)}"
    return [
        f"Via: SIP/2.0/{identity.transport} {identity.local_ip}:{identity.local_port};branch={branch}",
        f"From: <sip:{identity.device_id}@{identity.domain_id}>;tag={identity.from_tag}",
        f"To: <sip:{identity.device_id}@{identity.domain_id}>",
        f"Call-ID: {identity.call_id}",
        f"CSeq: {cseq} {method}",
        "Max-Forwards: 70",
    ]


def _message(start_line: str, headers: list[str], body: str) -> bytes:
    body_bytes = body.encode("utf-8")
    lines = [start_line, *headers, f"Content-Length: {len(body_bytes)}", "", ""]
    return "\r\n".join(lines).encode("utf-8") + body_bytes


def _canonical_header(name: str) -> str:
    mapping = {
        "call-id": "Call-ID",
        "cseq": "CSeq",
        "via": "Via",
        "from": "From",
        "to": "To",
    }
    return mapping.get(name.lower(), name)
