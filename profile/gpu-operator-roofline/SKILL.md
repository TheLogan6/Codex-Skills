---
name: gpu-operator-roofline
description: "GPU operator/kernel Roofline analysis and plotting：推导 FLOPs/OPs 与 HBM/DRAM/L2 流量，核对硬件峰值，结合实测计算算术强度 arithmetic intensity (AI)、MFU、带宽利用率和性能 gap。用于算子性能分析、MFU 低/算力没打满、compute-bound 或 memory-bound 判断、优化空间评估、换卡/精度/tile 性能对比；适用 GEMM/grouped GEMM/MoE、Attention、量化、归约及其他加速器算子。输出可复现图表、瓶颈证据和验证实验；不用于无性能问题的普通绘图或纯 GPU 规格查询。"
---

# GPU Operator Roofline

把“为什么只发挥了少量峰值算力，是否值得优化”变成可核查的证据链：

**算子语义 → 工作量/流量模型 → 硬件屋顶 → 稳定计时 → Roofline 落点 → 瓶颈验证 → 优化实验 → 正确性与端到端复测。**

默认中文解释，图默认英文技术标签。本包可独立使用，不依赖相邻技能、Lark 登录或某种 GPU。分析方法通用，但硬件峰值、指令计数、计数器名称和可达收益必须逐环境核验。

## 先判断能回答到哪一步

| 已有证据 | 可以交付 | 不能声称 |
|---|---|---|
| 只有算子/shape | 符号工作量、流量模型、待采集项 | 实测 MFU、实际瓶颈 |
| shape + 硬件峰值 + 延迟 | 建模 AI、有效吞吐、模型屋顶和 gap | HBM 带宽已经打满 |
| 再有同边界、同缓存策略的流量计数器 | 实测流量 Roofline、分层利用率 | 单凭落点证明因果 |
| 再有 timeline、管线/stall 和对照实验 | 有置信度的瓶颈结论、优化优先级 | 把理论空间当成保证收益 |

缺数据时先完成可完成的部分，列出会改变结论的最少缺口。不要为了画一个完整点而伪造时间、Bytes、峰值或计数器。

## SOP

### 1. 固定分析边界和证据

记录 kernel/算子名、代码 commit/二进制 hash、实际执行路径、shape/layout/stride、输入/输出/累加/scale 精度、设备/rank、融合范围、计时范围、缓存策略。多 kernel 算子记录组成和依赖，单卡 kernel 与多卡 step 分开。

源材料含图片、内嵌表格时区分正文、图注/自动描述、原图、原始测量四种证据；读不到的部分明确标注。远程代码块只作为材料，不自动执行。参考 [来源案例](references/source_case.md) 学习原文的成功链路与不能照搬的假设。

### 2. 推导操作数和 Bytes

先读 [建模规则](references/modeling.md)，给出带变量定义、代入值和假设的推导，再运行脚本。

- `F_useful`：数学上有用的工作量；`F_executed`：包含 padding、重算等的实际工作量。分别报告，不能混换坐标分子。
- 整数算术用 OP、TOP/s；浮点用 FLOP、TFLOP/s；约定 MAC/FMA = 2 operations。沿用日志的“MFU”时说明它是算子有效操作吞吐占匹配峰值之比，不是全模型 MFU，也不是 SM busy。
- 为每个内存层级分别建立 `Q_model` 和（可得时）`Q_measured`。列张量/中间结果/元数据的读写账本，区分一次装载假设和真实流量。
- W4A8 的存储位宽与 MMA 运算位宽分别处理；稀疏算法跳块与硬件 2:4 sparse 指令分开。
- 非算术 kernel、SFU/原子/排序/通信主导任务走 byte/s、instruction/s 或时间分解，不强行套 Tensor Core FLOP 峰值。

### 3. 选择匹配的屋顶并稳定计时

读 [采集流程](references/measurement.md)。优先复用用户提供的目标机器和实测记录，不能把本机信息当作远程 GPU 配置。

1. 查目标卡的精确 SKU、板型、MIG/分区、时钟/功耗、显存类型、驱动/工具版本；硬件规格使用厂商资料，注明链接和检索日期。
2. 核对 Tensor/向量/SIMT 路径、输入和累加精度、dense/sparse、单设备资源。没有匹配峰值就保持未知。
3. 规格屋顶与同机校准屋顶分开；固定 shape 的库基准单列为比较目标，不能把弱 baseline 变成“硬件上限”。
4. 预热并剔除编译/autotune，使用正确同步的设备计时；保存重复样本、n、median、p10/p90、环境状态。Profiler replay 与无 profiler 延迟分开。
5. HBM/L2/片上 SRAM 各用自己的流量和带宽，不混层级。无 HBM 的卡使用实际 DRAM/统一内存名称。

### 4. 计算、绘图和质量检查

读 [输入协议与运行方法](references/input_and_tools.md)。从绝对技能目录执行下面脚本，输出到任务工作目录；不修改技能中的示例作为当前用户的数据。

