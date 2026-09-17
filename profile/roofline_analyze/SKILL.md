---
name: "roofline_analyze"
description: "Analyzes DL operators with measured or modeled Roofline, arithmetic intensity, ridge-point distance, and bottleneck evidence. Invoke for GPU kernel performance, MFU/MBU, or compute-vs-memory diagnosis."
---

# Roofline Analyze

用于分析深度学习算子、融合 kernel、模型阶段或端到端 workload 是否受 compute、memory、latency/overhead、occupancy 或通信限制，并判断其相对 Roofline 拐点的位置。

## 核心原则

1. 只比较同一口径的数据：相同硬件、数据类型、dense/sparse 模式、时钟状态、功耗状态、并行规模和内存层级。
2. 算术强度定义为：

   `I_L = F / Q_L`，单位 `FLOP/Byte`

   - `F`：本次 kernel 或分析区域实际执行或算法定义的 FLOPs。
   - `Q_L`：该区域在内存层级 `L` 上传输的 Bytes。
   - `L` 可以是 HBM/DRAM、L2、L1/shared memory；不注明层级的 `I` 没有完整含义。
3. Roofline 上限：

   `P_roof(I) = min(P_compute, BW_L × I_L)`

4. 拐点：

   `I_ridge,L = P_compute / BW_L`

5. `I_L < I_ridge,L` 只表示该层级的理论带宽屋顶低于计算屋顶，不等价于“实测一定被带宽打满”。最终结论必须结合计数器、时间线和敏感性实验。
6. 算术强度不是脱离实现的绝对“算子固有属性”。FLOPs 主要由算法与 shape 决定，但 Bytes 会受融合、tiling、缓存命中、重计算、布局、并行切分和实现边界影响。必须区分算法级 I、实现级 I 和实测 I。
7. 禁止用端到端 MFU 单独判定某个 kernel 的瓶颈；禁止用白皮书峰值直接代替持续可达峰值。

## 触发场景

在以下请求中调用：

- 判断算子或 kernel 是 computation-bound 还是 memory-bound。
- 计算 arithmetic intensity、Roofline、ridge point、MFU、MBU。
- 分析 GEMM、Attention、FlashAttention、Norm、Softmax、element-wise、MoE、卷积、KV cache、量化 kernel。
- 分析换卡、换精度、改 batch/Seq_len/shape 后瓶颈为何变化。
- 根据 Nsight Systems、Nsight Compute、PyTorch Profiler、Triton benchmark 或日志给优化建议。
- 估算优化理论上限，判断是否值得做融合、低精度、Tensor Core、tiling、batching 或 CUDA Graph。

## 必需输入

优先收集：

- GPU 型号、卡数、互联拓扑；若是单 kernel，默认先做单卡分析。
- 数据类型：输入、输出、累加、权重、量化 scale/zero-point 的精度。
- 稠密或结构化稀疏；Tensor Core 或 CUDA Core 路径。
- 完整 shape、layout、stride、batch、Seq_len、head 数、head_dim、并行切分。
- 算子边界：单算子、融合 kernel、CUDA Graph 区域、模型阶段或端到端 step。
- 计时：warmup、重复次数、同步方式、均值/中位数/分位数。
- Bytes 口径：算法最小流量、Profiler 实测 HBM 流量或其他缓存层级流量。
- 峰值口径：datasheet 理论峰值、microbenchmark 实测持续峰值或库基准峰值。
- 是否包含 launch、CPU、通信、重编译、padding、重计算和同步。

信息不足时：

- 可先输出符号公式和上下界。
- 明确列出假设与缺失项。
- 不得伪造硬件峰值、Profiler counter 或测量结果。
- 不得在缺少 shape、dtype、kernel 边界或 Bytes 口径时给出确定的拐点结论。

## 分析口径

### 三种 Roofline

必须标注采用哪一种：

