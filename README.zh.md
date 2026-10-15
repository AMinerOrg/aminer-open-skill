# aminer-open-skill

[![版本](https://img.shields.io/badge/version-1.12.0-0969da)](.claude-plugin/marketplace.json)
[![可用 Skill](https://img.shields.io/badge/available_skills-10-2da44e)](#选择-skill)
[![许可证](https://img.shields.io/badge/license-MIT-6f42c1)](LICENSE)

[English](README.md) | 中文

面向 Claude Code、Codex、OpenClaw 等 AI 助手的 AMiner Skill 集，用于查找论文、构建阅读清单与 Taxonomy、追踪论文来源和核查引用。

- [🧰 选择 Skill](#选择-skill)
- [🚀 快速开始](#快速开始)
- [💬 使用场景](#使用场景)
- [ℹ️ 注意事项](#注意事项)
- [📚 参考资料](#参考资料)

## 选择 Skill

通常可以按照“发现与收集文献 -> 分析与追踪论文 -> 核验引用”的流程选择 Skill，也可以直接从当前需要完成的任务开始。

### 🔎 发现与收集文献

| Skill | 适合完成的任务 | Token 要求 | 使用说明 |
| --- | --- | --- | --- |
| `aminer-free-academic` | 使用 AMiner 免费接口查找和初筛论文、学者、机构、期刊或专利 | 接口免费，但仍需 Token | [SKILL.md](skills/aminer-free-academic/SKILL.md) |
| `aminer-academic-search` | 对论文、学者、机构、期刊和专利进行完整检索、深度分析或显式结构化实验检索 | 必须配置；部分 API 计费；实验检索 ¥0.10/次 | [SKILL.md](skills/aminer-academic-search/SKILL.md) |
| `aminer-daily-paper` | 根据主题、学者、作者或 AMiner 账号获取个性化论文推荐 | 必须配置 | [SKILL.md](skills/aminer-daily-paper/SKILL.md) |
| `aminer-deep-search` | 通过多轮检索、去重和引用扩展构建大规模综述文献集 | 必须配置 | [SKILL.zh.md](skills/aminer-deep-search/SKILL.zh.md) |
| `deep-research` | 驱动固定研究循环，结合 AMiner 开放平台与宿主原生 web 工具，产出带引用的分层研究报告与可复用的 Evidence Ledger | 必须配置；免费优先，计费上限 ¥20 | [SKILL.zh.md](skills/deep-research/SKILL.zh.md) |

### 🗂️ 整理论文集合

| Skill | 适合完成的任务 | Token 要求 | 使用说明 |
| --- | --- | --- | --- |
| `scientific-taxonomy` | 根据已有论文标题与摘要生成层次化 Markdown Taxonomy | 可选；仅在需要 AMiner 补全元数据时使用 | [SKILL.md](skills/scientific-taxonomy/SKILL.md) |

### 🧭 分析与追踪论文

| Skill | 适合完成的任务 | Token 要求 | 使用说明 |
| --- | --- | --- | --- |
| `paper-source-trace` | 将论文关键论点追踪到引用上下文和来源，并生成证据报告与引用图 | 可选；仅在使用 AMiner 增强时需要 | [SKILL.zh.md](skills/paper-source-trace/SKILL.zh.md) / [使用说明](skills/paper-source-trace/README_zh.md) |
| `aminer-pdf-ocr` | 将论文 PDF 提交 AMiner PDF OCR 服务转为 Markdown，再由 Agent 按内置提示词抽取实验方法、数据集与指标 | 必须配置 | [SKILL.zh.md](skills/aminer-pdf-ocr/SKILL.zh.md) |
| `aminer-exp-extraction` | 从论文 Markdown 出发，用固定脚本的两阶段 GLM 流水线（句子过滤 + 结构化抽取）产出方法/数据集/指标/关键结果 JSON；如果只有 PDF，先用 `aminer-pdf-ocr` 转出 Markdown | 需要 `BIGMODEL_API_KEY`（智谱 BigModel）；不需要 AMiner Token | [SKILL.md](skills/aminer-exp-extraction/SKILL.md) |

### ✅ 核验引用

| Skill | 适合完成的任务 | Token 要求 | 使用说明 |
| --- | --- | --- | --- |
| `pdf-citation-verifier` | 核验论文 PDF 所列参考文献是否真实存在 | 必须配置 | [SKILL.zh.md](skills/pdf-citation-verifier/SKILL.zh.md) |
| `structured-reference-audit` | 用 GROBID 建立可追溯参考文献账本，再逐条通过 AMiner 保守解析 | AMiner 解析需 token；需 GROBID 或已有 TEI | [SKILL.zh.md](skills/structured-reference-audit/SKILL.zh.md) |
| `citation-faithfulness` | 核查正文引用是否准确表达了被引来源的原意 | 不需要 AMiner Token，但需要联网 | [SKILL.zh.md](skills/citation-faithfulness/SKILL.zh.md) |

## 快速开始

### 1. 📦 添加需要的 Skill

克隆原作者仓库：

```bash
git clone https://github.com/CanXiangCC/aminer-open-skill.git
cd aminer-open-skill
```

通过 AI 助手常用的 Skill 或插件安装方式，添加所需的 `skills/<skill-name>/` 目录。如果 AI 助手支持 Claude 插件，可以通过 [`.claude-plugin/marketplace.json`](.claude-plugin/marketplace.json) 查看可安装条目。

### 2. 🔑 按需配置 Token

在 [AMiner 控制台](https://open.aminer.cn/open/board?tab=control)生成 Token，然后在 AI 助手使用的环境中配置 `AMINER_API_KEY`：

```bash
export AMINER_API_KEY="<YOUR_TOKEN>"
```

Claude Code、Codex 等本地对话式会话可以使用仓库提供的快速配置工具：

```text
Windows：       tools\setup-aminer-token.cmd
PowerShell：    .\tools\setup-aminer-token.ps1
macOS/Linux：   ./tools/setup-aminer-token.sh
```

OpenClaw 需要使用自己的环境配置：

```bash
openclaw config set env.vars.AMINER_API_KEY "<YOUR_TOKEN>"
```

独立 CLI、CI 和定时任务也需要在各自运行环境中配置 Token。并非所有 Skill 都需要 Token，配置前请先查看上方表格。

### 3. 💬 直接描述任务

用自然语言说明学术任务，并提供需要的论文、主题、学者或输出偏好：

```text
查找近期关于多模态智能体的论文，并总结主要研究方向。
```

如果 Skill 提供 slash command，也可以直接调用：

```text
/aminer-deep-search topic: "多模态智能体" target-size: 200
```

## 使用场景

安装对应 Skill 后，可以直接使用下面的请求：

| 目标 | 示例请求 | Skill |
| --- | --- | --- |
| 快速查找论文 | “查找 10 篇近期关于长上下文语言模型的论文，返回标题、年份、期刊或会议、引用量和链接。” | `aminer-free-academic` |
| 调研学者或研究方向 | “整理 Andrew Ng 的研究画像，包括研究兴趣、代表论文、主要合作者和近期工作。” | `aminer-academic-search` |
| 检索结构化实验 | “返回这篇论文的原始 Experiment JSON，并按方法和数据集名称精确过滤。” | `aminer-academic-search` |
| 获取聚焦阅读清单 | “推荐 8 篇关于工具调用型多模态智能体的论文，优先选择近期且高引用的工作。” | `aminer-daily-paper` |
| 为综述收集文献 | “收集 200 篇检索增强生成方向的候选论文，从高质量种子论文继续扩展，去重后导出文献清单。” | `aminer-deep-search` |
| 整理论文集合 | “把这些论文的标题和摘要组织成层次清晰的 Taxonomy，并保存为 taxonomy.md。” | `scientific-taxonomy` |
| 产出带出处的研究报告 | “调研中国大模型行业，写一份带引用的报告，每个论断都有证据台账支撑。” | `deep-research` |
| 追踪论文来源 | “分析这篇 PDF，将每个关键论点追踪到引用上下文和来源，解释引用意图，并生成 Markdown、JSON、SVG 和 HTML 产物。” | `paper-source-trace` |
| 解析 PDF 并抽取实验 | “把这篇论文 PDF 转成 Markdown，并抽取实验方法、数据集和指标的 JSON。” | `aminer-pdf-ocr` |
| 从 Markdown 抽取实验 | “读取这篇论文的 Markdown 文件，抽取实验方法、数据集、指标和关键结果，输出为一个 JSON 文件。” | `aminer-exp-extraction` |
| 识别虚假参考文献 | “核验这篇论文 PDF 中的所有参考文献，标出不存在、可疑或需要人工复核的条目。” | `pdf-citation-verifier` |
| 保守核验结构化参考文献 | “将这篇 PDF 拆成参考文献账本，再逐条通过 AMiner 解析；未命中不能直接当作伪造。” | `structured-reference-audit` |
| 核查引用忠实性 | “逐条检查这篇论文的正文引用，获取被引来源，并判断上下文中的论断是否得到原文支持。” | `citation-faithfulness` |

## 注意事项

- 不要打印、记录或提交 `AMINER_API_KEY`。
- `aminer-exp-extraction` 调用的是智谱 BigModel API：请为它配置 `BIGMODEL_API_KEY`（可回退 `OPENAI_API_KEY`），它不使用 AMiner Token。
- AMiner 免费接口仍需 Token。建议先用 `aminer-free-academic`，仅在必要时调用计费 API。
- 部分任务会产生 API 费用。执行大规模检索或高成本调用前，应先查看预估成本。
- `tools/` 下的配置工具只面向本地对话式环境。OpenClaw、CLI、CI 和定时任务需要单独配置。
- 如果需要直接集成 API，而不是使用 Skill，请参考下方 AMiner 开放平台文档。

## 参考资料

- [AMiner 控制台](https://open.aminer.cn/open/board?tab=control)
- [AMiner 开放平台文档](https://open.aminer.cn/open/docs)
- [Claude 插件清单](.claude-plugin/marketplace.json)
- [MIT License](LICENSE)
