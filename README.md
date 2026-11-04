<div align="center">
  <h1>AMiner Open Skills</h1>
  <p>
    <a href="LICENSE"><img alt="License" src="https://img.shields.io/badge/license-MIT-2ea44f"></a>
    <a href=".claude-plugin/marketplace.json"><img alt="Version" src="https://img.shields.io/badge/version-1.15.0-0969da"></a>
    <a href="#2-安装"><img alt="Install" src="https://img.shields.io/badge/install-Claude%20Code%20%7C%20Codex%20%7C%20OpenClaw-111827"></a>
    <a href="#3-技能索引"><img alt="Skills" src="https://img.shields.io/badge/skills-21-0ea5e9"></a>
    <a href="README.en.md"><img alt="Language" src="https://img.shields.io/badge/language-中文%20%7C%20English-1f6feb"></a>
  </p>
  <p>
    <a href="https://www.aminer.cn/">在线网站</a>
    · <a href="#2-安装">立即安装</a>
    · <a href="#1-快速开始">快速开始</a>
    · <a href="#3-技能索引">技能索引</a>
    · <a href="https://open.aminer.cn/open/docs">开放平台文档</a>
    · <a href="#4-设计原则与仓库结构">设计原则</a>
    · <a href="README.en.md">English</a>
  </p>
  <p>
    <img src="assets/readme-banner-zh.png" alt="AMiner Open Skills：真实学术数据驱动的科研 Skill 库" width="100%">
  </p>
  <p>
    <b>AMiner 网页版：内置智能搜索、AI 阅读、Res Labs、AI2000 等核心功能，访问地址 <a href="https://www.aminer.cn">https://www.aminer.cn</a></b>
  </p>
</div>

---

`aminer-open-skill` 面向科研全流程收录基于 AMiner 学术数据的可复用技能，强调真实学术数据、可验证证据链与可直接使用的科研产物。

## 目录

