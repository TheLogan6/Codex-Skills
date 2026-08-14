# AI Infra 推理加速 Skills 集合

> 面向 **大厂 AI Infra / 推理服务加速** 工程师的高质量 Agent Skills 精选合集。
> 覆盖 **推理框架 · Kernel 优化 · 量化压缩 · 分布式并行** 全栈。

所有 skill 均来自 [Orchestra Research AI-Research-SKILLs](https://github.com/Orchestra-Research/AI-Research-SKILLs) (11.7k⭐, MIT 协议)，遵循 [Agent Skills 标准](https://agentskills.io)，兼容 Claude Code、Codex、OpenCode、Cursor 等主流 coding agent。

---

## 目录总览

| # | Skill | 核心能力 | 应用场景 | 难度 |
|---|-------|---------|---------|------|
| 1 | [`vllm`](./vllm) | PagedAttention + 连续批处理 | 高吞吐生产 API | ⭐⭐⭐ |
| 2 | [`sglang`](./sglang) | RadixAttention + 结构化生成 | Agent/多轮/JSON 场景 | ⭐⭐⭐⭐ |
| 3 | [`tensorrt-llm`](./tensorrt-llm) | NVIDIA 编译式推理 | H100 极限性能 | ⭐⭐⭐⭐⭐ |
| 4 | [`flash-attention`](./flash-attention) | IO-aware attention kernel | 长序列 + 显存优化 | ⭐⭐⭐⭐ |
| 5 | [`awq`](./awq) | Activation-aware 4-bit 量化 | 生产部署量化 | ⭐⭐⭐ |
| 6 | [`bitsandbytes`](./bitsandbytes) | 8-bit/4-bit + QLoRA | HF 生态量化 | ⭐⭐ |
| 7 | [`megatron-core`](./megatron-core) | TP/PP/SP/CP/EP 多维并行 | 千亿模型训练/推理 | ⭐⭐⭐⭐⭐ |
| 8 | [`deepspeed`](./deepspeed) | ZeRO 1/2/3 + MoE | 大模型训练 | ⭐⭐⭐⭐ |
| 9 | [`pytorch-fsdp2`](./pytorch-fsdp2) | DTensor 分片 (fully_shard) | 现代 FSDP 迁移 | ⭐⭐⭐ |
| 10 | [`torchtitan`](./torchtitan) | PyTorch 官方 4D 并行 | Float8 + torch.compile 前沿 | ⭐⭐⭐⭐ |

---

## 技术栈全景图

```
┌─────────────────────────────────────────────────────────────────┐
│                    推理请求 (Request)                            │
└────────────────────────┬────────────────────────────────────────┘
                         ▼
┌─────────────────────────────────────────────────────────────────┐
│  推理服务层 (Serving Layer)                                       │
│  ┌────────┐  ┌─────────┐  ┌──────────────┐                     │
│  │ vLLM   │  │ SGLang  │  │ TensorRT-LLM │                     │
│  └────────┘  └─────────┘  └──────────────┘                     │
│      ▲            ▲              ▲                              │
│      │  PagedAttn │ RadixAttn    │ In-Flight Batching          │
└──────┼────────────┼──────────────┼──────────────────────────────┘
       │            │              │
┌──────┴────────────┴──────────────┴──────────────────────────────┐
│  Kernel & 量化层 (Kernel & Quantization)                         │
│  ┌───────────────────┐  ┌──────┐  ┌──────────────┐             │
│  │ Flash Attention   │  │ AWQ  │  │ bitsandbytes │             │
│  └───────────────────┘  └──────┘  └──────────────┘             │
│    (IO-aware kernel)   (Marlin)   (NF4 QLoRA)                  │
└─────────────────────────────────────────────────────────────────┘
                         ▲
┌────────────────────────┴────────────────────────────────────────┐
│  分布式 & 并行层 (Distributed & Parallelism)                     │
│  ┌──────────────┐ ┌──────────┐ ┌────────────┐ ┌────────────┐  │
│  │Megatron-Core │ │DeepSpeed │ │PyTorch FSDP│ │ TorchTitan │  │
│  │ TP/PP/SP/CP/EP│ │ ZeRO/MoE │ │  (DTensor) │ │  (4D+FP8)  │  │
│  └──────────────┘ └──────────┘ └────────────┘ └────────────┘  │
└─────────────────────────────────────────────────────────────────┘
                         ▲
┌────────────────────────┴────────────────────────────────────────┐
│              硬件层 (NVIDIA H100/A100 GPU)                       │
└─────────────────────────────────────────────────────────────────┘
```

---

## 三大推理框架选型决策树

```
                需要哪种推理框架?
                       │
        ┌──────────────┼───────────────┐
        │              │               │
   高吞吐生产      结构化输出/      NVIDIA 极限
   API 部署?        Agent 场景?       性能?
        │              │               │
        ▼              ▼               ▼
     [vLLM]        [SGLang]      [TensorRT-LLM]
   • PagedAttn    • RadixAttn     • FP8/INT4 编译
   • 广泛验证     • 前缀共享 3-5x  • H100 最快
   • OpenAI API   • JSON/工具调用  • 复杂 workflow
   • Python 友好  • Agent workflow • 部署门槛高
```

**通用建议**：先用 vLLM 快速上线 → 有 Agent/前缀重叠场景切 SGLang → 极限性能榨取切 TensorRT-LLM。

---

## 各 Skill 详细说明

### 【推理服务框架】

### 1. vllm —— PagedAttention 高吞吐推理

**24× 高于原生 transformers 的吞吐量**，通过 PagedAttention（块状 KV 缓存）+ 连续批处理（混跑 prefill/decode）实现。

- **PagedAttention**：仿 OS 虚拟内存的 KV cache 管理，消除内存碎片，支持 prefix caching
- **连续批处理 (Continuous Batching)**：单条请求生成完立即插入新请求，GPU 永不空转
- **OpenAI 兼容 API**：`vllm serve model-name` 一行起服务
- **量化支持**：GPTQ / AWQ / FP8
- **Tensor Parallelism**：多 GPU 支持 70B/405B 大模型

**核心工作流**：`生产 API 部署 → 张量并行配置 → 量化模型加载 → 性能调优`

**适用场景**：LLM API 生产化上线；需要 OpenAI 兼容接口；显存受限想跑更大模型。

---

### 2. sglang —— RadixAttention + 结构化生成

**xAI / AMD / NVIDIA / LinkedIn 部署超 30 万 GPU**，比 vLLM 快 5× (前缀重叠场景)。

- **RadixAttention**：自动前缀树缓存，多轮对话/工具调用零重复计算
- **结构化生成**：JSON / 正则 / 语法约束的高速解码（3× 快于常规）
- **Agent 原生**：函数调用、多轮对话、共享 system prompt 场景 first-class 支持
- **FlashInfer 后端**：融合 attention kernel，比 FlashAttention 更快
- **DeepSeek-V3 / Llama 4 原厂推荐**

**核心工作流**：`launch_server → 前缀缓存开启 → 结构化 schema 定义 → tool_call 集成`

**适用场景**：Agent workflows；JSON/结构化输出高频调用；长共享上下文（system prompt 很长）；多轮对话服务。

---

### 3. tensorrt-llm —— NVIDIA 编译式推理天花板

**Llama 3 24,000+ tokens/sec on H100**，10-100× 快于 PyTorch。

- **AOT 编译**：模型编译到 TensorRT engine，消除 Python overhead
- **量化组合**：FP8 / INT4 / FP4，配合 SmoothQuant / AWQ
- **In-Flight Batching**：动态请求调度，等价于连续批处理
- **多 GPU 缩放**：TP + PP，支持 GB200 集群
- **Triton Inference Server 集成**：完整生产链路

**核心工作流**：`TRT 编译 → engine 部署 → Triton 服务 → FP8 精度调校`

**适用场景**：NVIDIA H100/GB200 极限性能榨取；延迟敏感的实时业务；已在 CUDA 生态深耕的团队。

---

### 【Kernel & 量化】

### 4. flash-attention —— IO-aware Attention Kernel

**2-4× 提速 + 10-20× 显存减少**，长序列 Transformer 的救星，也是**并行算子的教科书**。

- **IO-aware 算法**：分块 tiling + 反向传播 recomputation，避免 O(N²) 中间矩阵在 HBM 上落地
- **PyTorch native SDPA**：`F.scaled_dot_product_attention` 自动调用（PyTorch 2.2+）
- **flash-attn 库**：更多 features（sliding window / ALiBi / block sparse）
- **H100 FP8**：FP8 attention 支持
- **Triton 版本**：可读性好的参考实现

**核心工作流**：`native SDPA 优先 → flash-attn lib → Triton 自定义 → CUDA hand-tune`

**适用场景**：写并行算子必学；长序列训练/推理显存瓶颈；对 attention pattern（causal / sliding window / block-sparse）有定制需求。

---

### 5. awq —— MLSys 2024 Best Paper 量化

**Activation-aware 4-bit 量化**，3× 提速 + <5% 精度损失，Marlin kernel 加持。

- **激活感知**：基于 activation magnitude 保留 salient 权重（1% 权重承载 99% 效果）
- **无需梯度**：Post-training 量化，无需重新训练
- **vLLM 原生支持**：`vllm serve --quantization awq`
- **Marlin kernels**：Ampere+ GPU (A100/H100/RTX40x) 2× 快于普通 4-bit
- **对 instruction-tuned 泛化好**：Chat/Instruct 模型精度保留优秀

**核心工作流**：`AutoAWQ 校准 → 保存量化权重 → vLLM 加载 → 精度 vs 速度评估`

**适用场景**：生产环境 4-bit 部署；Chat 模型量化；vLLM 部署栈；Ampere+ GPU 硬件。

---

### 6. bitsandbytes —— HF 生态量化事实标准

**50% (8-bit) / 75% (4-bit) 显存减少**，<1% 精度损失，无需校准数据。

- **零门槛**：`load_in_4bit=True` 一行接入
- **NF4 / FP4 / INT8**：NF4 是 QLoRA 论文推荐格式
- **QLoRA 训练支持**：量化 base model + LoRA 全量精度训练
- **8-bit 优化器**：Adam8bit 减少 optimizer state 显存
- **HuggingFace 深度集成**：`BitsAndBytesConfig` 与 `transformers` / `accelerate` / `PEFT` 无缝

**核心工作流**：`BitsAndBytesConfig 配置 → transformers 加载 → PEFT LoRA 微调`

**适用场景**：快速试验/POC；QLoRA 训练；不想搞校准的场景；HuggingFace 用户。

---

### 【分布式 & 并行】

### 7. megatron-core —— NVIDIA 多维并行圣经

**训练 2B-462B 模型，H100 MFU 47%**，Nemotron / LLaMA / DeepSeek 的底座。**开发并行算子必参**。

- **5D 并行**：
  - **TP (Tensor Parallelism)**: 权重按行/列切分，通过 all-reduce 通信
  - **PP (Pipeline Parallelism)**: 层间切分 + 1F1B / interleaved 调度
  - **SP (Sequence Parallelism)**: LayerNorm / Dropout 沿序列切
  - **CP (Context Parallelism)**: 长序列注意力沿序列切
  - **EP (Expert Parallelism)**: MoE experts 分布到不同 GPU
- **Transformer Engine 集成**：FP8 训练
- **Megatron-LM 生产脚本**：可直接跑 LLaMA-3 8B/70B / DeepSeek

**核心工作流**：`3D 并行配置 → 通信拓扑设计 → 微 batch 调度 → FP8 训练`

**适用场景**：千亿模型训练；开发自己的 TP/PP 并行算子（可参考实现）；MoE 系统设计；NVIDIA 生态。

---

### 8. deepspeed —— Microsoft ZeRO 全家桶

**ZeRO 1/2/3 分片优化 + MoE + DeepNVMe + 1-bit Adam**，工业级大规模训练框架。

- **ZeRO 三阶段**：
  - Stage 1: 优化器状态分片
  - Stage 2: + 梯度分片
  - Stage 3: + 参数分片（等价 FSDP）
- **ZeRO-Offload / Infinity**：显存不够用 CPU / NVMe 顶
- **DeepNVMe**：SSD 直读 tensor，绕过 PCIe 瓶颈
- **MoE 支持**：PR-MoE、专家并行、MoS 蒸馏
- **1-bit Adam / 1-bit LAMB**：通信压缩 5×

**核心工作流**：`ZeRO stage 选型 → offload 策略 → MoE 配置 → 通信压缩`

**适用场景**：ZeRO-3 大模型训练；MoE 训练；显存不够想 offload；已有 DeepSpeed 生产栈。

---

### 9. pytorch-fsdp2 —— DTensor 现代分片

**PyTorch 2.4+ 官方推荐**，基于 DTensor + DeviceMesh 的**每参数分片**。

- **fully_shard() API**：替代 FSDP1 的 `FullyShardedDataParallel` 包装
- **DTensor**：分片元数据显式建模，可 inspect / 可组合
- **DeviceMesh**：多维网格拓扑，DP × TP 组合无缝
- **Distributed Checkpointing (DCP)**：sharded state dict，加载/保存高效
- **Mixed Precision + Offload**：per-module 细粒度控制

**核心工作流**：`DeviceMesh 定义 → fully_shard 应用 → MixedPrecisionPolicy → DCP checkpoint`

**适用场景**：新项目起步（不要用 FSDP1）；DP + TP 组合；模型无法单卡放下；需要现代 checkpoint 格式。

---

### 10. torchtitan —— PyTorch 官方 4D 并行前沿

**PyTorch 官方大模型预训练平台**，H100 上 65%+ 加速，Float8 + torch.compile 生产级组合。

- **4D 并行**：FSDP2 + TP + PP + CP 可组合
- **Float8 训练**：torchao FP8 recipe，接近 BF16 精度、更快
- **torch.compile 深度集成**：算子融合、graph capture
- **模型库**：Llama 3.1 / DeepSeek V3 / 自定义
- **Distributed Checkpointing**：DCP async save

**核心工作流**：`config toml 定义 → 4D mesh 配置 → torch.compile 编译 → Float8 训练`

**适用场景**：PyTorch native 栈的大模型预训练；想上 Float8 + torch.compile 组合；DeepSeek V3 / Llama 3 训练；不想上 Megatron 的复杂度。

---

## 推荐工作流场景

### 场景 A: 快速上线一个 LLM API 服务

```
vllm  →  bitsandbytes (可选量化)
     [ 1-2 天完成 POC ]
```

### 场景 B: 生产级极限性能 LLM 服务

```
tensorrt-llm  →  awq (FP8/INT4)  →  flash-attention (kernel 定制)
     [ 数周深度优化 ]
```

### 场景 C: Agent / 多轮对话 / 工具调用服务

```
sglang  →  RadixAttention 调参  →  结构化输出 schema
     [ Agent 场景显著优于 vllm ]
```

### 场景 D: 大模型训练 / 推理 (>70B)

```
megatron-core  或  torchtitan  →  deepspeed ZeRO (可选)
     +  pytorch-fsdp2  (小规模)  +  flash-attention
```

### 场景 E: 开发自定义并行算子

```
flash-attention (kernel 参考)  +  megatron-core (通信/切分参考)
     +  pytorch-fsdp2 (DTensor API)
```

---

## 使用方式

### 在 OpenCode 中启用

将 `~/.config/opencode/opencode.json` 或项目下的 `opencode.json` 加上：

```json
{
  "$schema": "https://opencode.ai/config.json",
  "experimental": {
    "skills": ["~/Desktop/Skills/Codex-Skills/work"]
  }
}
```

### 在 Claude Code 中启用

```bash
# 全部安装（推荐）
cp -r /Users/bytedance/Desktop/Skills/Codex-Skills/work/* ~/.claude/skills/

# 或作为 plugin marketplace 安装原仓库
claude /plugin marketplace add Orchestra-Research/AI-Research-SKILLs
```

---

## 触发示例

| 你的问题 | 自动激活的 Skill |
|---------|-----------------|
| "帮我把这个模型部署成 OpenAI 兼容 API" | vllm |
| "prefix caching 怎么做" | sglang |
| "H100 上 FP8 量化推理怎么最快" | tensorrt-llm + awq |
| "写一个 attention kernel 长序列 OOM" | flash-attention |
| "70B 模型显存不够，用 QLoRA 微调" | bitsandbytes |
| "把模型 4-bit 量化投产" | awq |
| "8-way tensor parallelism 怎么切" | megatron-core |
| "ZeRO Stage 3 vs FSDP2 选哪个" | deepspeed + pytorch-fsdp2 |
| "PyTorch 官方大模型 pretrain 怎么起" | torchtitan |

---

## 关键性能对比参考

| 技术 | 提速倍数 | 显存节省 | 精度损失 |
|------|---------|---------|---------|
| Flash Attention | 2-4× | 10-20× | 无 |
| vLLM (vs HF Transformers) | 24× | - | 无 |
| SGLang (vs vLLM, 前缀重叠) | 5× | - | 无 |
| TensorRT-LLM (vs PyTorch) | 10-100× | - | 无（FP8 时轻微） |
| AWQ 4-bit | 3× | 4× | <5% |
| bitsandbytes NF4 | ~1.5× | 4× | <1% |
| ZeRO Stage 3 | - | ~N (# GPUs) | 无 |
| Float8 训练 (torchtitan) | 1.3-1.5× | 2× | ~0.1% |

---

## 依赖说明

各 skill 的 Python 依赖见其 SKILL.md `dependencies` 字段。常用组合：

```bash
# 推理服务栈
pip install vllm sglang[all] tensorrt-llm

# Kernel & 量化
pip install flash-attn --no-build-isolation
pip install autoawq bitsandbytes

# 分布式训练
pip install megatron-core deepspeed
pip install torch torchtitan torchao

# HuggingFace 生态
pip install transformers accelerate peft
```

---

## 来源与协议

| 来源 | 仓库 | Stars | License |
|------|------|-------|---------|
| Orchestra Research | https://github.com/Orchestra-Research/AI-Research-SKILLs | 11.7k | MIT |

所有 skills 均遵循原仓库 MIT 协议，可自由用于商业场景。