1. **算法 Roofline**
   - `F_alg`：数学上必要 FLOPs。
   - `Q_min`：理想情况下从目标内存层级至少传输的 Bytes。
   - 用于判断算法上限和优化潜力。

2. **实现 Roofline**
   - `F_impl`：实现真正执行的 FLOPs，包括必要时的重计算、padding 和额外操作。
   - `Q_impl`：基于 kernel 实现、融合边界和缓存假设建模的 Bytes。
   - 用于比较不同 kernel 设计。

3. **实测 Roofline**
   - `F_meas`：硬件计数器或经验证模型对应的 FLOPs。
   - `Q_meas`：Profiler 在指定层级统计的实际 Bytes。
   - 用于判定当前实现的真实落点。

不得混用，例如用 `F_alg / Q_min` 得到的 I 搭配 `F_impl / time` 而不做说明。

### 峰值选择

`P_compute` 必须与执行路径一致：

- FP32 CUDA Core、TF32 Tensor Core、BF16/FP16 Tensor Core、FP8、INT8 分开。
- dense 与 2:4 sparse 峰值分开。
- FMA 通常计作 2 FLOPs；必须全文统一。
- 矩阵 shape、对齐、指令选择无法达到 Tensor Core 峰值时，优先使用同类 shape 的 GEMM/microbenchmark 持续峰值。
- 对小 kernel，datasheet 峰值通常不具可达性，应同时给出 theoretical 与 empirical roof。

`BW_L` 优先级：

1. 同机同状态下的内存带宽 microbenchmark。
2. 同类访问模式的可达带宽。
3. datasheet 理论峰值，仅用于粗略上界。

ECC、MIG、功耗限制、时钟、NUMA、并发 kernel 会改变有效上限，必须注明。

## FLOPs 计算

统一采用 FMA = 2 FLOPs，除非工具或用户采用其他口径。

### GEMM

对 `C[M,N] = A[M,K] × B[K,N]`：

`F_GEMM = 2MNK`

若存在 bias、activation、scaling、dequantization 或 epilogue，分别加上其 FLOPs。若 `beta != 0`，还需计入读取旧 `C` 和对应计算。

### Batched GEMM

`F_BGEMM = 2B_gemmMNK`

注意 `B_gemm` 是矩阵乘批次数，不一定等于模型 batch。

### Element-wise

逐元素枚举操作：

- add/sub/mul/div：通常每元素 1 FLOP。
- FMA：每元素 2 FLOPs。
- exp/log/tanh/rsqrt 等特殊函数不能随意按 1 FLOP 与硬件峰值比较。优先单列特殊函数吞吐或采用指令级经验 roof。

### Reduction、Softmax、Norm

分阶段计数并说明算法：

- reduction 的加法约为 `N-1`。
- softmax 至少包含 max reduction、减法、exp、sum reduction、除法。
- LayerNorm/RMSNorm 的 FLOPs 随方差算法、Welford、融合 affine、重计算策略变化。
- 对特殊函数密集 kernel，经典 FLOP Roofline 可能失真，应增加 instruction/SFU roof。

### Attention

不得只用固定常数。按实际 Q/K/V shape 分解：

- `QK^T` GEMM。
- scale、mask、softmax。
- `P×V` GEMM。
- 投影层。
- causal、GQA/MQA、padding、block sparse、KV cache、FlashAttention 重计算分别建模。

训练、prefill、decode 必须分开。decode 中 `M` 很小，不能沿用训练大矩阵的算术强度。

### 模型级 FLOPs

`6PT` 仅是 dense Transformer 训练的近似，不可替代精确算子建模：

- `P` 必须说明是否仅含参与本 step 的激活参数。
- `T` 是全局有效 token 数还是 padding 后 token 数必须明确。
- 长 Seq_len 注意力项、MoE 激活专家、embedding、输出头、重计算必须按需要补充。
- 推理 prefill 与 decode 分别建模。

## Bytes 计算

### 基本规则

对每个张量列出：