- [1. 快速开始](#1-快速开始)
- [2. 安装](#2-安装)
  - [2.1 `npx skills` 安装（推荐）](#21-npx-skills-安装推荐)
  - [2.2 Claude Code 插件安装](#22-claude-code-插件安装)
  - [2.3 手动安装（Codex / OpenClaw / 其他 Agent）](#23-手动安装codex--openclaw--其他-agent)
  - [2.4 Python 依赖](#24-python-依赖)
  - [2.5 配置 Token](#25-配置-token)
  - [2.6 Token 与计费注意事项](#26-token-与计费注意事项)
- [3. 技能索引](#3-技能索引)
  - [3.1 按科研阶段选技能](#31-按科研阶段选技能)
  - [3.2 易混技能怎么选](#32-易混技能怎么选)
  - [3.3 完整技能列表](#33-完整技能列表)
- [4. 设计原则与仓库结构](#4-设计原则与仓库结构)
- [5. 反馈与联系](#5-反馈与联系)
- [6. Star 历史](#6-star-历史)

## 1. 快速开始

安装并按需配置 Token 后（见 [2. 安装](#2-安装)），可以直接把论文、主题、审稿意见或任务描述交给 Agent。下面这些提示词可以直接复制使用：

| 想做什么 | 直接这样说 |
|---|---|
| 快速查论文 | `查找 10 篇近期关于长上下文语言模型的论文，返回标题、年份、期刊或会议、引用量和链接。`（`aminer-free-academic`） |
| 调研学者或研究方向 | `整理 Andrew Ng 的研究画像，包括研究兴趣、代表论文、主要合作者和近期工作。`（`aminer-academic-search`） |
| 检索结构化实验 | `返回这篇论文的原始 Experiment JSON，并按方法和数据集名称精确过滤。`（`aminer-academic-search`） |
| 获取聚焦阅读清单 | `推荐 8 篇关于工具调用型多模态智能体的论文，优先选择近期且高引用的工作。`（`aminer-daily-paper`） |
| 为综述收集文献 | `收集 200 篇检索增强生成方向的候选论文，从高质量种子论文继续扩展，去重后导出文献清单。`（`aminer-deep-search`） |
| 整理论文集合 | `把这些论文的标题和摘要组织成层次清晰的 Taxonomy，并保存为 taxonomy.md。`（`scientific-taxonomy`） |
| 产出带出处的研究报告 | `调研中国大模型行业，写一份带引用的报告，每个论断都有证据台账支撑。`（`deep-research`） |
| 查找 SOTA 并建立榜单 | `查找当前 DocVQA SOTA，拆分不可比的评测范围，并生成带来源的榜单和标准产物。`（`sota-finder`） |
| 检查实验基线覆盖 | `检查这篇论文的实验部分是否可能遗漏直接实验基线，并区分有证据支持的比较项与待作者核实的候选。`（`baseline-finder`） |
| 追踪论文来源 | `分析这篇 PDF，将每个关键论点追踪到引用上下文和来源，解释引用意图，并生成 Markdown、JSON、SVG 和 HTML 产物。`（`paper-source-trace`） |
| 解析 PDF 并抽取实验 | `把这篇论文 PDF 转成 Markdown，并抽取实验方法、数据集和指标的 JSON。`（`aminer-pdf-ocr`） |
| 从 Markdown 抽取实验 | `读取这篇论文的 Markdown 文件，抽取实验方法、数据集、指标和关键结果，输出为一个 JSON 文件。`（`aminer-exp-extraction`） |
| 识别虚假参考文献 | `核验这篇论文 PDF 中的所有参考文献，标出不存在、可疑或需要人工复核的条目。`（`pdf-citation-verifier`） |
| 保守核验结构化参考文献 | `将这篇 PDF 拆成参考文献账本，再逐条通过 AMiner 解析；未命中不能直接当作伪造。`（`structured-reference-audit`） |
| 核查引用忠实性 | `逐条检查这篇论文的正文引用，获取被引来源，并判断上下文中的论断是否得到原文支持。`（`citation-faithfulness`） |
| 深读单篇论文 | `精读《Attention Is All You Need》：总结问题、方法、实验设计与关键数字，并给可继续追问的方向。`（`aminer-paper-deep-reading`） |
| 写期刊稿件 | `帮我写这篇稿子的 Related Work，每个论断配上真实检索到的引用，并模拟审稿人给一轮意见。`（`aminer-journal-paper-write-review-revise`） |
| 排障与对照文献 | `我的实验跑不过论文报告的指标，帮我排查；并核实这个指标的文献依据。`（`aminer-experiment-to-paper`） |
| 开题与学位论文 | `帮我做开题文献盘点和题目查新，再逐条处理导师对第二章的批注。`（`aminer-degree-thesis-proposal-to-defense`） |
| 写基金本子 | `提取这份指南的申报要件，帮我凝练科学问题并按节撰写，最后以评审专家身份评审一遍。`（`aminer-grant-application`） |
| 选题与找导师 | `评估「检索增强生成用于工业缺陷检测」这个方向的竞争密度，并帮我查这个题目有没有人做过。`（`aminer-topic-advisor-selection`） |
| 专利与产业情报 | `做一份固态电解质产业技术调研报告，并检索该申请日之前公开的最接近现有技术。`（`aminer-patent-tech-intelligence`） |

如果你不确定该用哪个技能，直接描述任务即可；如果已经知道技能名，可以在提示词中明确写“使用 `aminer-free-academic`”。以 [Claude Code 插件](#22-claude-code-插件安装)方式安装时，带 `commands/` 的技能还可以用 slash command 直接调用（插件命令带插件名前缀）：

```text
/aminer-deep-search:aminer-deep-search topic: "多模态智能体" target-size: 200
```

## 2. 安装

`skills/` 下每个目录都是一个独立的可安装技能。无论用哪种方式，都要保留完整技能目录（`SKILL.md`、`scripts/`、`references/` 等），不要只复制 `SKILL.md`。安装后再按 [2.5](#25-配置-token) 配置 Token。

| 你的环境 | 推荐方式 |
|---|---|
| Claude Code、Codex、OpenClaw、Cursor、Trae 等主流 Agent | [2.1 `npx skills`](#21-npx-skills-安装推荐) |
| Claude Code，且需要 slash command | [2.2 插件安装](#22-claude-code-插件安装) |
| 无法联网安装、或需要固定版本 | [2.3 手动安装](#23-手动安装codex--openclaw--其他-agent) |

### 2.1 `npx skills` 安装（推荐）

需要 [Node.js 18 或更高版本](https://nodejs.org/)，无需全局安装 CLI。先查看可安装的技能名：

```bash
npx skills add AMinerOrg/aminer-open-skill --list
```

按需安装到当前项目（省略 `--global`）或用户全局（加 `--global`）。`--agent` 取值如 `claude-code`、`codex`、`openclaw`、`cursor`、`trae`：

```bash
# 只装免费入口，装到当前项目的 Claude Code
npx skills add AMinerOrg/aminer-open-skill --agent claude-code --skill aminer-free-academic --yes

# 装多个技能到 Codex 全局
npx skills add AMinerOrg/aminer-open-skill --global --agent codex \
  --skill aminer-free-academic --skill aminer-academic-search --yes

# 装全部技能
npx skills add AMinerOrg/aminer-open-skill --global --agent claude-code --skill '*' --yes
```

查看与更新：

```bash
npx skills list --global
npx skills update --global --yes
```

`npx skills` 只管理技能文件，Python 依赖见 [2.4](#24-python-依赖)；slash command 需要 [2.2 插件安装](#22-claude-code-插件安装)。

### 2.2 Claude Code 插件安装

本仓库自带插件清单 [`.claude-plugin/marketplace.json`](.claude-plugin/marketplace.json)（市场名 `aminer-open-skills`），每个技能是一个插件。在 Claude Code 中执行：

```text
/plugin marketplace add AMinerOrg/aminer-open-skill
/plugin install aminer-free-academic@aminer-open-skills
```

其他技能把 `aminer-free-academic` 换成 [技能列表](#33-完整技能列表) 中的名字即可；也可以只执行第一行，再用 `/plugin` 打开界面勾选。拉取新版：

```text
/plugin marketplace update aminer-open-skills
```

插件方式会同时注册技能自带的 slash command（`commands/` 目录），命令带插件名前缀，例如 `/aminer-daily-paper:aminer-dp`、`/aminer-deep-search:aminer-deep-search`。

### 2.3 手动安装（Codex / OpenClaw / 其他 Agent）

```bash
git clone https://github.com/AMinerOrg/aminer-open-skill.git ~/ai-skills/aminer-open-skill
```

把需要的 `skills/<skill-name>/` 整个目录放进 Agent 的技能目录：

| Agent | 用户级技能目录 | 项目级技能目录 |
|---|---|---|
| Claude Code | `~/.claude/skills/` | `<项目>/.claude/skills/` |
| Codex | `~/.codex/skills/` | — |
| OpenClaw 等其他 Agent | 见各自文档 | 见各自文档 |

推荐用软链接代替复制，之后在 clone 目录里 `git pull` 即可更新：

```bash
ln -s ~/ai-skills/aminer-open-skill/skills/aminer-free-academic ~/.codex/skills/aminer-free-academic
```

手动安装不会注册 slash command（命令文件依赖插件环境变量 `CLAUDE_PLUGIN_ROOT`），直接用自然语言触发技能即可。

### 2.4 Python 依赖

技能脚本需要 `python3`。多数技能只用标准库；下列技能需要额外安装依赖：

| 技能 | 依赖 |
|---|---|
| `aminer-daily-paper` | PyYAML |
| `aminer-pdf-ocr` | requests、pypdf |
| `aminer-exp-extraction` / `pdf-citation-verifier` / `structured-reference-audit` | requests |
| `deep-research` | matplotlib（报告插图） |
| `sota-finder` | openpyxl（导出 Excel） |
| `baseline-finder` | httpx、openai、pypdf |

7 个科研工作流技能（`aminer-topic-advisor-selection` / `aminer-paper-deep-reading` / `aminer-journal-paper-write-review-revise` / `aminer-experiment-to-paper` / `aminer-degree-thesis-proposal-to-defense` / `aminer-grant-application` / `aminer-patent-tech-intelligence`）只依赖标准库，无需额外安装。

```bash
python3 -m pip install -r skills/<skill-name>/requirements.txt
```

`baseline-finder` 也提供独立 CLI；按其 [SKILL.md](skills/baseline-finder/SKILL.md) 将技能目录本身安装到隔离环境，可同时安装依赖并注册 `baseline-finder` 命令。

`structured-reference-audit` 还需要可访问的 [GROBID](https://github.com/kermitt2/grobid) 服务，或已有的 TEI 文件。

### 2.5 配置 Token

在 [AMiner 控制台](https://open.aminer.cn/open/board?tab=control)生成 Token，然后在 AI 助手使用的环境中配置 `AMINER_API_KEY`：

```bash
export AMINER_API_KEY="<YOUR_TOKEN>"
```

本地 Claude Code、Codex 等对话式会话可以使用仓库提供的快速配置工具：

```text
Windows：       tools\setup-aminer-token.cmd
PowerShell：    .\tools\setup-aminer-token.ps1
macOS/Linux：   ./tools/setup-aminer-token.sh
```

OpenClaw 使用自己的环境配置：

```bash
openclaw config set env.vars.AMINER_API_KEY "<YOUR_TOKEN>"
```

独立 CLI、CI 和定时任务需要在各自运行环境中配置 Token。并非所有技能都需要 Token，配置前先查看 [技能列表](#33-完整技能列表) 的 Token 列。

### 2.6 Token 与计费注意事项

- 不要打印、记录或提交 `AMINER_API_KEY`。
- `aminer-exp-extraction` 调用的是智谱 BigModel API：请为它配置 `BIGMODEL_API_KEY`（可回退 `OPENAI_API_KEY`），它不使用 AMiner Token。
- AMiner 免费接口仍需 Token。建议先用 `aminer-free-academic`，仅在必要时调用计费 API。
- 部分任务会产生 API 费用。执行大规模检索或高成本调用前，应先查看预估成本。
- `tools/` 下的配置工具只面向本地对话式环境。OpenClaw、CLI、CI 和定时任务需要单独配置。
- 如果需要直接集成 API 而不是使用 Skill，请参考 [AMiner 开放平台文档](https://open.aminer.cn/open/docs)。

## 3. 技能索引

### 3.1 按科研阶段选技能

| 阶段 | 技能 |
|---|---|
| 检索与发现 | `aminer-free-academic` · `aminer-academic-search` · `aminer-daily-paper` · `aminer-deep-search` · `sota-finder` |
| 阅读与整理 | `aminer-pdf-ocr` · `aminer-exp-extraction` · `scientific-taxonomy` · `paper-source-trace` · `aminer-paper-deep-reading` |
| 调研报告 | `deep-research` |
| 论文实验核查 | `baseline-finder` |
| 引用核查 | `pdf-citation-verifier` · `structured-reference-audit` · `citation-faithfulness` |
| 写作与投稿 | `aminer-journal-paper-write-review-revise` · `aminer-experiment-to-paper` |
| 学位与申报 | `aminer-degree-thesis-proposal-to-defense` · `aminer-grant-application` |
| 选题与情报 | `aminer-topic-advisor-selection` · `aminer-patent-tech-intelligence` |

### 3.2 易混技能怎么选

| 你要的是 | 用这个 | 而不是 |
|---|---|---|
| 单步查论文、学者、机构、期刊、专利，零费用 | `aminer-free-academic` | `aminer-academic-search`（需要完整摘要、学者履历、引用关系、组合工作流时才用） |
| 几百篇候选文献清单，不写报告 | `aminer-deep-search` | `deep-research` |
| 一份带引用、有证据台账的研究报告 | `deep-research` | `aminer-deep-search` |
| 几篇个性化推荐阅读 | `aminer-daily-paper` | `aminer-deep-search` |
| 判断参考文献是否真实存在，直接给出判定 | `pdf-citation-verifier` | `structured-reference-audit` |
| 保守核验参考文献，未命中不等于伪造 | `structured-reference-audit` | `pdf-citation-verifier` |
| 判断引用内容是否忠于被引原文 | `citation-faithfulness` | `pdf-citation-verifier` |
| 追溯论点来源、引用意图，生成引用图 | `paper-source-trace` | `citation-faithfulness` |
| 核查论文是否可能遗漏直接实验基线 | `baseline-finder` | `aminer-deep-search`（它收集候选论文，不评估基线覆盖） |
| 把 PDF 转成全文 Markdown | `aminer-pdf-ocr` | `aminer-exp-extraction`（输入已是 Markdown 时才用） |

### 3.3 完整技能列表

当前 `skills/` 下包含以下 21 个可触发技能。点击技能名查看完整技能定义。

| 技能 | 状态 | 用途 | 触发词 | Token |
| --- | --- | --- | --- | --- |
| [`aminer-free-academic`](skills/aminer-free-academic/SKILL.md) | Stable | 免费接口学术初筛与发现（7 个免费 API，零费用入口） | 「按标题查这篇论文」「这位学者的研究兴趣和引用量」「这个 venue 是会议还是期刊」「专利趋势扫描」 | 接口免费，仍需 Token |
| [`aminer-academic-search`](skills/aminer-academic-search/SKILL.md) | Stable | 全套学术数据查询与分析：论文/学者/机构/期刊/专利检索、结构化实验检索（29 API + 6 工作流） | 「构建学者完整画像」「论文深度下钻」「多条件/语义论文检索」「返回 Experiment JSON」 | 必须配置；部分 API 计费；实验检索 ¥0.10/次 |
| [`aminer-daily-paper`](skills/aminer-daily-paper/SKILL.md) | Stable | 个性化论文推荐：按主题、学者画像或作者信息推荐，支持飞书卡片与 Markdown 输出 | 「推荐 8 篇 XX 方向近期高引论文」「个性化阅读清单」 | 必须配置 |
| [`aminer-deep-search`](skills/aminer-deep-search/SKILL.zh.md) | Stable | 深度综述文献收集：多轮检索、去重与引用滚雪球，构建数百篇候选论文池 | 「收集 200 篇综述候选论文」「从种子论文滚雪球扩展」 | 必须配置 |
| [`deep-research`](skills/deep-research/SKILL.zh.md) | Stable | 深度研究：固定研究循环产出带引用的分层研究报告与可复用的 Evidence Ledger 证据台账 | 「调研 XX 行业，写一份带引用的报告」「文献综述型调研」 | 必须配置；免费优先，计费上限 ¥20 |
| [`baseline-finder`](skills/baseline-finder/SKILL.md) | Preview | 根据实验与引用证据核查论文是否可能遗漏直接实验基线，区分可比较项与待核实候选 | 「还应比较哪些实验基线」「检查论文实验对比是否完整」 | 需要模型 API Key 和 AMiner Token；部分 API 计费；PDF 模式需 GROBID |
| [`sota-finder`](skills/sota-finder/SKILL.zh.md) | Stable | 检索近期或历史 SOTA，区分可比范围，生成带来源的 Leaderboard 与结构化证据 | 「当前 XX 任务的 SOTA 是多少」「拆分可比范围做榜单」 | 可选；仅 AMiner 增强时需要 |
| [`scientific-taxonomy`](skills/scientific-taxonomy/SKILL.md) | Stable | 根据论文标题与摘要生成层次化 Markdown Taxonomy | 「把这些论文组织成层次清晰的分类树」 | 可选；仅补全元数据时需要 |
| [`paper-source-trace`](skills/paper-source-trace/SKILL.zh.md) | Stable | 论文来源追踪、引用意图识别、证据链分析与 SVG/HTML 引用图 | 「把关键论点追踪到引用来源」「解释引用意图」「生成引用图」 | 可选；仅 AMiner 增强时需要 |
| [`aminer-pdf-ocr`](skills/aminer-pdf-ocr/SKILL.zh.md) | Stable | 论文 PDF 经 AMiner OCR 异步解析转为全文 Markdown，并按内置提示词提取实验结构化信息 | 「把这篇 PDF 转成 Markdown」「OCR 并提取实验方法/数据集/指标」 | 必须配置 |
| [`aminer-exp-extraction`](skills/aminer-exp-extraction/SKILL.md) | Stable | 论文 Markdown 经两阶段 GLM 流水线（句子过滤 + 结构化抽取）产出实验 JSON | 「从论文 Markdown 抽取方法/数据集/指标/关键结果」 | 需 BIGMODEL_API_KEY，不用 AMiner Token |
| [`pdf-citation-verifier`](skills/pdf-citation-verifier/SKILL.zh.md) | Stable | 上传论文 PDF 核验每条参考文献是否真实存在，识别 hallucination | 「检查这篇 PDF 的参考文献是不是编的」「找出虚假引用」 | 必须配置 |
| [`structured-reference-audit`](skills/structured-reference-audit/SKILL.zh.md) | Stable | 用 GROBID 建立可追溯参考文献账本，再逐条经 AMiner 保守解析，区分「解析不确定」与「不存在」 | 「保守核验参考文献」「把 PDF 拆成参考文献账本再逐条解析」 | AMiner 解析需 Token；需 GROBID 或已有 TEI |
| [`citation-faithfulness`](skills/citation-faithfulness/SKILL.zh.md) | Stable | 逐条核查正文引用是否忠于被引原文（支持/部分支持/曲解/查无此说/无法核实） | 「引用是否忠于原文」「有没有曲解参考文献」「这条引用支撑这个论断吗」 | 不需要 AMiner Token，需联网 |
| [`aminer-topic-advisor-selection`](skills/aminer-topic-advisor-selection/SKILL.zh.md)<br>[在线使用 ↗](https://www.aminer.cn/?skill=aminer-topic-advisor-selection) | Stable | 科研选题与导师选择双轨：方向冷热/竞争密度、题目查新撞车、代表作定档；院系枚举、逐师档案、同名消歧 | 「这个方向还值不值得做」「帮我查这个题目有没有人做过」「帮我列这个院系的导师并逐个评估」 | 必须配置；逐师档案 person_detail ¥1.00/次，先免费收敛再拉详情 |
| [`aminer-paper-deep-reading`](skills/aminer-paper-deep-reading/SKILL.zh.md)<br>[在线使用 ↗](https://www.aminer.cn/?skill=aminer-paper-deep-reading) | Stable | 读论文——单篇深读：结构化精读、复现级精读（配方审计）、逐句翻译断点续读、跨文献参数面对比表、引用串/模糊记忆精确匹配定位 | 「精读这篇论文」「逐句翻译，解析」「XX参数一般是多少（跨文献对比表）」 | 必须配置；免费优先 |
| [`aminer-journal-paper-write-review-revise`](skills/aminer-journal-paper-write-review-revise/SKILL.zh.md)<br>[在线使用 ↗](https://www.aminer.cn/?skill=aminer-journal-paper-write-review-revise) | Stable | 期刊/会议稿件全流水线：从零成稿（系统性配引）、自有稿锚定修改、投稿前模拟审稿、真实审稿意见返修与回复信 | 「帮我写这篇稿子的 Related Work 并配上引用」「模拟审稿人审我的稿子」「逐条回复审稿意见并出回复信」 | 必须配置；免费优先 |
| [`aminer-experiment-to-paper`](skills/aminer-experiment-to-paper/SKILL.zh.md)<br>[在线使用 ↗](https://www.aminer.cn/?skill=aminer-experiment-to-paper) | Stable | 实验到论文：代码/实验排障、方法出处核实、结果与文献对照、先例存在性检索 | 「我的实验跑不过基线，帮我排障」「这个指标的文献依据是什么」「这个做法有没有人发表过」 | 必须配置；免费优先 |
| [`aminer-degree-thesis-proposal-to-defense`](skills/aminer-degree-thesis-proposal-to-defense/SKILL.zh.md)<br>[在线使用 ↗](https://www.aminer.cn/?skill=aminer-degree-thesis-proposal-to-defense) | Stable | 学位论文全流程：开题（文献盘点/查新）、逐节生产线、导师/评审/盲审意见逐条销号、引文审计、格式合规、答辩材料 | 「帮我做开题报告的文献盘点」「逐条处理导师的批注」「答辩前帮我整理论文要点」 | 必须配置；免费优先 |
| [`aminer-grant-application`](skills/aminer-grant-application/SKILL.zh.md)<br>[在线使用 ↗](https://www.aminer.cn/?skill=aminer-grant-application) | Stable | 基金申报全流程：要件提取、挑方向、科学问题凝练、分节撰写、句级配证、防撞车、多角色模拟评审 | 「提取这份指南的申报要件」「帮我凝练科学问题」「以评审专家组身份评审我的本子」 | 必须配置；免费优先 |
| [`aminer-patent-tech-intelligence`](skills/aminer-patent-tech-intelligence/SKILL.zh.md)<br>[在线使用 ↗](https://www.aminer.cn/?skill=aminer-patent-tech-intelligence) | Stable | 产业技术情报与专利作业：指标对标、URS/SOP 合规文书、专利布局；对比文件检索（申请日硬截止）、权利要求/交底书起草、OA 答复 | 「做一份XX产业技术调研报告」「检索X之前公开的现有技术」「帮我起草交底书」 | 必须配置；免费优先，批量排查注意 person_detail 单价 |

## 4. 设计原则与仓库结构

### 4.1 共享设计原则

所有技能都遵守以下原则：

1. **引文真实性红线**：检索到才写入，宁可说「未检索到」也绝不编造凑数；每条结果三态标注（已核实 / 存疑 / 查无）。
2. **学术数据优先**：论文、学者、机构、期刊、专利等学术查询优先走 AMiner 开放平台；免费接口先行，计费调用先估算成本再执行。
3. **先分诊再动手**：看似相同的请求实为多种任务类型，先判别类型，再按对应的输出契约执行。
4. **首答即全部**：首答按请求类型给出完整产物，不靠反问澄清续命。
5. **失败显式报错**：零产出的静默失败绝不发生；失败时保住已输入材料，同句重发即断点续传。
6. **交付自带下一步**：每次交付末尾给出可继续的维度、待办或下一节提示。
7. **约束解析并回显**：字数、条数、年份窗、模板等写进指令就是验收标准，动笔前解析回显，配额未满明说缺口。
8. **跨会话状态**：同一稿件、课题或名单跨周回炉是常态，续作继承增量而不是从头重写。
9. **载体优先**：引导用户贴自己的真材料（稿、数据、意见、模板）——看贴了什么，不只听说了什么。

### 4.2 仓库目录结构

```text
aminer-open-skill/
├── .claude-plugin/marketplace.json   # Claude 插件清单
├── tools/                            # 本地会话的 Token 快速配置脚本
└── skills/
    ├── <skill-name>/
    │   ├── SKILL.md                  # 技能定义：frontmatter + 规则 + 工作流，触发后由 agent 加载
    │   ├── SKILL.zh.md               # 中文镜像（部分技能提供）
    │   ├── commands/                 # slash command（部分技能提供）
    │   ├── scripts/                  # 调用 AMiner 开放平台的工具脚本
    │   ├── references/               # 提示词与参考规则
    │   ├── evals/                    # 评测样例
    │   └── requirements.txt
    └── ...
```

### 4.3 关于贡献

本仓库技能目前由 AMiner 团队内部维护，暂不接受外部提交新技能。欢迎通过 [GitHub Issues](https://github.com/AMinerOrg/aminer-open-skill/issues) 反馈问题和需求。

## 5. 反馈与联系

- 使用问题与 Bug：[GitHub Issues](https://github.com/AMinerOrg/aminer-open-skill/issues)
- 邮件：[report@aminer.cn](mailto:report@aminer.cn)
- API 接入与计费：[AMiner 开放平台](https://open.aminer.cn/open/docs)

## 6. Star 历史

[![Star History Chart](https://api.star-history.com/svg?repos=AMinerOrg/aminer-open-skill&type=Date)](https://star-history.com/#AMinerOrg/aminer-open-skill&Date)

## 参考

- [AMiner 控制台](https://open.aminer.cn/open/board?tab=control)
- [AMiner 开放平台文档](https://open.aminer.cn/open/docs)
- [Claude 插件清单](.claude-plugin/marketplace.json)
- [MIT License](LICENSE)
