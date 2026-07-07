from __future__ import annotations

from dataclasses import asdict, dataclass, field, fields, is_dataclass
import json
from pathlib import Path
from typing import Any, TypeVar
from urllib.parse import urlparse


T = TypeVar("T")


def _dataclass_from_dict(cls: type[T], data: dict[str, Any] | None) -> T:
    data = data or {}
    allowed = {item.name for item in fields(cls)}
    clean = {key: value for key, value in data.items() if key in allowed}
    return cls(**clean)


def _redact(value: Any, secret_keys: set[str]) -> Any:
    if is_dataclass(value):
        value = asdict(value)
    if isinstance(value, dict):
        result: dict[str, Any] = {}
        for key, item in value.items():
            if key in secret_keys and item:
                result[key] = "***redacted***"
            else:
                result[key] = _redact(item, secret_keys)
        return result
    if isinstance(value, list):
        return [_redact(item, secret_keys) for item in value]
    return value


@dataclass(slots=True)
class HttpConfig:
    server_url: str = "http://127.0.0.1:8080"
    device_count: int = 50
    ramp_seconds: int = 60
    duration_seconds: int = 300
    heartbeat_interval: float = 30.0
    status_interval: float = 10.0
    alarm_probability: float = 0.01
    payload_size: int = 256
    device_id_prefix: str = "test-device-"
    auth_token: str = ""
    max_concurrency: int = 100
    request_timeout: float = 10.0
    status_path: str = "/api/device/status"
    heartbeat_path: str = "/api/device/heartbeat"
    alarm_path: str = "/api/device/alarm"

    def base_url(self) -> str:
        value = self.server_url.strip()
        if "://" not in value:
            value = f"http://{value}"
        return value.rstrip("/")

    def validate(self) -> list[str]:
        errors: list[str] = []
        if not self.server_url.strip():
            errors.append("HTTP 服务器地址不能为空。")
        if self.device_count < 1:
            errors.append("HTTP 设备数量必须大于 0。")
        if self.device_count > 1 and self.ramp_seconds < 1:
            errors.append("HTTP 设备数量大于 1 时，爬坡时间必须至少 1 秒。")
        if self.duration_seconds < 1:
            errors.append("HTTP 测试时长必须大于 0。")
        if self.heartbeat_interval <= 0:
            errors.append("HTTP 心跳间隔必须大于 0。")
        if self.status_interval <= 0:
            errors.append("HTTP 状态上报间隔必须大于 0。")
        if not 0 <= self.alarm_probability <= 1:
            errors.append("HTTP 告警概率必须在 0 到 1 之间。")
        if self.payload_size < 0:
            errors.append("HTTP payload 大小不能为负数。")
        if not self.device_id_prefix:
            errors.append("HTTP 设备 ID 前缀不能为空。")
        if self.max_concurrency < 1:
            errors.append("HTTP 最大并发必须大于 0。")
        if self.request_timeout <= 0:
            errors.append("HTTP 请求超时时间必须大于 0。")
        return errors


@dataclass(slots=True)
class MqttConfig:
    server_url: str = "127.0.0.1:1883"
    device_count: int = 50
    ramp_seconds: int = 60
    duration_seconds: int = 300
    heartbeat_interval: float = 30.0
    status_interval: float = 10.0
    alarm_probability: float = 0.01
    payload_size: int = 256
    device_id_prefix: str = "test-device-"
    auth_token: str = ""
    max_concurrency: int = 100
    topic_prefix: str = "devices"
    port: int = 1883
    tls: bool = False
    username: str = ""
    password: str = ""

    def endpoint(self) -> tuple[str, int, bool]:
        value = self.server_url.strip()
        if "://" not in value:
            value = f"//{value}"
        parsed = urlparse(value)
        host = parsed.hostname or parsed.path.split(":")[0]
        port = parsed.port or self.port
        tls = self.tls or parsed.scheme.lower() == "mqtts"
        return host, port, tls

    def validate(self) -> list[str]:
        errors: list[str] = []
        host, port, _ = self.endpoint()
        if not host:
            errors.append("MQTT 服务器地址必须包含主机名或 IP。")
        if not 1 <= port <= 65535:
            errors.append("MQTT 端口必须在 1 到 65535 之间。")
        if self.device_count < 1:
            errors.append("MQTT 设备数量必须大于 0。")
        if self.device_count > 1 and self.ramp_seconds < 1:
            errors.append("MQTT 设备数量大于 1 时，爬坡时间必须至少 1 秒。")
        if self.duration_seconds < 1:
            errors.append("MQTT 测试时长必须大于 0。")
        if self.heartbeat_interval <= 0:
            errors.append("MQTT 心跳间隔必须大于 0。")
        if self.status_interval <= 0:
            errors.append("MQTT 状态上报间隔必须大于 0。")
        if not 0 <= self.alarm_probability <= 1:
            errors.append("MQTT 告警概率必须在 0 到 1 之间。")
        if self.payload_size < 0:
            errors.append("MQTT payload 大小不能为负数。")
        if not self.device_id_prefix:
            errors.append("MQTT 设备 ID 前缀不能为空。")
        if self.max_concurrency < 1:
            errors.append("MQTT 最大并发必须大于 0。")
        return errors