`Bytes = 元素数 × 每元素字节数 × 读写次数`

表格至少包含：

| 张量 | shape | dtype | 元素数 | HBM 读次数 | HBM 写次数 | Bytes |
|---|---|---:|---:|---:|---:|---:|

需要计入：

- 输入读取。
- 输出写回。
- read-modify-write。
- 中间张量的写回与再次读取。
- 权重、bias、scale、zero-point、索引、mask、稀疏元数据。
- KV cache 的读取和追加写入。
- 原子操作、workspace、spill、额外 transpose/copy。

不要默认计入：

- 寄存器内部移动。
- shared memory/L1 流量，除非分析的是对应层级 Roofline。
- 已被融合消除、且未触达目标内存层级的中间张量。

### GEMM 理想 HBM 流量

若 A、B 各从 HBM 读取一次，C 写一次：

`Q_min = s_A MK + s_B KN + s_C MN`

若读取旧 C：

`Q_min = s_A MK + s_B KN + s_C,read MN + s_C,write MN`

理想算术强度：

`I_min = 2MNK / Q_min`

这是 HBM 最小流量模型，不代表实际 traffic。小矩阵、并行切分、cache thrashing、split-K、workspace 和 layout conversion 都可能增加实际 Bytes。

### 融合

比较融合前后时，必须显式删除被消除的 HBM 中间张量读写。融合通常不显著改变主计算 FLOPs，却可降低 `Q_HBM` 并提高 `I_HBM`。

### 缓存

同一数据若命中 L2，则 HBM Bytes 可能下降但 L2 Bytes 不下降。此时分别计算：

- `I_HBM = F / Q_HBM`
- `I_L2 = F / Q_L2`

使用 Hierarchical Roofline 判断瓶颈发生在哪一层。

## 拐点判定

先计算：

- `I = F / Q`
- `I_ridge = P_compute / BW`
- `r = I / I_ridge`
- `P_achieved = F / t`
- `BW_achieved = Q / t`
- `U_compute = P_achieved / P_compute`
- `U_bw = BW_achieved / BW`
- `P_roof = min(P_compute, BW × I)`
- `U_roof = P_achieved / P_roof`

默认分区仅作启发式：

| `r = I/I_ridge` | 理论区域 |
|---:|---|
| `< 0.5` | 强 memory-side |
| `0.5–2.0` | 拐点附近 / balanced |
| `> 2.0` | 强 compute-side |

必须同时报告 `r`，不能只输出类别。`0.5` 和 `2.0` 不是物理定律，可按误差范围和测量质量调整。

### 实测结论证据

**Memory-bound** 至少满足多项：

- `r < 1`。
- 实测 DRAM/L2 throughput 接近相应可达带宽。
- compute pipe 利用率低于带宽利用率。
- 减少 Bytes、提升复用、量化或融合后性能近似按流量下降比例改善。
- 增加无关 FLOPs 在一定范围内对时间影响小。

**Compute-bound** 至少满足多项：

- `r > 1`。
- 对应精度和指令路径的 compute throughput 接近可达峰值。
- DRAM/L2 带宽没有饱和。
- 降低 FLOPs、使用低精度或更高吞吐指令后性能明显改善。
- 增加数据复用但不减少 FLOPs 时收益有限。

**Latency/overhead-bound** 常见证据：

- `U_compute` 与 `U_bw` 都低。
- Nsight Systems 显示 GPU 间歇空闲、kernel 很短或 launch gap 明显。
- 增大 workload 后吞吐显著提高。
- CUDA Graph、kernel fusion、减少 Python dispatch 后改善。

**Occupancy/dependency/instruction-bound** 常见证据：

- 两种利用率都低但 GPU 持续有 kernel。
- 寄存器/shared memory 限制 occupancy。
- warp stall 集中在 dependency、barrier、branch、instruction fetch、special-function unit。
- 非合并访存、bank conflict 或指令混合导致理论 Roofline 过于乐观。

