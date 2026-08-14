# CS 科研 Skills 集合

> 面向计算机科学研究生的高质量 Agent Skills 精选合集。
> 覆盖 **选题 → 文献 → 实验 → 写作 → 演讲** 完整科研生命周期。

所有 skill 均遵循 [Agent Skills 标准](https://agentskills.io)，兼容 Claude Code、Codex、OpenCode、Cursor、Gemini CLI 等主流 coding agent。

---

## 目录总览

| # | Skill | 用途 | 来源 | 复杂度 |
|---|-------|------|------|--------|
| 1 | [`autoresearch`](./autoresearch) | 端到端自主科研编排（双循环架构） | Orchestra Research | ⭐⭐⭐⭐⭐ |
| 2 | [`brainstorming-research-ideas`](./brainstorming-research-ideas) | 结构化研究选题脑暴（10 种思维框架） | Orchestra Research | ⭐⭐ |
| 3 | [`deep-research`](./deep-research) | 多源三角验证的深度调研工作流 | alirezarezvani | ⭐⭐⭐⭐ |
| 4 | [`literature-review`](./literature-review) | 系统性文献综述（多库检索+合成） | K-Dense-AI | ⭐⭐⭐ |
| 5 | [`paper-lookup`](./paper-lookup) | 11 个学术数据库统一查询 | K-Dense-AI | ⭐⭐ |
| 6 | [`citation-management`](./citation-management) | 引用管理（DOI→BibTeX + 幻觉校验） | K-Dense-AI | ⭐⭐ |
| 7 | [`ml-paper-writing`](./ml-paper-writing) | NeurIPS/ICML/ICLR/ACL 论文写作 | Orchestra Research | ⭐⭐⭐⭐⭐ |
| 8 | [`academic-plotting`](./academic-plotting) | 出版级论文配图（matplotlib+AI） | Orchestra Research | ⭐⭐⭐ |
| 9 | [`presenting-conference-talks`](./presenting-conference-talks) | 会议 Talk 幻灯片（Beamer+PPTX） | Orchestra Research | ⭐⭐⭐ |

---

## 推荐科研工作流

```
┌───────────────────────────────────────────────────────────────┐
│                      科研生命周期                                │
└───────────────────────────────────────────────────────────────┘

  阶段 1  选题     brainstorming-research-ideas
                       │
                       ▼
  阶段 2  文献     deep-research  ➜  literature-review
                                              │
                                              ▼
                                    paper-lookup + citation-management
                                              │
                                              ▼
  阶段 3  实验     autoresearch  ◀────────────┘
              （编排整个实验循环，含实验设计、跑实验、
                记录、复盘、迭代等）
                       │
                       ▼
  阶段 4  写作     ml-paper-writing  +  academic-plotting
                       │
                       ▼
  阶段 5  演讲     presenting-conference-talks
```

**新手起步建议**：从 `brainstorming-research-ideas` + `paper-lookup` 开始最容易上手；进入正式项目后再启用 `autoresearch`。

---

## 各 Skill 详细说明

### 1. autoresearch —— 端到端自主科研编排

**这是整个集合的旗舰 skill**，实现完全自主的研究项目管理。

- **双循环架构**：
  - **内循环（Inner Loop）**：快速实验迭代，明确的可测量指标（灵感来源于 Karpathy 的 autoresearch 工作流）
  - **外循环（Outer Loop）**：跨实验综合分析，识别规律，调整方向
- **持续运行**：通过 Claude Code `/loop` 或 OpenCode heartbeat 实现 20 分钟粒度的持续研究
- **状态管理**：`research-state.yaml` + `research-log.md` + `findings.md` 三文件维护完整项目记忆
- **Git 预注册**：实验协议在跑实验前先提交 git，作为"实验前你想到了什么"的时间戳证据（避免结果导向 p-hacking）
- **自动路由**：识别研究任务后自动调用相应领域 skill（模型架构 / 数据处理 / 评估 / 分布式训练 等）
- **产出 HTML/PDF 进展报告**给导师看

**核心工作流**：`Bootstrap（文献+假设）→ Inner Loop（实验x10）→ Outer Loop（反思）→ ... → Conclude（写论文）`

**适用场景**：任何可通过实验探索的研究问题，且存在可测量的代理指标（proxy metric）。

---

### 2. brainstorming-research-ideas —— 结构化研究选题

用 10 种互补的思维框架帮你把模糊好奇心变成扎实的研究提案。

- 从"我想探索 X"到"具体、可辩护的研究问题"的迭代脚本
- 涵盖：先发散再收敛、跨领域类比、极端场景假设、悖论挖掘、假设逆转…
- 每个框架针对不同认知模式，可单独使用或组合

**适用场景**：开始新研究方向、当前项目卡壳、评估半成型想法、准备与合作者头脑风暴。

---

### 3. deep-research —— 严谨的多源深度调研

不是快速一句话答复，而是**可审计、可复用**的调研工作流。

- **9 阶段流水线**：Reframe → Genre → Plan → Capability discovery → Search (fan-out) → Score & triangulate → Synthesize + adversarial → Verify → Refresh targets
- **核心机制**：
  - **三角验证**：每个论点需 ≥3 个不同类型的独立来源（一手/学术/工业/讨论）
  - **来源存档**：每条来源单独存为 `sources/NN_slug.md`，含逐字引用（避免 AI 幻觉）
  - **对抗性审查**：主动搜索反证，对抗确认偏差
  - **可证伪假设**：调研开始前提出 2-4 个可证伪假设
  - **并行子代理**：多个子代理并发跑不同信道搜索
- **可增量刷新**：一个月后可跑 `update <slug>` 只查变化，无需重跑整个调研

**适用场景**：战略决策、比较 N 个方案 / 产品 / 方法 / 市场、假设验证、映射一个领域的全貌。**不是**快速事实核查。

---

### 4. literature-review —— 系统性文献综述

按学术严谨的方法做系统性文献综述。

- 多数据库检索：**PubMed / arXiv / bioRxiv / Semantic Scholar** 等
- 主题式综合（thematic synthesis）
- 全部引用验证（消除幻觉引用）
- 输出**多种引用样式**的 markdown + PDF（APA、Nature、Vancouver…）
- 使用 `parallel-web` skill 做广度学术检索

**适用场景**：为一篇论文或综述写文献综述章节；准备开题报告的相关工作部分；meta-analysis 或 scoping review。

---

### 5. paper-lookup —— 11 个学术数据库统一查询

把用户意图变成**可复现的**文献检索：选权威数据库、有节流地调用、返回带 provenance 的结果。

覆盖 11 个数据库：
- **PubMed / PMC** (生物医学)
- **Europe PMC** (含全文和 preprint)
- **bioRxiv / medRxiv** (生命科学 preprint)
- **arXiv** (CS/物理/数学 preprint)
- **OpenAlex** (通用学术，覆盖广)
- **Crossref** (DOI 官方注册)
- **Semantic Scholar** (含引用图谱)
- **CORE** (开放访问全文)
- **Unpaywall** (合法的开放获取 PDF)

**关键点**：这些 API 会**用 HTTP 200 返回错误**（比如 arXiv 把无效字段悄悄改成 `all:` 前缀），skill 内置了识别每种"沉默失败"模式的 hazard 说明。

**适用场景**：查某篇具体论文、DOI/PMID/arXiv ID 相互转换、找 open-access PDF、看谁引用了某篇论文。

---

### 6. citation-management —— 引用管理

避免 AI 幻觉引用的完整工作流。

- 从 **DOI / PMID / arXiv ID** 拉取权威 BibTeX
- 交叉验证多个源（CrossRef / PubMed / arXiv / DataCite）
- 自动清理 BibTeX 格式
- 检测**幻觉引用**（AI 平均引用错误率约 40%）

**适用场景**：为论文添加引用时，写 BibTeX 前必用；把手头 `.bib` 文件的 `[CITATION NEEDED]` 转成真实条目。

---

### 7. ml-paper-writing —— 顶会论文写作

面向 **NeurIPS / ICML / ICLR / ACL / AAAI / COLM** 的出版级论文写作。

- 综合了顶级研究者的写作理念：**Nanda, Farquhar, Karpathy, Lipton, Steinhardt**
- 各个会议的 **LaTeX 模板**
- **引用 API 集成**：Semantic Scholar / arXiv / Habanero(CrossRef) → 永不幻觉引用
- 阶段化：`理解仓库 → 输出完整初稿 → 找引用 → 反馈迭代`
- 提供 Related Work / Method / Experiments / Conclusion 各章节的写作 checklist
- 相机就绪（camera-ready）版检查表
- 系统类 venues（OSDI、NSDI、ASPLOS、SOSP）用姊妹 skill `systems-paper-writing`（此处未收录，如需可另加）

**核心规则**：`NEVER hallucinate citations`—任何未验证的引用必须显式标记为 `[CITATION NEEDED]`。

**适用场景**：从研究仓库起草论文、结构化论点、准备投稿版本。

---

### 8. academic-plotting —— 出版级论文配图

针对 ML 论文的两类图表提供两种工作流：

| 图表类型 | 工具 | 说明 |
|---------|------|------|
| 系统架构图 / 流程图 / 管道图 | Gemini AI 生图 | 复杂布局，含框和箭头 |
| 折线图 / 柱状图 / 散点图 / 热图 | matplotlib + seaborn | 精确数值、可复现 |

- 从实验结果或数据自动选择合适的图表类型
- 遵循顶会的字号 / 配色 / 边距惯例
- 生成 LaTeX 可直接 `\includegraphics{}` 的 PDF/SVG

**适用场景**：为 NeurIPS/ICML 论文出图；主实验图、消融实验图、训练曲线图、混淆矩阵。

---

### 9. presenting-conference-talks —— 会议演讲幻灯片

从**已经完成的 paper** 生成会议演讲材料。

- 同时产出 **Beamer LaTeX PDF**（打磨排版）+ **PPTX**（临场编辑）
- 附带 **speaker notes** 和 **talk script**
- 支持四类演讲：
  - Poster talk (2-3 min)
  - Spotlight (5-10 min)
  - Oral (15-20 min)
  - Invited talk (30+ min)
- 覆盖 ML (NeurIPS/ICML/ICLR) 和系统 (OSDI/SOSP/ASPLOS) 会议惯例

**适用场景**：论文被 accepted 后，准备现场演讲；给组会/学术报告做 slides。

---

## 使用方式

### 在 OpenCode 中启用

将本目录作为 skills 目录挂载即可。默认情况下 OpenCode 会读取每个子目录的 `SKILL.md` frontmatter 里的 `description` 字段，然后按需自动加载。

如需在 `opencode.json` 或 `~/.config/opencode/opencode.json` 中显式声明：

```json
{
  "$schema": "https://opencode.ai/config.json",
  "experimental": {
    "skills": ["~/Desktop/Skills/Codex-Skills/research"]
  }
}
```

### 在 Claude Code 中启用

```bash
# 每个 skill 独立安装
cp -r /Users/bytedance/Desktop/Skills/Codex-Skills/research/autoresearch ~/.claude/skills/

# 或全部拷贝
cp -r /Users/bytedance/Desktop/Skills/Codex-Skills/research/* ~/.claude/skills/
```

### 在其他 agent 中启用

参考各自项目文档（Codex / Cursor / Gemini CLI / Antigravity 等均支持 Agent Skills 标准）。

---

## 触发方式

Skills 会根据 `SKILL.md` 里的 `description` 自动匹配用户请求。示例：

| 用户输入 | 触发的 Skill |
|---------|-------------|
| "我想探索 XX 方向" | brainstorming-research-ideas |
| "帮我调研下 XX 领域的 SOTA" | deep-research |
| "写一篇 XX 主题的文献综述" | literature-review |
| "查一下 arXiv:2401.XXXXX 这篇论文" | paper-lookup |
| "把这些 DOI 转成 BibTeX" | citation-management |
| "运行完整自主研究项目" | autoresearch |
| "把这个实验结果画成论文里的图" | academic-plotting |
| "帮我写一篇投 NeurIPS 的论文" | ml-paper-writing |
| "为这篇 paper 做 20 分钟的 talk slides" | presenting-conference-talks |

---

## 来源与致谢

| 项目 | 仓库 | Stars | License |
|------|------|-------|---------|
| Orchestra Research AI-Research-SKILLs | https://github.com/Orchestra-Research/AI-Research-SKILLs | 11.7k | MIT |
| K-Dense-AI Scientific Agent Skills | https://github.com/K-Dense-AI/scientific-agent-skills | 33.5k | MIT |
| alirezarezvani claude-skills | https://github.com/alirezarezvani/claude-skills | 24.4k | MIT |

所有 skills 均遵循原仓库 MIT 协议。如需了解某个 skill 的所有原始文件，可参考对应仓库。

## 依赖说明

多数 skill 需要以下 Python 包（各自 SKILL.md 会列出）：

```bash
# 通用
pip install semanticscholar arxiv habanero requests

# ml-paper-writing 额外
pip install python-pptx

# academic-plotting 额外
pip install matplotlib seaborn google-genai

# citation-management 额外（可选）
pip install scholarly

# literature-review 需要
# 安装 pandoc 用于 markdown → PDF 转换
brew install pandoc
```

某些高级功能建议接入 **Exa MCP** 提升学术搜索质量：

```bash
claude mcp add exa -- npx -y mcp-remote "https://mcp.exa.ai/mcp"
```
