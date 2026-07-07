from __future__ import annotations

import asyncio
from pathlib import Path
import random
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from mock_gb28181_sip_server import MockUdpProtocol, handle_tcp
from bukong_load_tester.config import AppConfig, Gb28181Config, GbMediaConfig, GbSipConfig
from bukong_load_tester.engine import run_load_test


async def run_udp_server(host: str, port: int):
    loop = asyncio.get_running_loop()
    return await loop.create_datagram_endpoint(MockUdpProtocol, local_addr=(host, port))


async def smoke(transport: str, port: int) -> None:
    server = None
    udp_transport = None
    if transport == "UDP":
        udp_transport, _ = await run_udp_server("127.0.0.1", port)
    else:
        server = await asyncio.start_server(handle_tcp, "127.0.0.1", port)
    try:
        local_port_base = random.randint(20000, 50000)
        config = AppConfig(
            mode="GB28181",
            gb28181=Gb28181Config(
                sip=GbSipConfig(
                    server_ip="127.0.0.1",
                    server_port=port,
                    domain_id="4403060755",
                    local_device_ip="127.0.0.1",
                    local_sip_start_port=local_port_base,
                    device_id_prefix="440306075513200",
                    device_count=3,
                    password="888888",
                    transport=transport,
                    heartbeat_interval=0.6,
                    register_expires=3600,
                    ramp_seconds=1,
                    duration_seconds=3,
                    sip_timeout=1.0,
                    channels_per_device=2,
                ),
                media=GbMediaConfig(enabled=False),
            ),
        )
        report = await run_load_test(config, event_callback=lambda event: print(event.get("message", event)) if event.get("type") == "log" else None)
        summary = report["summary"]
        print(transport, summary)
        assert summary.get("register_success_count", 0) == 3
        assert summary.get("register_failure_count", 0) == 0
        assert summary.get("heartbeat_sent_count", 0) > 0
        assert summary.get("catalog_response_count", 0) > 0
    finally:
        if udp_transport:
            udp_transport.close()
        if server:
            server.close()
            await server.wait_closed()


async def main() -> None:
    await smoke("UDP", 15061)
    await smoke("TCP", 15062)


if __name__ == "__main__":
    asyncio.run(main())