## 标准工作流

### 第一步：定义分析边界

写清 kernel 名称、输入 shape、dtype、融合范围、分析层级和是否包含通信/launch。不同边界不能共享同一个 I。

### 第二步：稳定计时

- 预热，避免首次编译、autotune、cache 初始化。
- 使用 CUDA event、`torch.utils.benchmark` 或 `triton.testing.do_bench`。
- 异步调用前后正确同步。
- 报告中位数及 P10/P90 或其他稳定性指标。
- 同时检查 GPU 时钟、功耗和并发任务。

### 第三步：算法建模

列出 FLOPs 明细、最小 HBM Bytes 和算法 I。对复杂算子给上下界，不隐藏不确定项。

### 第四步：采集实测

- Nsight Systems：定位 CPU、launch、同步、通信和 timeline gap。
- Nsight Compute：查看 Speed of Light、Roofline、DRAM/L2 traffic、Tensor Core/compute pipe、occupancy 与 warp stall。
- PyTorch Profiler：定位 op/kernel 映射和调用关系，不把其估算 FLOPs 当成最终硬件证据。
- Triton/CUDA microbenchmark：验证 shape、dtype 和实现的持续性能。

Profiler metric 名称可能随 GPU 架构和 Nsight Compute 版本变化。优先读取报告中的语义分组，不盲目硬编码 metric 名；若直接使用 counter，必须记录版本和 counter 定义。

### 第五步：建立双 Roofline

至少计算：

- 理论 roof：datasheet `P_peak`、`BW_peak`。
- 实测 roof：同机 microbenchmark 的 `P_sustained`、`BW_sustained`。

优先基于实测 roof 做工程判断，理论 roof 作为硬上界。

### 第六步：交叉验证

设计最小扰动实验：

- 变 `M/N/K`、batch、Seq_len。
- 固定 FLOPs 改 Bytes，或固定 Bytes 改 FLOPs。
- 比较融合前后。
- 比较 dtype 或 Tensor Core 路径。
- 比较冷/热 cache。

结论必须能解释缩放趋势，不能只解释单个点。

### 第七步：给出优化上限

若降低流量到 `Q_new`：

`t_lower_bound,new = max(F/P_compute, Q_new/BW)`

理想 speedup：

`S_max = t_old / t_lower_bound,new`

若改变 FLOPs、精度或并发，同步更新所有项。任何基础输入变化后，全文重算派生值并检查旧数字残留。

## 优化映射

| 主要瓶颈 | 优先方向 |
|---|---|
| HBM/L2 bandwidth | 融合、tiling、复用、减少中间写回、量化存储、布局优化 |
| Compute | Tensor Core、降低精度、减少 FLOPs、提高指令吞吐、shape 对齐 |
| Launch/CPU overhead | CUDA Graph、`torch.compile`、persistent kernel、批处理、减少 dispatch |
| Occupancy/resource | 降寄存器压力、控制 shared memory、调整 block/warp、减少 spill |
| Dependency/SFU | 改写计算、软件流水、近似函数、增加 ILP |
| Communication | 单独建立网络 Roofline，分析 payload、链路带宽、拓扑、collective 和 overlap |

不要把以下手段绝对化：

- FP8 会降低存储 Bytes，但 compute 峰值提升可能使 `I_ridge` 右移；必须重算新 dtype 下的两边。
- batching 通常提高 GEMM 的 I，但也可能增加 KV cache 流量、排队延迟和 padding。
- FlashAttention 主要减少 HBM 中间流量，但具体 I 取决于 Seq_len、head_dim、tile、causal 和 backward 重计算。
- kernel fusion 可能减少 HBM traffic，也可能因寄存器压力、occupancy 下降而回退。

## MFU、HFU、MBU

### MFU

`MFU = 有效模型 FLOPs / (step_time × GPU_count × 对应精度单卡峰值 FLOP/s)`

