# 猫猫鲨压测平台

这个代码库和它的名字一样奇怪。

虽然我也不知道为什么猫猫会和鲨鱼混在一起，但她很可爱，不是吗？

请注意，以下是内部情报：

这是一只会对你的服务器哈气的小鲨鱼。  
所以在使用前，请记得先投喂她正确的服务器配置。

她可以模拟大量 GB28181 布控球设备，对服务器进行注册、心跳、告警和流媒体压力测试。  
简单来说，她会帮你确认服务器在被一群小鲨鱼围攻的时候还能不能活着。

如果小鲨鱼开始乱咬东西、拆家、发出奇怪错误，可能是受到了某种未知生物影响。  
也可能只是 bug。

据说这只小鲨鱼是北极星工业集团的小宠物。  
至于为什么她看起来像猫猫，这件事目前仍然没有可靠解释。

# 布控球服务器压测上位机

Windows 优先的 Python 3 / PySide6 图形压测工具。调度核心使用 `asyncio`，HTTP 使用 `aiohttp`，MQTT 使用 `gmqtt`，新增 GB/T 28181 国标信令压测。

默认配置不写入任何现场或生产服务器地址。GB28181 SIP 服务器 IP 默认为空，必须手动填写。

## 安全边界

- 只允许对明确授权的测试环境或压测窗口使用。
- 必须配置测试时长，程序不支持无限运行。
- 界面提供停止按钮，停止后会取消所有模拟设备任务。
- 默认设备数量是 50，不超过 100。
- 媒体压测第一版在界面硬限制最多 10 路，避免误开大规模视频。
- `config.json` 会保存 token 和密码；报告中的 token/password 会自动脱敏。

## 安装运行

```powershell
cd C:\Users\17937\Documents\Codex\2026-07-07\windows-python-3-pyside6-gui-asyncio\outputs\bukong-load-tester
py -3 -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
python run.py
```

## 分布式 headless 模式

GUI 仍使用：

```powershell
python run.py
```

分布式节点使用 headless worker，不依赖 PySide6 界面：

```powershell
python -m bukong_load_tester.headless_worker `
  --config C:\path\to\config.json `
  --run-id gb28181-run-001 `
  --node-id load-node-01 `
  --shard-index 0 `
  --shard-count 4 `
  --output-dir C:\load-output\gb28181-run-001\node-0
```

每个节点输出：

```text
report.json
report.csv
node.log
```

合并多个节点报告：

```powershell
python -m bukong_load_tester.merge_reports `
  --input-dir C:\load-output\gb28181-run-001 `
  --output-dir C:\load-output\gb28181-run-001\merged
```

详细多机部署、运行、停止和汇总流程见 `DISTRIBUTED_TEST.md`。

## 模式

### HTTP

保留原 HTTP 压测能力：模拟设备定时 POST heartbeat、status，并按概率 POST alarm。

本地 mock：

```powershell
python tools\mock_http_server.py
```

命令行冒烟：

```powershell
python tools\smoke_http.py
```

### MQTT

保留原 MQTT 压测能力：模拟设备发布 `heartbeat`、`status`、`fault` topic。

### GB28181

GB28181 模式明确区分两层传输，不使用全局 TCP/UDP 开关：

- SIP 信令传输：`UDP` 或 `TCP`
- RTP 媒体传输：`UDP` 或 `TCP`

第一版优先实现信令压测：

- 多设备分批 REGISTER 注册。
- 支持 401 Digest MD5 鉴权后重 REGISTER。
- 统计注册成功数、注册失败数、在线设备数、SIP 状态码分布。
- 按心跳间隔发送 Keepalive MESSAGE。
- 支持 Catalog 查询响应，返回简化目录。
- 支持离线和重连模拟。
- 统计心跳发送数、超时数、每秒消息数、Catalog 查询/响应数。

媒体层第一版只做小规模验证和接口预留：

- `RtpUdpSender`
- `RtpTcpSender`
- 设备主动连平台方向。
- 配置层预留 H.264/H.265 与 PS over RTP / ES over RTP。
- 支持从 INVITE SDP 解析平台 RTP 目标后小规模推流。
- 主动测试推流入口保留；没有独立 RTP 目标字段时不会直接向未知平台推流。
- 不在第一版直接强做几千路视频。

本地 GB28181 信令 mock：

```powershell
python tools\mock_gb28181_sip_server.py --transport udp --host 127.0.0.1 --port 15061
python tools\mock_gb28181_sip_server.py --transport tcp --host 127.0.0.1 --port 15062
```

GB28181 UDP/TCP 冒烟：

```powershell
python tools\smoke_gb28181.py
```

## 配置结构

新版 `config.json` 是嵌套结构：

```json
{
  "mode": "GB28181",
  "http": {},
  "mqtt": {},
  "gb28181": {
    "sip": {
      "server_ip": "",
      "server_port": 5060,
      "domain_id": "",
      "local_device_ip": "127.0.0.1",
      "local_sip_start_port": 15060,
      "device_id_prefix": "340200000013200",
      "device_count": 50,
      "password": "",
      "transport": "UDP",
      "heartbeat_interval": 30.0,
      "register_expires": 3600,
      "ramp_seconds": 60,
      "duration_seconds": 300,
      "channels_per_device": 1
    },
    "media": {
      "enabled": false,
      "rtp_transport": "UDP",
      "local_port_start": 30000,
      "local_port_end": 30020,
      "video_file_path": "",
      "concurrent_streams": 1,
      "bitrate_kbps": 512,
      "fps": 25,
      "video_codec": "H264",
      "payload_format": "PS_OVER_RTP",
      "loop": true,
      "trigger_mode": "invite_then_stream"
    }
  }
}
```

旧版扁平 `config.json` 可继续加载，会自动映射到 HTTP/MQTT 配置。

## 三种用法

### 1. 本地小规模测试

用于验证工具、payload、接口路径、GB28181 REGISTER/Keepalive/Catalog 和报告导出。

建议配置：

```text
服务器地址: 127.0.0.1
设备数量: 3-20
爬坡时间: 5-30 秒
测试时长: 30-120 秒
```

### 2. 测试环境压测

用于验证授权测试环境服务器容量和业务链路。SIP UDP 与 SIP TCP 建议分别跑两轮，RTP UDP 与 RTP TCP 也分别小规模验证。

建议配置：

```text
设备数量: 从 50、100、1000 逐级增加
爬坡时间: 不低于 60 秒
测试时长: 5-30 分钟
媒体并发: 第一版不超过 10 路
```

压测时同时观察服务端 CPU、内存、连接数、SIP 状态码、数据库、消息队列和错误日志。

### 3. 正式压测

只在获得书面授权、确认压测窗口、确认回滚和告警联系人后执行。不要直接复用本地配置打到生产环境。

建议流程：

```text
1. 先在测试环境复现相同配置。
2. SIP UDP、SIP TCP 分开压测，记录各自报告。
3. 从小设备数开始，逐级升压到目标在线规模。
4. 媒体先做小规模链路验证，再由专门媒体压测方案扩展到 1-2 千路。
5. 每一档结束后保存 report.json/report.csv 和服务端监控截图。
6. 出现大面积 5xx、SIP 超时、注册失败、连接失败、队列堆积或核心业务异常时立即停止。
```
