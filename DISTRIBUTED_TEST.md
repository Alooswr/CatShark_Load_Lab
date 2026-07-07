# 分布式 GB28181 压测说明

本工具支持把 `bukong-load-tester` 打包到多台 Windows 压测机上，每台机器运行 headless worker，模拟一部分 GB28181 布控球设备，最后合并多个节点报告。

默认示例不写入现场 IP、端口、密码。只对授权测试环境使用。

## 1. 部署

每台压测机安装 Python 3，然后放置同一份工具目录：

```powershell
cd bukong-load-tester
py -3 -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
```

复制 `examples\distributed\base_config.template.json` 为自己的 `config.json`，填写授权测试环境参数：

```json
{
  "mode": "GB28181",
  "gb28181": {
    "sip": {
      "server_ip": "",
      "server_port": 5060,
      "domain_id": "",
      "password": "",
      "device_count": 20000
    }
  }
}
```

`device_count` 表示整场压测的总设备数，不是单节点设备数。

`local_device_ip` 必须填写当前压测机对 SIP 服务器可达的网卡 IP，不要使用模板空值直接运行。

## 2. 分片规则

worker 参数：

```text
--config       配置文件路径
--run-id       本次压测的统一 ID
--node-id      当前节点 ID
--shard-index  当前分片序号，从 0 开始
--shard-count  总分片数
--output-dir   当前节点输出目录
```

设备分配按总设备数自动均分：

```text
device_count = 20000
shard_count = 4
node-0: 0-4999
node-1: 5000-9999
node-2: 10000-14999
node-3: 15000-19999
```

设备 ID 使用 `device_id_prefix + 全局序号` 生成 20 位国标编码，因此不同节点不会冲突。

本地端口自动平移：

- SIP 端口：`local_sip_start_port + 当前分片全局起点`
- RTP 端口：`local_port_start + shard_index * 原始 RTP 端口段长度`

如果多分片跑在同一台机器上，这两个规则可以避免同一节点内端口冲突。大规模压测前要确认端口范围不会超过 `65535`。

## 3. 启动

2 节点示例：

```powershell
cd examples\distributed\2-nodes
.\run-node.ps1 -ShardIndex 0 -RunId gb28181-run-001
.\run-node.ps1 -ShardIndex 1 -RunId gb28181-run-001
```

4 节点示例：

```powershell
cd examples\distributed\4-nodes
.\run-node.ps1 -ShardIndex 0 -RunId gb28181-run-001
.\run-node.ps1 -ShardIndex 1 -RunId gb28181-run-001
.\run-node.ps1 -ShardIndex 2 -RunId gb28181-run-001
.\run-node.ps1 -ShardIndex 3 -RunId gb28181-run-001
```

8 节点同理，使用 `examples\distributed\8-nodes\run-node.ps1`，`ShardIndex` 为 `0..7`。

也可以直接运行：

```powershell
python -m bukong_load_tester.headless_worker `
  --config C:\path\to\config.json `
  --run-id gb28181-run-001 `
  --node-id load-node-01 `
  --shard-index 0 `
  --shard-count 4 `
  --output-dir C:\load-output\gb28181-run-001\node-0
```

## 4. 停止

首选让测试按 `duration_seconds` 自动结束。需要提前停止时，在对应节点窗口按 `Ctrl+C`。

每个节点独立输出：

```text
report.json
report.csv
node.log
```

`node.log` 会记录启动参数、设备范围、端口范围和报告路径。

## 5. 汇总报告

把各节点输出目录收集到同一台机器，例如：

```text
C:\load-output\gb28181-run-001\node-0\report.json
C:\load-output\gb28181-run-001\node-1\report.json
C:\load-output\gb28181-run-001\node-2\report.json
C:\load-output\gb28181-run-001\node-3\report.json
```

运行合并：

```powershell
python -m bukong_load_tester.merge_reports `
  --input-dir C:\load-output\gb28181-run-001 `
  --output-dir C:\load-output\gb28181-run-001\merged
```

输出：

```text
merged_report.json
merged_report.csv
```

合并报告会汇总：

- run_id
- node_count / shard_count
- 全局设备范围
- 节点列表
- SIP 状态码分布
- 注册成功/失败数
- 心跳数
- 超时数
- Catalog 查询/响应数
- 峰值在线设备数
- 异常分布

节点级 P50/P95/P99 没有原始延迟样本，合并报告使用各节点对应分位值的最大值作为保守观察值。

## 6. 媒体限制

第一版仍保持媒体压测最多 10 路硬限制，不扩展到 1-2 千路视频。大规模视频压测需要单独媒体专项方案。

媒体配置可预留 RTP UDP/TCP、H.264/H.265、PS over RTP / ES over RTP，但当前分布式目标优先是 2-3 万设备在线和信令容量。
