# 实现方法

## 1. 冻结语义接口

接口至少显式包含：

- producer output；
- 可选 smooth scale；
- expert id、scatter index、expert 内行号；
- quant-block prefix 与 expert offset；
- hidden size；
- `match_reference` 或等价的明确模式；
- 可选预分配输出。

输出通常为 packed codes、per-token scale、tiled group scale。每个输出都要声明 shape、dtype、有效区与 padding。

## 2. 复现 activation

用独立 device helper 写 reference 公式，保持：

- 常量值和精度；
- 乘加与括号顺序；
- tanh/erf/exp 等 intrinsic；
- opmath dtype；
- reference 输出 storage dtype 的显式 round。

示意：

```python
x32 = x.to(fp32)
y32 = activation_reference_order(x32)
y_storage = y32.to(reference_storage_dtype)
```

不要依赖编译器“自然产生相同舍入”。

## 3. 复现 smooth 边界

根据旧链选择：

```python
# 常见 bitwise 模式
y_low = y32.to(low_precision)
product_low = y_low * smooth_low
quant_input = product_low.to(fp32)
```

这与先转 FP32 再乘通常不等价。没有 smooth scale 时，也要确认 quant kernel 读取低精度 storage 后的 widen 行为。

## 4. 动态 scale

对每个有效 row：

1. masked load，tail 的 `other` 不得影响 amax；
2. `amax = max(abs(value))`；
3. 按 reference 常量和顺序计算 double scale；
4. 明确 `amax == 0` 的 fallback；
5. 计算 reciprocal 和 normalize；
6. 调用唯一的 NVFP4 quant helper，避免复制出第二套 recipe。

NaN/Inf 策略必须与 reference 一致；若 reference 未定义，使用 guard 明确拒绝。

## 5. 三类输出

- codes：按目标 row 写 packed nibble，尾部 mask；
- per-token scale：按 `(local_expert, in_expert_row)` 写 FP32；
- group scale：按 quant block、K block 和 tile swizzle 写原 scale dtype。

地址公式应与 consumer 的 layout builder 同源，避免“看起来等价”的新公式。

## 6. 分支与 fallback

推荐：

```python
if enabled and supported:
    fused(..., match_reference=True)
else:
    activation_then_quant(...)
```

`supported` 检查 activation 类型、近似模式、dtype、group size、hidden 对齐、top-k、index dtype 与 layout version。未支持组合不允许静默进入近似分支。

## 7. 优化顺序

1. 先做一 row/program 的正确版本；
2. 删除 activation 中间 tensor；
3. 复用量化 helper；
4. 调整 block size、warps 与 reduction；
5. 检查寄存器和 occupancy；
6. 仅在 trace 证明必要时尝试多 program/row 或与 GEMM epilogue 融合。

将其融入 GEMM epilogue 前，额外证明跨 CTA completion、写可见性、资源增量和调度收益；standalone 快不能作为依据。