@dataclass(slots=True)
class GbSipConfig:
    server_ip: str = ""
    server_port: int = 5060
    domain_id: str = ""
    local_device_ip: str = "127.0.0.1"
    local_sip_start_port: int = 15060
    device_id_prefix: str = "340200000013200"
    device_count: int = 50
    device_index_offset: int = 0
    password: str = ""
    transport: str = "UDP"
    heartbeat_interval: float = 30.0
    register_expires: int = 3600
    ramp_seconds: int = 60
    duration_seconds: int = 300
    sip_timeout: float = 5.0
    offline_simulation_enabled: bool = False
    offline_probability: float = 0.0
    offline_duration_seconds: float = 10.0
    channels_per_device: int = 1

    def validate(self) -> list[str]:
        errors: list[str] = []
        if not self.server_ip.strip():
            errors.append("GB28181 SIP 服务器 IP 不能为空。")
        if not 1 <= self.server_port <= 65535:
            errors.append("GB28181 SIP 服务器端口必须在 1 到 65535 之间。")
        if not self.domain_id.strip():
            errors.append("GB28181 SIP 域 ID 不能为空。")
        if not self.local_device_ip.strip():
            errors.append("GB28181 本地设备 IP 不能为空。")
        if not 1 <= self.local_sip_start_port <= 65535:
            errors.append("GB28181 本地 SIP 起始端口必须在 1 到 65535 之间。")
        if self.transport.upper() not in {"UDP", "TCP"}:
            errors.append("GB28181 SIP 传输协议必须是 UDP 或 TCP。")
        if self.device_count < 1:
            errors.append("GB28181 设备数量必须大于 0。")
        if self.device_index_offset < 0:
            errors.append("GB28181 device_index_offset must not be negative.")
        if self.device_count > 1 and self.ramp_seconds < 1:
            errors.append("GB28181 设备数量大于 1 时，爬坡时间必须至少 1 秒。")
        if self.duration_seconds < 1:
            errors.append("GB28181 测试时长必须大于 0。")
        if self.heartbeat_interval <= 0:
            errors.append("GB28181 心跳间隔必须大于 0。")
        if self.register_expires < 60:
            errors.append("GB28181 注册有效期建议不小于 60 秒。")
        if self.sip_timeout <= 0:
            errors.append("GB28181 SIP 超时时间必须大于 0。")
        if not 0 <= self.offline_probability <= 1:
            errors.append("GB28181 离线概率必须在 0 到 1 之间。")
        if self.offline_duration_seconds <= 0:
            errors.append("GB28181 离线时长必须大于 0。")
        if not self.device_id_prefix.isdigit():
            errors.append("GB28181 设备 ID 前缀必须为数字。")
        if len(self.device_id_prefix) >= 20:
            errors.append("GB28181 设备 ID 前缀必须短于 20 位，以便追加序号。")
        else:
            suffix_width = 20 - len(self.device_id_prefix)
            if self.device_index_offset + self.device_count > 10**suffix_width - 1:
                errors.append("GB28181 设备数量超过当前设备 ID 前缀可生成的 20 位国标编码范围。")
        if self.local_sip_start_port + self.device_count - 1 > 65535:
            errors.append("GB28181 本地 SIP 起始端口加设备数量超过 65535。")
        if not 1 <= self.channels_per_device <= 4:
            errors.append("第一版每台设备通道数硬限制为 1 到 4 路。")
        return errors

    def device_id(self, index: int) -> str:
        suffix_width = 20 - len(self.device_id_prefix)
        return f"{self.device_id_prefix}{self.device_index_offset + index + 1:0{suffix_width}d}"


