# 代码分析

## 1. 从 consumer 反推契约

先定位 grouped GEMM 调用，记录它真正消费的三个对象：

| 输出 | 常见逻辑形状 | 关键问题 |
|---|---|---|
| packed codes | `[pairs, K/2]` 或带 top-k 维 | 两个 FP4 值的 nibble 顺序、目标行顺序 |
| per-token scale | `[local_experts, padded_pairs]` | expert 偏移、expert 内行号、padding |
| tiled group scale | `[M_blocks, K_blocks, tile_m, tile_k]` | block 累加偏移、tile 内 swizzle、原始字节类型 |

不要从函数名推断布局。沿 consumer 的地址公式、stride 和 dtype 反向确认。

## 2. 还原 reference 链

将旧实现拆成纯语义步骤：

```text
source_row = global_payload[pair_idx[m]]
codes = source_row[:code_width]
flat_group_scale = reinterpret(source_row[code_width:])
dst = scatter_index[m]
expert_major_codes[dst] = codes
per_token_scale[local_expert, in_expert_row] = global_aux[pair_idx[m]]
tiled_group_scale[tile_address(...)] = flat_group_scale
```

若 `gather` 后紧接 `scatter`，通常可合成为一次源地址读取和一次目标地址写入。判断能否融合时，逐步回答：

1. 中间张量是否还有其他消费者；
2. 两次置换是否可由 metadata 直接组合；
3. 是否存在重复目标行；
4. 未写区域是否有可观察语义；
5. dtype 转换是数值 cast 还是 bit reinterpret；
6. 旧链是否隐含稳定排序、arrival order 或 padding 规则。

## 3. 索引语义审计

为每个索引建立最小样例并手算：

- `pair_idx`：接收 pair 到全局通信 payload 行；
- `scatter_index`：pair 到本地 expert-major 行，sentinel 表示无效；
- `in_expert_index`：pair 在本地 expert 内的行；
- `expert_id`：确认是 global、rank-local 还是 physical slot；
- `quant_block_cumsum`：每个本地 expert 在 scale tile 池中的 block 起点。

验证等式：

```text
local_expert = global_expert - expert_offset
dst_row = expert_prefix[local_expert] + in_expert_index
quant_block = quant_block_cumsum[local_expert] + in_expert_index // tile_m
```

若存在 expert remap，先应用 logical→physical 映射，再计算本地地址。

## 4. 写集合与所有权

分别列出每个输出的 write set：

- codes：通常由 `dst_row` 唯一决定；
- per-token scale：由 `(local_expert, in_expert_index)` 唯一决定；
- group scale：由 `(quant_block, k_block, tile_inner)` 唯一决定。

证明 live pair 间无写冲突。若 reference 对 drop 后的洞保持未初始化，则测试不能直接比较这些洞；应比较有效写集合，或两侧使用相同预填值。

## 5. 调用链与 engagement

检查以下位置：

1. feature flag 的读取时机；
2. deferred payload 是否会被意外提前 materialize；
3. top-k、quant mode、EP size 的 guard；
4. fallback 是否保持旧行为；
5. 实际 kernel 分支是否有一次性日志、计数器或 profiler 证据；
6. serial、pipeline、persistent 路径是否共享或绕过该实现。

最终形成“条件→路径”矩阵，避免开关 silent no-op。
