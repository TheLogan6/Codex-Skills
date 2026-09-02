# 验收与 Diff

## 1. 正确性金字塔

### L0：activation

candidate debug activation 对 framework reference 的低精度输出做 `equal`。这一级确认公式、opmath 与 storage round。

### L1：quant 输入

比较 smooth product 经 reference rounding 后的 FP32 widen 值。确认量化读到的真实输入一致。

### L2：quant statistics

逐 row 比较 amax、double scale、reciprocal；零行单独记录。

### L3：量化输出

分别比较：

- packed codes 原始字节；
- per-token scale；
- group scale 原始字节；
- shape、dtype、stride 和有效区。

### L4：consumer

候选与 reference 输出进入同一 grouped GEMM，比较 GEMM 输入契约与输出。

### L5：集成

覆盖单 block、多 chunk、多 rank、长 shape、开关 fallback 与实际 engagement。

## 2. 首差定位顺序

严格按以下顺序停止在第一处差异：

```text
input row
→ activation FP32 intermediate
→ activation storage round
→ smooth product round
→ amax
→ double scale
→ normalized values
→ group quant
→ packed codes
→ scale layout
```

首差报告包含 row/column、输入位模式、reference/candidate 中间值、ulp 或原始字节、相关 expert 与目标地址。

## 3. 常见 diff 解释

| 现象 | 优先检查 |
|---|---|
| activation 只差少量 ulp | 公式结合顺序、常量、intrinsic、FMA |
| smooth 后才分叉 | 乘法 dtype、乘前/乘后 cast |
| amax 不同 | tail mask、NaN 策略、reduction 范围 |
| scale 相同但 codes 不同 | threshold rounding、clamp、nibble 顺序 |
| codes 相同但 group scale 不同 | group reduction或 tile 地址 |
| 仅特定 expert 错 | global→local/physical expert 映射 |
| 仅 drop/tail 错 | sentinel guard、未写区比较、mask |

## 4. Bitwise 声明

合格表述：

```text
candidate 对指定的未融合 reference，在所列 dtype、activation 模式、
shape、路由和量化契约下，codes、per-token scale 与 group-scale bytes 均 equal。
```

如果只保证下游容差，应明确容差、误差统计和原因，不得称为 bitwise。改变 recipe 时必须执行模型质量门禁。

## 5. 性能验收

- 同一进程、固定输入、交错 A/B；
- warmup 后使用 GPU event，并在边界同步；
- 至少两轮，报告中位数与抖动；
- 统计删除的 activation bytes 和 launch；
- 检查 registers、shared memory、occupancy；
- 测 kernel、MoE block、layer 和 slowest rank；
- 记录 peak allocation 与总显存；
- 用 timeline 判断收益是否真实暴露。

若 kernel 快但 layer 不快，检查它是否原本被 overlap，或融合后是否延迟相邻 GEMM/通信。

## 6. 代码 Diff 审核

确认 diff 只包含：

- 新 fused kernel/helper；
- 明确的 feature gate；
- 受支持条件与 fallback；
- 测试和必要的 engagement 证据。

拒绝夹带量化常量、默认 recipe、expert 映射、并行策略或无关重构的变化。

## 7. 决策模板

```markdown
## Reference
激活公式、dtype/rounding 时间线、量化与布局契约

## Correctness
各级 gate、用例矩阵、首差或全通过证据

## Performance
字节/launch 理论值；kernel/block/layer；slowest rank；显存

## Code diff
改变与未改变的语义；fallback；支持范围

## Decision
ship / continue / stop；是否需要模型质量评估
```
