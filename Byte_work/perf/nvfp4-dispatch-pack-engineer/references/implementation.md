# 实现方法

## 1. 先冻结接口

候选接口应显式接收：

- global quantized payload 与 auxiliary scale；
- 源行 `pair_idx`；
- 目标 `scatter_index`；
- expert 内行号与 expert id；
- quant-block 前缀；
- hidden size、local expert 数、expert offset；
- 可选的预分配输出，供确定性测试与内存复用。

禁止从全局状态猜 shape、top-k 或 expert offset。

## 2. 推荐 program 粒度

以“一条 routed pair 一个 program”为起点：

```python
m = program_id(0)
dst = load(scatter_index + m)
if dst != DROP:
    src = load(pair_idx + m)
    # load one payload row
    # write codes, per-token scale, tiled group scale
```

优点是 metadata 标量只读一次、row-local、容易证明无冲突。若 hidden 很大导致寄存器压力，再考虑二维 program 或分段，但先保持语义简单。

## 3. 地址实现顺序

1. 使用足够宽的地址类型计算 `src * payload_width` 与 `dst * code_width`。
2. codes 使用原 dtype 原样搬运，尾部用 `c < code_width` mask。
3. auxiliary scale 写入 `(local_expert, in_expert_row)`。
4. group scale 以原始字节读取；按 consumer 的 K block 和 tile-inner 公式写入。
5. K 非整 tile 时对 block 维和元素维分别 mask。
6. sentinel 分支必须包围所有输入读取和输出写入。

## 4. group-scale 布局

不要“重新设计更直观的布局”。从 reference 的 layout-builder 复制并解释每一项：

```text
block_m = in_expert_row // tile_m
row_in_block = in_expert_row % tile_m
block_base = quant_block_cumsum[local_expert] + block_m
scale_block = block_base * k_block_count + block_k
inner = swizzle(row_in_block, scale_lane)
```

将公式写成注释和独立 helper；测试中用小 shape 手算至少一个地址。

## 5. 分配与初始化

- codes 仅在有效目标行定义时可用 `empty`；
- per-token scale 若 consumer 会读 padding，应初始化为零；
- tiled scale 若存在洞，生产路径要证明 consumer 不读，测试则确定性预填；
- 优先支持 caller-provided buffers，减少 allocator 干扰并便于 diff。

## 6. fallback 与集成

保持未融合链路：

```python
if enabled and supported_contract:
    outputs = fused_pack(...)
else:
    outputs = reference_chain(...)
```

`supported_contract` 至少检查 top-k、payload width、group size、hidden 对齐、index dtype、expert id 范围。对不支持输入明确 fallback 或报错，不得静默产生近似布局。

## 7. 性能优化顺序

1. 删除中间 gather/slice/scatter；
2. 删除 int64 索引 materialization；
3. 合并 metadata 标量读取；
4. 调整 block size 与 num warps；
5. 检查寄存器、occupancy、HBM throughput；
6. 再考虑异步加载或二维切分。

每次只改变一个机制，并保留对应 correctness gate。理论收益应以减少的 read/write 字节和 launch 数估算，不能只看 kernel 名称。
