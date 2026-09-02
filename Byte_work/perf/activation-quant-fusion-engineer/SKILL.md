---
name: activation-quant-fusion-engineer
description: 分析、实现并验收 activation+quant 融合算子。遇到 GELU/SiLU/门控与低比特动态量化融合、rounding 边界复现、Triton 开发或数值 diff 时调用。
---

# Activation-Quant Fusion Engineer

面向 activation→quantization 之间的大中间张量消除：先复原 reference 的浮点求值顺序、dtype 截断和 scale 布局，再编写融合 kernel，并通过逐级 diff、性能和集成门禁验收。

## 接受的输入

- 未融合 activation 与 quant 调用链；
- 输入、smooth scale、路由 metadata 和输出布局；
- 激活类型及近似模式；
- 量化格式、group size、scale dtype、packing 规则；
- 候选 Triton/CUDA kernel、失败样例或 profiler trace。

缺少 reference 时先定位真实框架实现与调用参数，不能把数学公式当作位级 reference。

## 强制工作流

1. 阅读 [references/code-analysis.md](references/code-analysis.md)，建立数值时间线。
2. 标注每次 widen、运算、round、cast、amax reduction、scale 计算和 packing。
3. 区分“保持旧链 bitwise”和“采用新量化 recipe”两类任务。
4. 按 [references/implementation.md](references/implementation.md) 写最小融合 kernel，保留 fallback 和匹配模式。
5. 按 [references/cases.md](references/cases.md) 覆盖零、极值、阈值、tail、drop、smooth scale 与路由。
6. 按 [references/validation-and-diff.md](references/validation-and-diff.md) 从 activation 边界向 codes/scales 逐级定位首差。
7. 正确性通过后做同 session A/B，并确认整 block/layer 的 exposed 时间下降。

## 核心不变量

- 激活函数的公式、常量精度与结合顺序必须匹配 reference。
- 若旧链把 activation 写成低精度再由 quant 读取，融合 kernel 必须显式复现该 rounding boundary。
- smooth multiply 的输入 dtype、运算 dtype 和结果 dtype必须匹配旧链。
- `amax==0` 的 scale fallback 必须一致，避免除零和 NaN。
- reduction 范围只覆盖有效 hidden 元素；masked tail 不能污染 amax。
- codes 的 nibble 顺序、per-token scale 与 tiled group-scale 地址不得改变。
- dropped rows 不得写；唯一 writer 和 expert 本地化必须可证明。
- “bitwise”只能描述明确的 candidate/reference、shape 和输出。

## 输出要求

每次任务至少交付：

- reference 数值时间线和数据布局表；
- 融合边界选择及理论节省的字节/launch；
- 最小实现 diff 与 fallback 条件；
- activation、smooth product、amax、scale、codes、group scale 的逐级 diff；
- 特殊用例、集成与性能结果；
- 是否保持旧 recipe、是否需要模型质量门禁的结论。

## 停止条件

以下任一项未解释时不得宣称完成：

- activation 边界已出现首差；
- 只比较反量化结果，未比较 codes/scales；
- 量化 recipe 或 accumulation order 已改变但仍宣称 bitwise；
- 候选路径未实际 engaged；
- microkernel 变快但资源占用使上游 GEMM 或通信 overlap 变差；
- 非整 tile、zero row、drop 或非零 expert offset 未覆盖。
