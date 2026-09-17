# 输入协议与复现

## 运行

Python 3.9+。计算部分仅标准库；图形部分需 `matplotlib>=3.6`、`numpy>=1.23`、`Pillow>=8`。可选技能结构校验需 PyYAML。本包不自动安装依赖，也不触发 GPU/网络/远程命令。

```bash
# 在技能目录执行：使用任务自己的输出位置
python3 scripts/roofline.py --input examples/source_reconstruction.json --output-dir /tmp/roofline-source-demo
python3 scripts/roofline.py --input examples/synthetic_portable.json --output-dir /tmp/roofline-portable-demo
python3 scripts/roofline.py --input /path/to/case.json --output-dir /path/to/results --no-plot --strict
python3 -m unittest discover -s scripts -p 'test_*.py' -v
```

`--overwrite` 显式覆盖该输出目录中的同名报告文件，默认非空目录会拒绝。无需 GPU；示例不会运行原文的模型启动命令。没有 plots 依赖时计算文件仍可用，但完整绘图任务需补齐依赖再跑。

## JSON 结构（schema_version=1）

所有 time/operations/bytes 都是 **每次 case 调用** 的量。`time_ms` 的每个元素对应相同 F/Q 的重复运行；不同 shape 或流量变化大时拆 case。不能把整个重复批次时间直接塞成单次样本。

顶层：

| 字段 | 含义 |
|---|---|
| title, device | 图表标题和精确目标设备说明；不硬编码卡型 |
| roofs | 非空列表，唯一 id；每条配一组匹配 compute + memory roof |
| cases | 非空列表，唯一 id；每条一个工作负载/计时边界 |
| notes, environment 等 | 可选审计元数据，完整保存在 metrics.json 的 input 中 |

每个 roof：

| 字段 | 必需含义 |
|---|---|
| id, label | 关联 ID、简短可读标签 |
| op_kind | `float` / `integer` / `instruction`，对应 FLOP / OP / instruction |
| path | 经核验的指令/精度/稀疏路径名称，与 case 精确一致 |
| layer | 内存层级，如 HBM / DRAM / L2；与 byte model 一致 |
| kind | `spec` 或 `calibrated`；校准实验/规格来源写清 |
| compute_tops | 数值单位 `10^12 operations/s`；float 时 TFLOP/s，整数时 TOP/s |
| bandwidth_gbps | **十进制 GB/s**；3.35 TB/s 应输入 3350 |
| source | 文档 URL/页码/日期，或实验命令、环境和文件位置 |

同一 case 可选择规格和校准两条 roof；不把参考库速度放进 roof，另作一个基准 case。多设备比较使用独立输入文件或逐硬件运行，避免跨设备归一化混乱。

每个 case：

| 字段 | 含义 |
|---|---|
| id, label, scope | 唯一 ID、简短图标签、精确计时/工作量边界 |
| path, op_kind | 与所选 roof 一致 |
| work_basis | `useful` 或 `executed`；推导口径由分析者负责 |
| work | 下表之一 |
| time_ms | 正数重复样本列表，程序报告 median/p10/p90/min/max/n |
| timing_kind | `measured` / `derived` / `synthetic`；来源中转述的实测不能冒称本轮新测 |
| timing_source | 原始文件/调用 ID/计时协议/来源，单样本也要标明 |
| cache_policy | 冷/暖/应用自然状态、replay 设置；未知就写 unknown |
| roof_ids | 非空、无重复的 roof ID 列表 |
| byte_models | 至少一条，见下文 |
| e2e_fraction | 可选 `[0,1]`，串行关键路径占比；同时必须有 e2e_fraction_source |

### work 模型

| kind | 字段 / 工作量 |
|---|---|
| `gemm` | m,n,k（正整数），可选 batch=1；`2*batch*m*n*k` |
| `grouped_gemm` | groups 列表，每组 m≥0,n>0,k>0，可选 count=1 表示相同 shape 的组数；求 `Σ2*m*n*k*count` |
| `block_sparse_attention` | pairs≥0（**已包含所有 head/batch**）、bq,bk,dk,dv；`2*pairs*bq*bk*(dk+dv)`，不含 softmax |
| `elementwise` | elements≥0、ops_per_element≥0；乘积；复杂 SFU 不用普通 FLOP 屋顶 |
| `explicit` | operations≥0、derivation（非空）；用于其他算子/执行指令量，必须审计推导 |

公式只负责主工作量，不猜 metadata、额外指令、padding 或实际 routing。`explicit` 不执行表达式字符串，避免任意代码执行。多种精度混合的 case 拆阶段或用单独有定义的 instruction roof。

### byte_models

每条必须有 `id`、`kind=modeled|measured`、`layer`、`source`、非空 `ledger`。每个 ledger item 的 `name` 必须非空；二选一：

```json
{"name":"A read", "elements":1048576, "storage_bits":16, "reads":1, "writes":0}
```

或已经换算为该层级 **总流量** 的 bytes：

```json
{"name":"DRAM read counter", "bytes":2097152}
```

按公式求和。元素数为非负整数，存储位宽为正整数，读写次数可为有来源的非负平均倍数。INT4 可以是 4 bits；布局 padding/transaction amplification 请显式建模或使用 bytes。不能把实测一个总 counter 与其分项重复相加。模型不自动判定 source 的真实性，必须人工审计。

每条 byte model 与所选 roof 中同层级者组合。实测和一次装载模型用不同 ID，共用时间和 F 的前提是状态/边界一致。`Q=0` 时不制造无限 log 坐标；`F=0` 时改为带宽分析，图里不画这两个点，原因写入 plot_qa.json。两者都为零拒绝。

区间估计可建立 lower/upper 两个明确标为 modeled 的 byte models；它们是敏感性端点，不是两次测量。联合统计需使用原始成对观测，当前计算器不自动拟合置信区间。

## 输出与解释

- `metrics.json` 保存输入、SHA256 和逐组合结果；可追溯所有数字。
- `metrics.csv` 是长表，利用率用 0–1 小数，**不预乘 100**。
- `report.md` 是计算摘要，真实 limiter 留待证据补齐；不要直接把模板结论当诊断。
- 按 roof 分图、每张最多三点；每点用颜色+形状，旁栏显示工作量/时间/流量来源口径、AI、吞吐、Uroof/r，纵向虚线表示到匹配屋顶的 gap。
- p10/p90 延迟映射为反向的吞吐范围；n=1 不给虚构误差条。模型参数的不确定性不包含在这个时间误差条里。
- `plot_qa.json` 检查缺字/布局警告、关键文字越界、旁栏和刻度重叠；`human_visual_review=required` 必须实际看图后由分析者验收。

`--strict` 在利用率超过 101% 或程序绘图检查失败时返回 2；1% 是浮点/报告容差，非物理豁免。只要 Uroof>100%，脚本就不提供加速承诺，保留原点。模型流量、单样本、未校准或派生时间会警告但不会阻止明确标注的估算。

## 输入验证责任

程序验证正数/有限值、维度、枚举、重复 ID、跨精度路径和内存层级匹配，并检查数值恒等式。它**不能**从一个任意 path 字符串证明 GPU 真的执行该指令；也不能识别所有逻辑流量重复计数、计时范围不实、dense/sparse 指标错配。这些必须遵循 SOP 的代码、counter 和来源核对。