- 明确使用算法 FLOPs还是实际 FLOPs。
- padding token 是否算有效 token 必须说明。
- MoE 使用激活专家对应 FLOPs，不能简单使用总参数量。
- MFU 是模型级吞吐指标，不直接证明单 kernel compute-bound。

### HFU

HFU 可将 checkpoint recompute、padding 或其他实际执行计算计入分子。报告必须写明分子定义，禁止把 HFU 标成 MFU。

### MBU

`MBU = 有效或实测 HBM Bytes / (time × GPU_count × HBM BW)`

- 必须说明 Bytes 是权重最小读取量还是 Profiler 实测流量。
- decode 中权重可能跨 token/cache 复用，不能无条件假设每 token 从 HBM 完整读取一次。
- 多请求 continuous batching、TP/PP、KV cache 和量化元数据必须纳入。

## 输出模板

每次分析按以下结构输出：

### 结论

- 判定：compute-side / memory-side / ridge-point / overhead / occupancy / inconclusive。
- 拐点距离：`r = I/I_ridge`。
- 置信度：高/中/低。
- 一句话说明主证据，区分“理论区域”与“实测瓶颈”。

### 输入与口径

| 项目 | 值 | 来源/假设 |
|---|---:|---|
| GPU / 数量 |  |  |
| dtype / 路径 |  |  |
| shape |  |  |
| kernel 边界 |  |  |
| 内存层级 |  |  |
| `P_compute` |  | theoretical / sustained |
| `BW` |  | theoretical / sustained |
| latency |  |  |

### 计算

1. FLOPs：逐项公式及总计。
2. Bytes：逐张量读写表及总计。
3. `I = F/Q`。
4. `I_ridge = P_compute/BW`。
5. `r = I/I_ridge`。
6. `P_achieved`、`BW_achieved`、`U_compute`、`U_bw`、`U_roof`。

### 证据

- Profiler counters。
- timeline 形态。
- shape/dtype/融合敏感性。
- 理论值与实测值的偏差来源。

### 优化建议

只给与瓶颈证据一致的建议，并按预计收益、实现成本和风险排序。给出理论 speedup 上限，禁止暗示可以同时吃满 compute 与 bandwidth 两个峰值。

### 缺失信息

列出会改变结论的最少补充数据，以及可直接执行的采集命令或工具步骤。

## 快速示例：GEMM

给定 BF16 GEMM `M=N=K=4096`，忽略旧 C：

- `F = 2MNK`
- `Q_min = 2MK + 2KN + 2MN`
- `I_HBM,min = F/Q_min`

将 I 与同一 GPU 的 BF16 dense Tensor Core `I_ridge` 比较。随后用 Nsight Compute 的实际 DRAM Bytes 和 kernel 时间重算实测 I 与 achieved performance。只有当计算管线接近持续峰值且带宽未饱和时，才把“compute-side 理论区域”升级为“实测 compute-bound”。

对 decode GEMM `M=1`，必须重新代入公式。不能因为它仍叫 GEMM，就沿用大方阵 GEMM 的结论。

## 失败检查

提交结论前逐项检查：

- 是否混淆 FLOP 与 FLOP/s。
- 是否混淆 GB/s 与 GiB/s。
- 是否混淆单卡与多卡总峰值。
- 是否混淆 dense 与 sparse 峰值。
- 是否混淆 BF16/FP16/TF32/FP8 峰值。
- 是否把 FMA 口径前后改成 1 FLOP。
- 是否遗漏输出写、旧输出读、中间张量、KV cache 或量化元数据。
- 是否用算法最小 Bytes 冒充实测 Bytes。
- 是否把 I 当成与实现和 shape 无关的常数。
- 是否把 `I<I_ridge` 直接写成“带宽已打满”。
- 是否忽略 overhead、occupancy、依赖、SFU、同步或通信。
- 是否在基础数据变化后保留了旧的派生数字。
