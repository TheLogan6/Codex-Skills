# 测试用例

## 最小功能矩阵

| 维度 | 必测取值 |
|---|---|
| pair 数 | `0`、`1`、小于 expert 数、常规、大规模 |
| hidden | 标准值、不同合法值、K tile 的 ragged tail |
| expert 分布 | 均匀、单 expert 热点、长尾、空 expert |
| expert id | offset 为零、非零、存在 logical→physical remap |
| 路由 | 顺序、随机、重复源行、稳定 arrival order |
| drop | 无 drop、单个 sentinel、随机 drop、全部 drop |
| chunk | 单 chunk、非整尾 chunk、多种 split |
| buffer | 默认分配、预分配、非零预填 |

## 用例 A：手算小布局

使用少量 pairs、两个本地 experts 和很小的合法 K，固定：

- `pair_idx` 为非单调排列；
- `scatter_index` 为另一组排列；
- 每个源行填充不同字节模式；
- auxiliary scale 为可辨识值。

逐行断言源→目标映射，并手算一个 per-token slot 和一个 group-scale tile 地址。此用例主要抓错索引和错 swizzle。

## 用例 B：重复读取、唯一写入

允许多个 pair 读取同一 payload 行，但写到不同 expert-major 行。验证 kernel 没有错误假设 `pair_idx` 唯一。

## 用例 C：drop 与洞

插入 sentinel：

- 验证 sentinel program 不访问越界源；
- codes 只比较已写目标行；
- scale 输出使用相同预填后全缓冲比较；
- 使用 guard/canary 验证未写区未被污染。

## 用例 D：empty expert 与热点 expert

分别构造：

- pair 数小于 expert 数；
- 所有 pair 落到一个 expert；
- 每个 expert 的行数跨越 tile_m 边界。

验证 `quant_block_cumsum`、padding 和 block 计数公式。

## 用例 E：非零 offset 与 remap

输入 global expert id，使用非零 rank offset；再增加一个 physical slot permutation。验证本地化顺序正确，且不会用 global id 直接索引本地 buffer。

## 用例 F：大规模与索引宽度

构造足以暴露 32 位乘法溢出的逻辑尺寸或地址计算测试。即使 tensor 实际无法分配，也应对 host 端 shape guard 和地址类型进行单元检查。

## 用例 G：split invariance

同一全局输入分别按一种和多种 chunk 划分，拼接逻辑结果后比较。所有 row-local 输出应一致；若目标布局依赖全局 prefix，必须使用相同全局 metadata。

## 回归组合

每次修复至少保留：

1. 触发原 bug 的最小 deterministic case；
2. 一个正常生产形状；
3. 一个 ragged tail；
4. 一个 skew routing；
5. 一个 sentinel；
6. 一个非零 expert offset。

随机 fuzz 应固定 seed，并在失败信息中打印完整 shape、索引摘要和首个差异位置。