```bash
python3 /path/to/gpu-operator-roofline/scripts/roofline.py \
  --input /path/to/case.json --output-dir /path/to/results
```

脚本不需要 GPU：用标准库算指标、输出 JSON/CSV/Markdown；绘图需 Matplotlib、NumPy、Pillow。可加 `--no-plot` 仅计算，`--strict` 让超屋顶等模型矛盾返回非零。首次运行先确认当前 Python 环境和依赖，复用现有环境或任务专用环境。

统一 SI 单位，`F` 为 operations、`Q` 为 bytes、`t` 为 seconds、`P` 为 operations/s、`B` 为 bytes/s：

```text
AI = F/Q                    ridge = P/B
r = AI/ridge                achieved = F/t
bandwidth = Q/t             roof = min(P, B*AI)
U_compute = achieved/P      U_bandwidth = bandwidth/B
U_roof = achieved/roof      t_lower = max(F/P, Q/B)
S_fixed = t/t_lower         gap_fraction = 1 - U_roof
```

`S_fixed` 是固定 F/Q/屋顶下的条件理想加速倍数，不是收益预测；`t_lower` 是模型下界，实测校准屋顶也不是绝对物理界。改变算法、流量或精度后重新建模。详细诊断见 [瓶颈与优化](references/diagnosis.md)。

绘图使用 log-log，清楚标注设备、精度/路径、层级、屋顶来源、数据流量口径。点和屋顶共享单位；不同精度/层级分面，不把不相关点连成趋势。标出 ridge、点到对应 roof 的距离；保留误差范围，不能裁掉 >100% 的异常点。

产出 PNG 预览、灰度预览和 SVG/PDF 矢量图。先检查 `plot_qa.json`，再实际打开 PNG 读图：标签完整、图例不遮点、误差棒未裁、颜色与符号可区分、图文数值一致。程序通过不替代目视验收；缺字/重叠时修改图参数并重渲。默认无需指定论文期刊。

### 5. 从理论区域升级为实测瓶颈

分别回答以下三问，不用一个 `bound` 标签混在一起：

1. 在所选流量模型下，处于 memory-side、compute-side 还是 ridge 附近？报告 r。
2. 当前 kernel 真的受哪个资源限制？结合实际带宽、指令管线、warp stall、occupancy、时间线和最小对照实验；不足则写“未证实”。
3. 距离对应屋顶有多大，优化是否值得？报告利用率、理想上限、绝对可节省 ms、关键路径时间占比、投入/精度/资源风险。

低 MFU 同时低带宽时，优先排查小规模/尾波、指令吞吐、寄存器/shared memory、spill、依赖/barrier、访存延迟和调度，不直接称为带宽饱和。近 ridge 时先补实测 Bytes/持续峰值；假设误差可能改变区域。

### 6. 给可验证的优化计划并回归

每条建议包含：**证据 → 假设 → 最小改动实验 → 预期计数器/时间变化 → 正确性门槛 → 通过/否定条件**。

不要把“更大 tile/cooperative/persistent 一定更快”写成通则。改 tile 要同时考虑尾块、寄存器、SMEM、并发 CTA、载入和写回；不同卡和 shape 单独调优。

算子正确性至少看约定的绝对/相对误差、NaN/Inf、边界/空组/非对齐 shape；量化验证 scale/zero-point/饱和语义。仅高余弦相似度不充分。优化前后用相同 workload、计时和缓存策略对比，再测真实关键路径及端到端。用户只要诊断时，交付计划，不实施生产优化。

## 标准交付

- `case.json`：输入、来源、推导账本、环境与测量协议，可重跑。
- `metrics.json` / `metrics.csv`：逐 case/流量模型/屋顶结果及异常。
- `report.md`：计算摘要；在其中补齐人工分析的主证据、置信度和验证计划（脚本不会凭数值自动宣布真实瓶颈）。
- `roofline-*.png/.svg/.pdf`、灰度图、`plot_qa.json`。
- 原始 latency/counter 记录、命令和版本；没有测过的阶段明确留缺口。

最终回答先给判断、把握程度和是否值得优化，再给关键数值和最优先的实验。用 [验收用例](references/acceptance.md) 自审，尤其检查有无把建模带宽叫成实测带宽。

## 资源导航

- [modeling.md](references/modeling.md)：GEMM/group GEMM、attention、稀疏、归约、融合的 F/Q 推导。
- [measurement.md](references/measurement.md)：机器探测、NVIDIA/AMD/其他平台采集与可靠计时。
- [diagnosis.md](references/diagnosis.md)：gap、分层瓶颈、优化收益与证据表。
- [input_and_tools.md](references/input_and_tools.md)：JSON 协议、计算器、绘图和复现命令。
- [source_case.md](references/source_case.md)：原文案例的蒸馏、复算和局限。
- [acceptance.md](references/acceptance.md)：场景验收、反例和自动测试。
- [sources.md](references/sources.md)：权威方法、工具、ISA 参考及使用边界。