@dataclass(slots=True)
class GbMediaConfig:
    enabled: bool = False
    rtp_transport: str = "UDP"
    local_port_start: int = 30000
    local_port_end: int = 30020
    video_file_path: str = ""
    concurrent_streams: int = 1
    bitrate_kbps: int = 512
    fps: int = 25
    video_codec: str = "H264"
    payload_format: str = "PS_OVER_RTP"
    loop: bool = True
    trigger_mode: str = "invite_then_stream"
    max_first_version_streams: int = 10

    def validate(self) -> list[str]:
        errors: list[str] = []
        if self.rtp_transport.upper() not in {"UDP", "TCP"}:
            errors.append("GB28181 RTP 传输协议必须是 UDP 或 TCP。")
        if not 1 <= self.local_port_start <= 65535 or not 1 <= self.local_port_end <= 65535:
            errors.append("GB28181 RTP 本地端口范围必须在 1 到 65535 之间。")
        if self.local_port_start > self.local_port_end:
            errors.append("GB28181 RTP 本地端口范围起点不能大于终点。")
        if self.concurrent_streams < 0:
            errors.append("GB28181 并发视频路数不能为负数。")
        if self.concurrent_streams > self.max_first_version_streams:
            errors.append(f"第一版媒体压测硬限制为最多 {self.max_first_version_streams} 路。")
        if self.enabled and self.concurrent_streams < 1:
            errors.append("启用媒体压测时，并发视频路数必须大于 0。")
        if self.bitrate_kbps <= 0:
            errors.append("GB28181 码率必须大于 0。")
        if self.fps <= 0:
            errors.append("GB28181 帧率必须大于 0。")
        if self.video_codec.upper() not in {"H264", "H265"}:
            errors.append("GB28181 视频编码必须是 H264 或 H265。")
        if self.payload_format.upper() not in {"PS_OVER_RTP", "ES_OVER_RTP"}:
            errors.append("GB28181 RTP 负载封装必须是 PS_OVER_RTP 或 ES_OVER_RTP。")
        if self.trigger_mode not in {"invite_then_stream", "active_test_stream"}:
            errors.append("GB28181 点播触发方式无效。")
        needed_ports = max(1, self.concurrent_streams)
        if self.enabled and self.local_port_end - self.local_port_start + 1 < needed_ports:
            errors.append("GB28181 RTP 本地端口范围不足以覆盖并发视频路数。")
        return errors


@dataclass(slots=True)
class Gb28181Config:
    sip: GbSipConfig = field(default_factory=GbSipConfig)
    media: GbMediaConfig = field(default_factory=GbMediaConfig)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "Gb28181Config":
        data = data or {}
        return cls(
            sip=_dataclass_from_dict(GbSipConfig, data.get("sip")),
            media=_dataclass_from_dict(GbMediaConfig, data.get("media")),
        )

    def validate(self) -> list[str]:
        return self.sip.validate() + self.media.validate()


