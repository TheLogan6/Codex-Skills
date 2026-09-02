---
name: nvfp4-dispatch-pack-engineer
description: 分析、实现并验收 NVFP4 MoE dispatch-pack 算子。遇到量化通信载荷到 expert-major GEMM 布局的融合、重排、Triton 优化或 bitwise diff 时调用。
---

# NVFP4 Dispatch-Pack Engineer

面向 MoE expert-parallel dispatch 输入侧：把量化通信载荷、路由元数据与目标 GEMM 布局作为一个整体分析，设计一次读取、直接写终态的 pack 算子，并用逐输出 diff 证明替换安全。

## 接受的输入

- dispatch 前后张量的 shape、dtype、stride 和布局说明；
- reference 链路与候选 kernel；
- `pair_idx`、`scatter_index`、expert id、expert 内行号等路由元数据；
- NVFP4 codes、per-token scale、group scale 的量化约定；
- grouped GEMM 对 codes/scales 的最终布局要求；
- 测试、trace、benchmark 或错误样例。

信息不全时，先从调用链恢复契约，不猜测索引语义或 scale 布局。

## 强制工作流

1. 阅读 [references/code-analysis.md](references/code-analysis.md)，画出 producer→metadata→pack→GEMM 数据流。
2. 为每个输入和输出建立契约表：逻辑含义、shape、dtype、stride、所有者、有效区、padding、哨兵值。
3. 写出 reference 的逐步等式，证明哪些步骤只是置换或布局转换。
4. 按 [references/implementation.md](references/implementation.md) 实现最小候选，保留可切换 fallback。
5. 按 [references/cases.md](references/cases.md) 覆盖正常、tail、empty、drop、偏移和极端路由。
6. 按 [references/validation-and-diff.md](references/validation-and-diff.md) 分别比较 codes、per-token scale、group scale 的原始位模式。
7. 正确性门禁全过后再做同 session A/B；最后验证调用路径确实 engaged。

## 核心不变量

- `pair_idx[m]` 只描述源通信行；`scatter_index[m]` 只描述 expert-major 目标行。
- 全局 expert id 必须在地址计算前转换为本地 physical expert id。
- `-1` 或其他 drop sentinel 不得读源、不得写目标。
- 一个 live pair 对每个目标区域必须有唯一 writer；若不能证明，必须引入冲突消解。
- codes 按原始字节搬运；scale 的 dtype reinterpret 与数值 cast 不可混用。
- group-scale tile 地址必须逐项复现 consumer 约定。
- padding/未写区域不能被误当有效数据；全缓冲比较时需确定性预填。
- chunk 切分不能改变 row-local 量化与路由语义。

## 输出要求

每次任务至少交付：

- 数据流与契约表；
- reference→candidate 对应关系；
- 最小代码 diff；
- 分层正确性结果，明确 reference、shape 与比较方式；
- 性能结果，含 warmup、迭代、slowest rank 和显存；
- 风险、fallback 与是否可上线的结论。

不得只报告“bitwise 通过”或“更快”；必须说明比较了什么、在哪些条件下、为何可比。

## 停止条件

出现以下任一情况时停止推进性能结论并先修正：

- feature 开关未能证明实际进入候选路径；
- reference 与 candidate 的有效区定义不一致；
- 路由元数据来源或本地 expert 映射不明确；
- 任一 codes/scales 输出存在未解释 diff；
- benchmark 同时改变了量化算法、布局、shape 或调度；
- 单 kernel 加速未转化为 block/layer 收益且 trace 显示其原本被 overlap。
