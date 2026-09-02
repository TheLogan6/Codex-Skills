# 测试用例

## 数值边界矩阵

| 类别 | 必测输入 |
|---|---|
| 零 | 全零、正零/负零、单个非零 |
| 激活 | 正负小值、饱和值、拐点附近、近似公式敏感值 |
| 量化 | half-step 两侧、clamp 边界、最大有限值附近 |
| 非有限值 | NaN、`+Inf`、`-Inf`，按契约接受或拒绝 |
| dtype | 所有支持的输入与 smooth scale dtype |
| smooth | 无 scale、全一、极小/极大、正负混合 |
| shape | 空、单行、tail row、hidden 非整 tile、生产大 shape |
| 路由 | 顺序、随机、drop、空 expert、热点 expert、非零 offset |

## 用例 A：activation 首边界

单独比较：

1. framework activation 的低精度输出；
2. 融合 kernel 在量化前显式导出的 debug activation。

若此处不等，不再检查量化。对首差值打印输入、FP32 中间值、低精度位模式和公式分支。

## 用例 B：smooth product 边界

固定 activation 输出，分别验证：

- 低精度乘法后 widen；
- FP32 乘法；
- 无 smooth scale。

测试应包含能让两种乘法跨越 NVFP4 threshold 的构造值，确保能抓到漏掉的 round。

## 用例 C：zero row

全零输入验证：

- amax 为零；
- fallback scale 与 reference 相同；
- 不产生 NaN/Inf；
- codes、per-token scale、group scale 全部一致。

## 用例 D：quant threshold

围绕每个可表示 FP4 值的中点构造 `nextafter` 两侧输入，验证 round、clamp、符号和 nibble packing。

## 用例 E：tail 与 mask

hidden 不是 program block size 的整数倍。将 masked 区域视作极大 canary，确认其不参与 amax、不写 codes/scales 越界。

## 用例 F：路由与布局

使用非单调 scatter、非零 expert offset、空 expert、热点 expert 和跨 tile_m 边界的 expert 行数。逐项比较 scale slot 与 tiled 地址。

## 用例 G：drop

设置 sentinel 行，验证：

- 不读取无效 activation；
- 不写任一输出；
- 有效行保持一致；
- 预填 canary 未变化。

## 用例 H：随机与真实分布

固定 seed 覆盖：

- 均匀、正偏、长尾、大动态范围；
- 多个 shape 与路由；
- 至少一个生产规模。

失败时缩减为最小复现，但保留原 seed、shape、首差索引和输入位模式。

## 集成用例

1. 未融合 activation+quant 对融合输出；
2. 两者分别进入同一 grouped GEMM；
3. 单 MoE block；
4. 多 chunk 与多 rank；
5. feature flag 开/关及 unsupported fallback；
6. 长 shape 显存峰值。