@dataclass(slots=True)
class AppConfig:
    mode: str = "HTTP"
    http: HttpConfig = field(default_factory=HttpConfig)
    mqtt: MqttConfig = field(default_factory=MqttConfig)
    gb28181: Gb28181Config = field(default_factory=Gb28181Config)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AppConfig":
        if "mode" not in data and "protocol" in data:
            return cls._from_legacy_flat(data)
        mode = str(data.get("mode", "HTTP")).upper()
        return cls(
            mode=mode,
            http=_dataclass_from_dict(HttpConfig, data.get("http")),
            mqtt=_dataclass_from_dict(MqttConfig, data.get("mqtt")),
            gb28181=Gb28181Config.from_dict(data.get("gb28181")),
        )

    @classmethod
    def _from_legacy_flat(cls, data: dict[str, Any]) -> "AppConfig":
        mode = str(data.get("protocol", "HTTP")).upper()
        http_defaults = HttpConfig()
        mqtt_defaults = MqttConfig()
        http = HttpConfig(
            server_url=data.get("server_url", http_defaults.server_url),
            device_count=data.get("device_count", http_defaults.device_count),
            ramp_seconds=data.get("ramp_seconds", http_defaults.ramp_seconds),
            duration_seconds=data.get("duration_seconds", http_defaults.duration_seconds),
            heartbeat_interval=data.get("heartbeat_interval", http_defaults.heartbeat_interval),
            status_interval=data.get("status_interval", http_defaults.status_interval),
            alarm_probability=data.get("alarm_probability", http_defaults.alarm_probability),
            payload_size=data.get("payload_size", http_defaults.payload_size),
            device_id_prefix=data.get("device_id_prefix", http_defaults.device_id_prefix),
            auth_token=data.get("auth_token", ""),
            max_concurrency=data.get("max_concurrency", http_defaults.max_concurrency),
            request_timeout=data.get("request_timeout", http_defaults.request_timeout),
            status_path=data.get("http_status_path", http_defaults.status_path),
            heartbeat_path=data.get("http_heartbeat_path", http_defaults.heartbeat_path),
            alarm_path=data.get("http_alarm_path", http_defaults.alarm_path),
        )
        mqtt = MqttConfig(
            server_url=data.get("server_url", mqtt_defaults.server_url),
            device_count=data.get("device_count", mqtt_defaults.device_count),
            ramp_seconds=data.get("ramp_seconds", mqtt_defaults.ramp_seconds),
            duration_seconds=data.get("duration_seconds", mqtt_defaults.duration_seconds),
            heartbeat_interval=data.get("heartbeat_interval", mqtt_defaults.heartbeat_interval),
            status_interval=data.get("status_interval", mqtt_defaults.status_interval),
            alarm_probability=data.get("alarm_probability", mqtt_defaults.alarm_probability),
            payload_size=data.get("payload_size", mqtt_defaults.payload_size),
            device_id_prefix=data.get("device_id_prefix", mqtt_defaults.device_id_prefix),
            auth_token=data.get("auth_token", ""),
            max_concurrency=data.get("max_concurrency", mqtt_defaults.max_concurrency),
            topic_prefix=data.get("mqtt_topic_prefix", mqtt_defaults.topic_prefix),
            port=data.get("mqtt_port", mqtt_defaults.port),
            tls=data.get("mqtt_tls", mqtt_defaults.tls),
            username=data.get("mqtt_username", ""),
            password=data.get("mqtt_password", ""),
        )
        return cls(mode=mode, http=http, mqtt=mqtt)

    @classmethod
    def load(cls, path: str | Path) -> "AppConfig":
        with Path(path).open("r", encoding="utf-8") as handle:
            return cls.from_dict(json.load(handle))

    def save(self, path: str | Path) -> None:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("w", encoding="utf-8") as handle:
            json.dump(self.to_dict(), handle, indent=2, ensure_ascii=False)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    def to_report_dict(self) -> dict[str, Any]:
        return _redact(self.to_dict(), {"auth_token", "password"})

    def validate(self) -> list[str]:
        mode = self.mode.upper()
        if mode == "HTTP":
            return self.http.validate()
        if mode == "MQTT":
            return self.mqtt.validate()
        if mode == "GB28181":
            return self.gb28181.validate()
        return ["压测模式必须是 HTTP、MQTT 或 GB28181。"]

    def ensure_valid(self) -> None:
        errors = self.validate()
        if errors:
            raise ValueError("\n".join(errors))

    def duration_seconds(self) -> float:
        mode = self.mode.upper()
        if mode == "HTTP":
            return self.http.duration_seconds
        if mode == "MQTT":
            return self.mqtt.duration_seconds
        return self.gb28181.sip.duration_seconds


LoadConfig = AppConfig
