# 验收与 Diff

## 1. 定义 reference

reference 必须是待替换的完整旧链，而不是另写的“理想公式”。记录：

- 调用顺序和中间 dtype；
- reshape、contiguous、reinterpret 与 cast；
- stable ordering；
- padding 与未初始化区；
- drop 后的有效写集合。

## 2. 逐输出 bitwise gate

按以下顺序独立比较：

1. packed codes：原 dtype `equal`；
2. per-token scale：FP32 原位模式或严格 `equal`；
3. group scale：先 view 为原始整数字节，再 `equal`；
4. shape、dtype、stride；
5. 有效写集合与 sentinel 行；
6. 接入 grouped GEMM 后的输出。

报告格式：

```text
candidate 对 reference，在给定 shape、路由、expert offset 和量化契约下：
- codes: equal / 首差位置
- per-token scale: equal / 首差位置
- group scale bytes: equal / 首差位置
- GEMM output: equal 或明确容差与原因
```

不得用“数值接近”替代本应纯搬运的 bitwise gate。

## 3. 差异定位

发现 diff 时按因果顺序定位：

```text
metadata
→ source row
→ destination row
→ local expert / in-expert row
→ quant block
→ tile inner offset
→ stored byte/value
```

输出首差元素的：

- pair 编号；
- `pair_idx`、`scatter_index`；
- global/local/physical expert id；
- expert 内行号；
- 期望和实际地址；
- 期望和实际原始字节；
- 是否处于 padding 或无效区。

若差异只在洞中，先确认 consumer 是否读取；不要直接放宽整个比较。

## 4. 集成门禁

- 开关关：完整走 reference；
- 开关开且契约支持：日志或 profiler 能证明候选 engaged；
- 不支持 shape：按设计 fallback 或明确报错；
- serial 与 pipeline 路径各跑一次；
- 多 rank 比较每个 rank，不只看 rank 0；
- 多 chunk 验证 collective 顺序和结果不随 split 改变。

## 5. 性能验收

同一进程交错运行 reference/candidate：

- 固定输入和路由；
- 预热并同步；
- 至少两轮 A/B/A/B；
- 报告 p50、p95 或分位数，不只单次；
- 报告 launch 数、读写字节估算、HBM throughput；
- 同时测 kernel、MoE block、layer、slowest rank；
- 记录 peak allocated 与设备总显存。

只有候选在目标层级缩短 exposed critical path，且没有增加不可接受的显存或资源占用，才能判定性能验收通过。

## 6. 最终结论模板

```markdown
## 契约
reference、有效区、布局与支持范围

## 正确性
用例矩阵；三个输出的逐项结果；集成结果

## 性能
环境；A/B 方法；kernel/block/layer；slowest rank；显存

## Diff
代码只改变了哪些数据移动与地址计算；未改变哪些量化语义

## 决策
ship / continue / stop；fallback；已知限制
```
