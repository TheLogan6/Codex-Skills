# 代码分析

## 1. 建立数值时间线

不要只写“activation 后量化”。把 reference 展开为精确时间线：

```text
input storage dtype
→ widen/opmath dtype
→ activation 公式与求值顺序
→ activation output storage round
→ smooth multiply 的两个输入 dtype
→ smooth product round/widen
→ row amax reduction
→ double scale 与 zero fallback
→ normalize
→ group quant / scale
→ nibble pack 与 scale layout
```

每个箭头都标注 dtype、shape、是否 materialize、是否改变位模式。

## 2. 查真实 reference

依次检查：

1. 调用处传入的 activation 参数，例如近似模式；
2. 框架 kernel 的 opmath dtype 和表达式结合顺序；
3. activation 输出 tensor 的 storage dtype；
4. smooth scale 的 dtype 与广播方式；
5. quant helper 的 amax、scale、clamp、round、pack；
6. grouped GEMM 对 scale 布局的消费方式。

数学上等价的公式可能因常量精度、FMA、括号或中间舍入产生不同 ulp，进而跨过量化阈值。

## 3. 识别融合收益

典型未融合链：

```text
producer output
→ activation kernel 读写完整低精度 tensor
→ quant kernel 再读该 tensor
→ codes + scales
```

主要收益来自删除 activation 中间 tensor 的完整写回与重读，并减少一次 launch。先估算：

```text
saved_bytes ≈ rows * hidden * sizeof(activation_dtype) * 2
```

若 activation 已与上游 GEMM epilogue 融合或被 overlap，继续融合未必降低 exposed latency。

## 4. 路由与布局

在 MoE 中，一个 program 常对应 routed pair：

- `scatter_index` 找到 expert-major activation 行；
- global expert id 减 offset 得到 local expert；
- expert 内行号决定 per-token scale slot；
- quant-block prefix 与行号决定 group-scale tile。

检查 drop sentinel、expert remap、top-k 展平顺序和目标行唯一性。

## 5. 两种目标必须分开

### A. Bitwise-preserving fusion

显式复现旧链中所有 rounding boundary，目标是 codes 与 scales 原位模式一致。

### B. New recipe fusion

允许保留更高精度或改变公式，但必须：

- 改名并明确语义；
- 不使用“bitwise 替换”措辞；
- 增加误差统计、下游输出和模型质量门禁；
- 与旧 recipe 做可回滚 A/B。

不得用 B 的结果替代 A 的验收。

## 6. 资源分析

记录每个 program：

- 加载的 hidden 元素数；
- reduction 宽度；
- registers/thread；
- shared memory；
- warps 与 occupancy；
- 是否与相邻 GEMM/通信 co-reside。

大 hidden 的单 program 实现可能因寄存器压力抵消内存收益；先从简单实现验证正确性，再按 trace 调整分块。
