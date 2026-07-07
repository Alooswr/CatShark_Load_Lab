from __future__ import annotations

from pathlib import Path
import sys
from typing import Any

from PySide6.QtCore import QThread, Qt, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QPlainTextEdit,
    QDoubleSpinBox,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .config import AppConfig, Gb28181Config, GbMediaConfig, GbSipConfig, HttpConfig, MqttConfig
from .control import RunControl
from .engine import run_load_test
from .report import write_csv_report, write_json_report


class LoadTestThread(QThread):
    event_emitted = Signal(dict)
    report_ready = Signal(dict)
    failed = Signal(str)

    def __init__(self, config: AppConfig) -> None:
        super().__init__()
        self.config = config
        self.control = RunControl()

    def run(self) -> None:
        try:
            import asyncio

            report = asyncio.run(
                run_load_test(
                    self.config,
                    event_callback=self.event_emitted.emit,
                    control=self.control,
                )
            )
            self.report_ready.emit(report)
        except Exception as exc:
            self.failed.emit(str(exc))

    def pause_test(self) -> None:
        self.control.pause()
        self.event_emitted.emit({"type": "log", "message": "已暂停"})

    def resume_test(self) -> None:
        self.control.resume()
        self.event_emitted.emit({"type": "log", "message": "已继续"})

    def stop_test(self) -> None:
        self.control.request_stop("stopped")
        self.event_emitted.emit({"type": "log", "message": "正在停止..."})

    def is_paused(self) -> bool:
        return self.control.is_paused()


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowIcon(_load_app_icon())
        self.setWindowTitle("布控球服务器压测上位机")
        self.resize(1320, 860)
        self.worker: LoadTestThread | None = None
        self.last_report: dict[str, Any] | None = None
        self.text_widgets: dict[str, QPlainTextEdit] = {}
        self.stat_labels: dict[str, QLabel] = {}
        self._build_ui()
        self._apply_config(AppConfig())
        self._set_running(False)

    def _build_ui(self) -> None:
        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)

        top_row = QHBoxLayout()
        layout.addLayout(top_row)
        top_row.addWidget(QLabel("压测模式"))
        self.mode = QComboBox()
        self.mode.addItems(["HTTP", "MQTT", "GB28181"])
        self.mode.currentTextChanged.connect(self._sync_mode_tab)
        top_row.addWidget(self.mode)
        top_row.addSpacing(16)

        self.load_config_button = QPushButton("加载配置")
        self.save_config_button = QPushButton("保存 config.json")
        self.start_button = QPushButton("开始")
        self.pause_button = QPushButton("暂停")
        self.stop_button = QPushButton("停止")
        self.export_button = QPushButton("导出报告")
        for button in [
            self.load_config_button,
            self.save_config_button,
            self.start_button,
            self.pause_button,
            self.stop_button,
            self.export_button,
        ]:
            top_row.addWidget(button)
        top_row.addStretch(1)

        self.load_config_button.clicked.connect(self.load_config)
        self.save_config_button.clicked.connect(self.save_config)
        self.start_button.clicked.connect(self.start_test)
        self.pause_button.clicked.connect(self.toggle_pause)
        self.stop_button.clicked.connect(self.stop_test)
        self.export_button.clicked.connect(self.export_report)

        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)
        self.tabs.addTab(self._build_http_tab(), "HTTP")
        self.tabs.addTab(self._build_mqtt_tab(), "MQTT")
        self.tabs.addTab(self._build_gb_sip_tab(), "GB28181 SIP")
        self.tabs.addTab(self._build_gb_media_tab(), "GB28181 媒体")

        stats_group = QGroupBox("实时指标")
        stats_grid = QGridLayout(stats_group)
        layout.addWidget(stats_group)
        stats = [
            ("active_devices", "当前任务设备数"),
            ("total_requests", "总消息/请求数"),
            ("success_count", "成功数"),
            ("failure_count", "失败数"),
            ("throughput", "RPS/MPS"),
            ("avg_latency_ms", "平均延迟(ms)"),
            ("p50_latency_ms", "P50(ms)"),
            ("p95_latency_ms", "P95(ms)"),
            ("p99_latency_ms", "P99(ms)"),
            ("active_elapsed_seconds", "有效运行时长(s)"),
            ("register_success_count", "注册成功数"),
            ("register_failure_count", "注册失败数"),
            ("online_devices", "在线设备数"),
            ("peak_online_devices", "峰值在线设备数"),
            ("heartbeat_sent_count", "心跳发送数"),
            ("timeout_count", "超时数"),
            ("catalog_query_count", "Catalog 查询数"),
            ("catalog_response_count", "Catalog 响应数"),
            ("reconnect_count", "重连数"),
            ("media_stream_started_count", "媒体启动路数"),
            ("media_active_streams", "当前媒体路数"),
        ]
        for index, (key, label) in enumerate(stats):
            value = QLabel("0")
            value.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.stat_labels[key] = value
            stats_grid.addWidget(QLabel(label), index // 5, (index % 5) * 2)
            stats_grid.addWidget(value, index // 5, (index % 5) * 2 + 1)

        split = QHBoxLayout()
        layout.addLayout(split, stretch=1)
        split.addWidget(self._read_only_text("状态码分布"), stretch=1)
        split.addWidget(self._read_only_text("异常分布"), stretch=1)
        split.addWidget(self._read_only_text("运行日志"), stretch=2)

    def _build_http_tab(self) -> QWidget:
        widget = QWidget()
        grid = QGridLayout(widget)
        self.http_server_url = QLineEdit()
        self.http_device_count = self._spin(1, 1_000_000)
        self.http_ramp_seconds = self._spin(1, 86_400)
        self.http_duration_seconds = self._spin(1, 86_400)
        self.http_heartbeat_interval = self._double_spin(0.1, 86_400, 1)
        self.http_status_interval = self._double_spin(0.1, 86_400, 1)
        self.http_alarm_probability = self._double_spin(0.0, 1.0, 3)
        self.http_alarm_probability.setSingleStep(0.01)
        self.http_payload_size = self._spin(0, 10_000_000)
        self.http_device_id_prefix = QLineEdit()
        self.http_auth_token = QLineEdit()
        self.http_auth_token.setEchoMode(QLineEdit.Password)
        self.http_max_concurrency = self._spin(1, 100_000)
        self.http_request_timeout = self._double_spin(0.1, 600, 1)
        self.http_status_path = QLineEdit()
        self.http_heartbeat_path = QLineEdit()
        self.http_alarm_path = QLineEdit()
        self._add_rows(
            grid,
            [
                ("服务器地址", self.http_server_url),
                ("设备数量", self.http_device_count),
                ("爬坡时间(s)", self.http_ramp_seconds),
                ("测试时长(s)", self.http_duration_seconds),
                ("心跳间隔(s)", self.http_heartbeat_interval),
                ("状态上报间隔(s)", self.http_status_interval),
                ("告警概率", self.http_alarm_probability),
                ("payload 大小(bytes)", self.http_payload_size),
                ("设备 ID 前缀", self.http_device_id_prefix),
                ("鉴权 token", self.http_auth_token),
                ("最大并发", self.http_max_concurrency),
                ("请求超时(s)", self.http_request_timeout),
                ("HTTP status path", self.http_status_path),
                ("HTTP heartbeat path", self.http_heartbeat_path),
                ("HTTP alarm path", self.http_alarm_path),
            ],
        )
        return widget

    def _build_mqtt_tab(self) -> QWidget:
        widget = QWidget()
        grid = QGridLayout(widget)
        self.mqtt_server_url = QLineEdit()
        self.mqtt_device_count = self._spin(1, 1_000_000)
        self.mqtt_ramp_seconds = self._spin(1, 86_400)
        self.mqtt_duration_seconds = self._spin(1, 86_400)
        self.mqtt_heartbeat_interval = self._double_spin(0.1, 86_400, 1)
        self.mqtt_status_interval = self._double_spin(0.1, 86_400, 1)
        self.mqtt_alarm_probability = self._double_spin(0.0, 1.0, 3)
        self.mqtt_alarm_probability.setSingleStep(0.01)
        self.mqtt_payload_size = self._spin(0, 10_000_000)
        self.mqtt_device_id_prefix = QLineEdit()
        self.mqtt_auth_token = QLineEdit()
        self.mqtt_auth_token.setEchoMode(QLineEdit.Password)
        self.mqtt_max_concurrency = self._spin(1, 100_000)
        self.mqtt_topic_prefix = QLineEdit()
        self.mqtt_port = self._spin(1, 65_535)
        self.mqtt_tls = QCheckBox("启用 TLS")
        self.mqtt_username = QLineEdit()
        self.mqtt_password = QLineEdit()
        self.mqtt_password.setEchoMode(QLineEdit.Password)
        self._add_rows(
            grid,
            [
                ("服务器地址", self.mqtt_server_url),
                ("设备数量", self.mqtt_device_count),
                ("爬坡时间(s)", self.mqtt_ramp_seconds),
                ("测试时长(s)", self.mqtt_duration_seconds),
                ("心跳间隔(s)", self.mqtt_heartbeat_interval),
                ("状态上报间隔(s)", self.mqtt_status_interval),
                ("告警概率", self.mqtt_alarm_probability),
                ("payload 大小(bytes)", self.mqtt_payload_size),
                ("设备 ID 前缀", self.mqtt_device_id_prefix),
                ("鉴权 token", self.mqtt_auth_token),
                ("最大并发", self.mqtt_max_concurrency),
                ("MQTT topic prefix", self.mqtt_topic_prefix),
                ("MQTT 端口", self.mqtt_port),
                ("MQTT TLS", self.mqtt_tls),
                ("MQTT 用户名", self.mqtt_username),
                ("MQTT 密码", self.mqtt_password),
            ],
        )
        return widget

    def _build_gb_sip_tab(self) -> QWidget:
        widget = QWidget()
        grid = QGridLayout(widget)
        self.gb_sip_server_ip = QLineEdit()
        self.gb_sip_server_ip.setPlaceholderText("不默认写入现场或生产地址")
        self.gb_sip_server_port = self._spin(1, 65_535)
        self.gb_sip_domain_id = QLineEdit()
        self.gb_local_device_ip = QLineEdit()
        self.gb_local_sip_start_port = self._spin(1, 65_535)
        self.gb_device_id_prefix = QLineEdit()
        self.gb_device_count = self._spin(1, 1_000_000)
        self.gb_password = QLineEdit()
        self.gb_password.setEchoMode(QLineEdit.Password)
        self.gb_sip_transport = QComboBox()
        self.gb_sip_transport.addItems(["UDP", "TCP"])
        self.gb_heartbeat_interval = self._double_spin(0.1, 86_400, 1)
        self.gb_register_expires = self._spin(60, 86_400)
        self.gb_ramp_seconds = self._spin(1, 86_400)
        self.gb_duration_seconds = self._spin(1, 86_400)
        self.gb_sip_timeout = self._double_spin(0.1, 120, 1)
        self.gb_channels_per_device = self._spin(1, 4)
        self.gb_offline_enabled = QCheckBox("启用离线/重连模拟")
        self.gb_offline_probability = self._double_spin(0.0, 1.0, 3)
        self.gb_offline_probability.setSingleStep(0.01)
        self.gb_offline_duration = self._double_spin(0.1, 3600, 1)
        self._add_rows(
            grid,
            [
                ("SIP 服务器 IP", self.gb_sip_server_ip),
                ("SIP 服务器端口", self.gb_sip_server_port),
                ("SIP 域 ID", self.gb_sip_domain_id),
                ("本地设备 IP", self.gb_local_device_ip),
                ("本地 SIP 起始端口", self.gb_local_sip_start_port),
                ("设备 ID 前缀", self.gb_device_id_prefix),
                ("设备数量", self.gb_device_count),
                ("注册密码", self.gb_password),
                ("SIP 传输协议", self.gb_sip_transport),
                ("心跳间隔(s)", self.gb_heartbeat_interval),
                ("注册有效期(s)", self.gb_register_expires),
                ("爬坡时间(s)", self.gb_ramp_seconds),
                ("测试时长(s)", self.gb_duration_seconds),
                ("SIP 超时(s)", self.gb_sip_timeout),
                ("每台设备通道数(1-4)", self.gb_channels_per_device),
                ("离线/重连", self.gb_offline_enabled),
                ("离线概率", self.gb_offline_probability),
                ("离线时长(s)", self.gb_offline_duration),
            ],
        )
        return widget

    def _build_gb_media_tab(self) -> QWidget:
        widget = QWidget()
        grid = QGridLayout(widget)
        self.gb_media_enabled = QCheckBox("启用媒体压测")
        self.gb_rtp_transport = QComboBox()
        self.gb_rtp_transport.addItems(["UDP", "TCP"])
        self.gb_rtp_local_port_start = self._spin(1, 65_535)
        self.gb_rtp_local_port_end = self._spin(1, 65_535)
        self.gb_video_file_path = QLineEdit()
        browse = QPushButton("选择")
        browse.clicked.connect(self._browse_video_file)
        video_row = QWidget()
        video_layout = QHBoxLayout(video_row)
        video_layout.setContentsMargins(0, 0, 0, 0)
        video_layout.addWidget(self.gb_video_file_path)
        video_layout.addWidget(browse)
        self.gb_concurrent_streams = self._spin(0, 10)
        self.gb_bitrate_kbps = self._spin(1, 200_000)
        self.gb_fps = self._spin(1, 240)
        self.gb_video_codec = QComboBox()
        self.gb_video_codec.addItems(["H264", "H265"])
        self.gb_payload_format = QComboBox()
        self.gb_payload_format.addItem("PS over RTP", "PS_OVER_RTP")
        self.gb_payload_format.addItem("ES over RTP", "ES_OVER_RTP")
        self.gb_loop = QCheckBox("循环推流")
        self.gb_trigger_mode = QComboBox()
        self.gb_trigger_mode.addItem("模拟 INVITE 后推流", "invite_then_stream")
        self.gb_trigger_mode.addItem("主动测试推流", "active_test_stream")
        direction = QLabel("媒体方向固定为设备主动连平台；第一版媒体并发硬限制 10 路。")
        direction.setWordWrap(True)
        self._add_rows(
            grid,
            [
                ("是否启用媒体压测", self.gb_media_enabled),
                ("RTP 传输协议", self.gb_rtp_transport),
                ("RTP 本地端口起点", self.gb_rtp_local_port_start),
                ("RTP 本地端口终点", self.gb_rtp_local_port_end),
                ("视频文件路径", video_row),
                ("并发视频路数", self.gb_concurrent_streams),
                ("码率(kbps)", self.gb_bitrate_kbps),
                ("帧率", self.gb_fps),
                ("视频编码", self.gb_video_codec),
                ("RTP 负载封装", self.gb_payload_format),
                ("是否循环推流", self.gb_loop),
                ("点播触发方式", self.gb_trigger_mode),
                ("说明", direction),
            ],
        )
        return widget

    def _add_rows(self, grid: QGridLayout, rows: list[tuple[str, QWidget]]) -> None:
        for row, (label, widget) in enumerate(rows):
            column = 0 if row < 10 else 2
            grid_row = row if row < 10 else row - 10
            grid.addWidget(QLabel(label), grid_row, column)
            grid.addWidget(widget, grid_row, column + 1)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(3, 1)

    def _spin(self, minimum: int, maximum: int) -> QSpinBox:
        spin = QSpinBox()
        spin.setRange(minimum, maximum)
        return spin

    def _double_spin(self, minimum: float, maximum: float, decimals: int) -> QDoubleSpinBox:
        spin = QDoubleSpinBox()
        spin.setRange(minimum, maximum)
        spin.setDecimals(decimals)
        return spin

    def _read_only_text(self, title: str) -> QGroupBox:
        group = QGroupBox(title)
        layout = QVBoxLayout(group)
        text = QPlainTextEdit()
        text.setReadOnly(True)
        layout.addWidget(text)
        self.text_widgets[title] = text
        return group

    def _apply_config(self, config: AppConfig) -> None:
        self.mode.setCurrentText(config.mode.upper())
        self._apply_http(config.http)
        self._apply_mqtt(config.mqtt)
        self._apply_gb28181(config.gb28181)
        self._sync_mode_tab(config.mode.upper())

    def _apply_http(self, config: HttpConfig) -> None:
        self.http_server_url.setText(config.server_url)
        self.http_device_count.setValue(config.device_count)
        self.http_ramp_seconds.setValue(config.ramp_seconds)
        self.http_duration_seconds.setValue(config.duration_seconds)
        self.http_heartbeat_interval.setValue(config.heartbeat_interval)
        self.http_status_interval.setValue(config.status_interval)
        self.http_alarm_probability.setValue(config.alarm_probability)
        self.http_payload_size.setValue(config.payload_size)
        self.http_device_id_prefix.setText(config.device_id_prefix)
        self.http_auth_token.setText(config.auth_token)
        self.http_max_concurrency.setValue(config.max_concurrency)
        self.http_request_timeout.setValue(config.request_timeout)
        self.http_status_path.setText(config.status_path)
        self.http_heartbeat_path.setText(config.heartbeat_path)
        self.http_alarm_path.setText(config.alarm_path)

    def _apply_mqtt(self, config: MqttConfig) -> None:
        self.mqtt_server_url.setText(config.server_url)
        self.mqtt_device_count.setValue(config.device_count)
        self.mqtt_ramp_seconds.setValue(config.ramp_seconds)
        self.mqtt_duration_seconds.setValue(config.duration_seconds)
        self.mqtt_heartbeat_interval.setValue(config.heartbeat_interval)
        self.mqtt_status_interval.setValue(config.status_interval)
        self.mqtt_alarm_probability.setValue(config.alarm_probability)
        self.mqtt_payload_size.setValue(config.payload_size)
        self.mqtt_device_id_prefix.setText(config.device_id_prefix)
        self.mqtt_auth_token.setText(config.auth_token)
        self.mqtt_max_concurrency.setValue(config.max_concurrency)
        self.mqtt_topic_prefix.setText(config.topic_prefix)
        self.mqtt_port.setValue(config.port)
        self.mqtt_tls.setChecked(config.tls)
        self.mqtt_username.setText(config.username)
        self.mqtt_password.setText(config.password)

    def _apply_gb28181(self, config: Gb28181Config) -> None:
        sip = config.sip
        media = config.media
        self.gb_sip_server_ip.setText(sip.server_ip)
        self.gb_sip_server_port.setValue(sip.server_port)
        self.gb_sip_domain_id.setText(sip.domain_id)
        self.gb_local_device_ip.setText(sip.local_device_ip)
        self.gb_local_sip_start_port.setValue(sip.local_sip_start_port)
        self.gb_device_id_prefix.setText(sip.device_id_prefix)
        self.gb_device_count.setValue(sip.device_count)
        self.gb_password.setText(sip.password)
        self.gb_sip_transport.setCurrentText(sip.transport.upper())
        self.gb_heartbeat_interval.setValue(sip.heartbeat_interval)
        self.gb_register_expires.setValue(sip.register_expires)
        self.gb_ramp_seconds.setValue(sip.ramp_seconds)
        self.gb_duration_seconds.setValue(sip.duration_seconds)
        self.gb_sip_timeout.setValue(sip.sip_timeout)
        self.gb_channels_per_device.setValue(sip.channels_per_device)
        self.gb_offline_enabled.setChecked(sip.offline_simulation_enabled)
        self.gb_offline_probability.setValue(sip.offline_probability)
        self.gb_offline_duration.setValue(sip.offline_duration_seconds)
        self.gb_media_enabled.setChecked(media.enabled)
        self.gb_rtp_transport.setCurrentText(media.rtp_transport.upper())
        self.gb_rtp_local_port_start.setValue(media.local_port_start)
        self.gb_rtp_local_port_end.setValue(media.local_port_end)
        self.gb_video_file_path.setText(media.video_file_path)
        self.gb_concurrent_streams.setValue(media.concurrent_streams)
        self.gb_bitrate_kbps.setValue(media.bitrate_kbps)
        self.gb_fps.setValue(media.fps)
        self.gb_video_codec.setCurrentText(media.video_codec.upper())
        self.gb_payload_format.setCurrentIndex(max(0, self.gb_payload_format.findData(media.payload_format)))
        self.gb_loop.setChecked(media.loop)
        self.gb_trigger_mode.setCurrentIndex(max(0, self.gb_trigger_mode.findData(media.trigger_mode)))

    def _collect_config(self) -> AppConfig:
        config = AppConfig(
            mode=self.mode.currentText(),
            http=HttpConfig(
                server_url=self.http_server_url.text().strip(),
                device_count=self.http_device_count.value(),
                ramp_seconds=self.http_ramp_seconds.value(),
                duration_seconds=self.http_duration_seconds.value(),
                heartbeat_interval=self.http_heartbeat_interval.value(),
                status_interval=self.http_status_interval.value(),
                alarm_probability=self.http_alarm_probability.value(),
                payload_size=self.http_payload_size.value(),
                device_id_prefix=self.http_device_id_prefix.text().strip(),
                auth_token=self.http_auth_token.text(),
                max_concurrency=self.http_max_concurrency.value(),
                request_timeout=self.http_request_timeout.value(),
                status_path=self.http_status_path.text().strip(),
                heartbeat_path=self.http_heartbeat_path.text().strip(),
                alarm_path=self.http_alarm_path.text().strip(),
            ),
            mqtt=MqttConfig(
                server_url=self.mqtt_server_url.text().strip(),
                device_count=self.mqtt_device_count.value(),
                ramp_seconds=self.mqtt_ramp_seconds.value(),
                duration_seconds=self.mqtt_duration_seconds.value(),
                heartbeat_interval=self.mqtt_heartbeat_interval.value(),
                status_interval=self.mqtt_status_interval.value(),
                alarm_probability=self.mqtt_alarm_probability.value(),
                payload_size=self.mqtt_payload_size.value(),
                device_id_prefix=self.mqtt_device_id_prefix.text().strip(),
                auth_token=self.mqtt_auth_token.text(),
                max_concurrency=self.mqtt_max_concurrency.value(),
                topic_prefix=self.mqtt_topic_prefix.text().strip(),
                port=self.mqtt_port.value(),
                tls=self.mqtt_tls.isChecked(),
                username=self.mqtt_username.text().strip(),
                password=self.mqtt_password.text(),
            ),
            gb28181=Gb28181Config(
                sip=GbSipConfig(
                    server_ip=self.gb_sip_server_ip.text().strip(),
                    server_port=self.gb_sip_server_port.value(),
                    domain_id=self.gb_sip_domain_id.text().strip(),
                    local_device_ip=self.gb_local_device_ip.text().strip(),
                    local_sip_start_port=self.gb_local_sip_start_port.value(),
                    device_id_prefix=self.gb_device_id_prefix.text().strip(),
                    device_count=self.gb_device_count.value(),
                    password=self.gb_password.text(),
                    transport=self.gb_sip_transport.currentText(),
                    heartbeat_interval=self.gb_heartbeat_interval.value(),
                    register_expires=self.gb_register_expires.value(),
                    ramp_seconds=self.gb_ramp_seconds.value(),
                    duration_seconds=self.gb_duration_seconds.value(),
                    sip_timeout=self.gb_sip_timeout.value(),
                    offline_simulation_enabled=self.gb_offline_enabled.isChecked(),
                    offline_probability=self.gb_offline_probability.value(),
                    offline_duration_seconds=self.gb_offline_duration.value(),
                    channels_per_device=self.gb_channels_per_device.value(),
                ),
                media=GbMediaConfig(
                    enabled=self.gb_media_enabled.isChecked(),
                    rtp_transport=self.gb_rtp_transport.currentText(),
                    local_port_start=self.gb_rtp_local_port_start.value(),
                    local_port_end=self.gb_rtp_local_port_end.value(),
                    video_file_path=self.gb_video_file_path.text().strip(),
                    concurrent_streams=self.gb_concurrent_streams.value(),
                    bitrate_kbps=self.gb_bitrate_kbps.value(),
                    fps=self.gb_fps.value(),
                    video_codec=self.gb_video_codec.currentText(),
                    payload_format=self.gb_payload_format.currentData(),
                    loop=self.gb_loop.isChecked(),
                    trigger_mode=self.gb_trigger_mode.currentData(),
                ),
            ),
        )
        config.ensure_valid()
        return config

    def start_test(self) -> None:
        try:
            config = self._collect_config()
        except ValueError as exc:
            QMessageBox.warning(self, "配置错误", str(exc))
            return
        self.last_report = None
        self._clear_outputs()
        self.worker = LoadTestThread(config)
        self.worker.event_emitted.connect(self.handle_event)
        self.worker.report_ready.connect(self.on_report_ready)
        self.worker.failed.connect(self.on_failed)
        self.worker.finished.connect(lambda: self._set_running(False))
        self.worker.start()
        self._set_running(True)

    def toggle_pause(self) -> None:
        if not self.worker:
            return
        if self.worker.is_paused():
            self.worker.resume_test()
            self.pause_button.setText("暂停")
        else:
            self.worker.pause_test()
            self.pause_button.setText("继续")

    def stop_test(self) -> None:
        if self.worker:
            self.worker.stop_test()

    def handle_event(self, event: dict[str, Any]) -> None:
        event_type = event.get("type")
        if event_type == "metrics":
            self.update_metrics(event.get("metrics", {}))
        elif event_type == "log":
            self.append_log(str(event.get("message", "")))

    def update_metrics(self, data: dict[str, Any]) -> None:
        for key, label in self.stat_labels.items():
            value = data.get(key, 0)
            if isinstance(value, float):
                label.setText(f"{value:.2f}")
            else:
                label.setText(str(value))
        self.text_widgets["状态码分布"].setPlainText(self._format_distribution(data.get("status_codes", {})))
        self.text_widgets["异常分布"].setPlainText(self._format_distribution(data.get("exceptions", {})))

    def on_report_ready(self, report: dict[str, Any]) -> None:
        self.last_report = report
        self.export_button.setEnabled(True)
        self.append_log("测试完成，可以导出 report.json 和 report.csv。")

    def on_failed(self, message: str) -> None:
        QMessageBox.critical(self, "运行失败", message)
        self.append_log(f"运行失败: {message}")

    def save_config(self) -> None:
        try:
            config = self._collect_config()
        except ValueError as exc:
            QMessageBox.warning(self, "配置错误", str(exc))
            return
        path, _ = QFileDialog.getSaveFileName(self, "保存配置", "config.json", "JSON (*.json)")
        if path:
            config.save(path)
            self.append_log(f"配置已保存: {path}")

    def load_config(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "加载配置", "", "JSON (*.json)")
        if not path:
            return
        try:
            config = AppConfig.load(path)
            config.ensure_valid()
        except Exception as exc:
            QMessageBox.warning(self, "加载失败", str(exc))
            return
        self._apply_config(config)
        self.append_log(f"配置已加载: {path}")

    def export_report(self) -> None:
        if not self.last_report:
            QMessageBox.information(self, "暂无报告", "测试结束后才能导出报告。")
            return
        directory = QFileDialog.getExistingDirectory(self, "选择报告输出目录", str(Path.cwd()))
        if not directory:
            return
        output_dir = Path(directory)
        write_json_report(output_dir / "report.json", self.last_report)
        write_csv_report(output_dir / "report.csv", self.last_report)
        self.append_log(f"报告已导出: {output_dir / 'report.json'}")
        self.append_log(f"报告已导出: {output_dir / 'report.csv'}")

    def append_log(self, message: str) -> None:
        self.text_widgets["运行日志"].appendPlainText(message)

    def _set_running(self, running: bool) -> None:
        self.start_button.setEnabled(not running)
        self.load_config_button.setEnabled(not running)
        self.save_config_button.setEnabled(not running)
        self.pause_button.setEnabled(running)
        self.stop_button.setEnabled(running)
        self.pause_button.setText("暂停")
        if running:
            self.export_button.setEnabled(False)
        elif not self.last_report:
            self.export_button.setEnabled(False)

    def _clear_outputs(self) -> None:
        for text in self.text_widgets.values():
            text.clear()
        for label in self.stat_labels.values():
            label.setText("0")

    def _format_distribution(self, values: dict[str, int]) -> str:
        if not values:
            return ""
        return "\n".join(f"{key}: {value}" for key, value in values.items())

    def _browse_video_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "选择视频文件", "", "Video/Data (*.*)")
        if path:
            self.gb_video_file_path.setText(path)

    def _sync_mode_tab(self, mode: str) -> None:
        index = {"HTTP": 0, "MQTT": 1, "GB28181": 2}.get(mode.upper(), 0)
        self.tabs.setCurrentIndex(index)

    def closeEvent(self, event: Any) -> None:
        if self.worker and self.worker.isRunning():
            reply = QMessageBox.question(self, "确认退出", "压测仍在运行，是否停止并退出？")
            if reply != QMessageBox.Yes:
                event.ignore()
                return
            self.worker.stop_test()
            if not self.worker.wait(15_000):
                QMessageBox.warning(self, "仍在停止", "worker 仍在等待网络请求退出，请稍后再关闭。")
                event.ignore()
                return
        event.accept()

def _asset_path(relative: str) -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))
    return base / relative


def _load_app_icon() -> QIcon:
    icon_path = _asset_path("assets/app.ico")
    return QIcon(str(icon_path)) if icon_path.exists() else QIcon()


def main() -> None:
    app = QApplication(sys.argv)
    app.setWindowIcon(_load_app_icon())
    window = MainWindow()
    window.setWindowIcon(_load_app_icon())
    window.show()
    sys.exit(app.exec())
