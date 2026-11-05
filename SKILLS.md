# 技能目录

[← 返回 README](README.md) · [English](SKILLS.en.md)

当前 `skills/` 下包含以下 21 个可触发技能。点击技能名查看完整技能定义。前 7 个为科研工作流技能，在 AMiner 网页版在线可用；其余面向本地 Agent，按科研阶段分组。

**目录**：

- [科研工作流（网页版在线可用）](#科研工作流网页版在线可用)
- [检索与发现](#检索与发现)
- [阅读与整理](#阅读与整理)
- [调研报告](#调研报告)
- [论文实验核查](#论文实验核查)
- [引用核查](#引用核查)
- [易混技能如何选择](#易混技能如何选择)
- [设计原则](#设计原则)

## 科研工作流（网页版在线可用）

| 技能 | 状态 | 用途 | 触发词 | Token |
| --- | --- | --- | --- | --- |
| [`aminer-paper-deep-reading`](skills/aminer-paper-deep-reading/SKILL.zh.md) | Stable | 论文精读：总结方法与实验、逐句翻译解析、审计复现级实验细节；也可跨文献汇总某参数的取值，或根据模糊描述反查论文 | 「精读这篇论文」「XX 参数的典型取值是多少」 | 必须配置；免费优先 |
| [`aminer-paper-writing`](skills/aminer-paper-writing/SKILL.zh.md) | Stable | 论文写作与返修：从零成稿并配真实引用，投稿前模拟审稿，逐条回复审稿意见并撰写回复信 | 「帮我撰写 Related Work 并配上引用」「逐条回复审稿意见」 | 必须配置；免费优先 |
| [`aminer-experiment-to-paper`](skills/aminer-experiment-to-paper/SKILL.zh.md) | Stable | 实验分析与结果撰写：代码报错排查、实验设计评估、将实验结果写成论文表述，并核实方法出处与先例 | 「我的实验复现不出论文基线，帮我排查」 | 必须配置；免费优先 |
| [`aminer-thesis-writing`](skills/aminer-thesis-writing/SKILL.zh.md) | Stable | 学位论文全流程：开题文献调研与查新、按学校模板逐节起草、逐条落实导师与评审意见、格式合规、答辩材料 | 「帮我做开题报告的文献调研」「逐条处理导师的批注」 | 必须配置；免费优先 |
| [`aminer-grant-application`](skills/aminer-grant-application/SKILL.zh.md) | Stable | 科研项目申报：从申报指南提取要求、凝练科学问题、分节撰写申报书、查新以避免选题重复，最后模拟评审专家评审 | 「提取这份申报指南的申报要件」「以评审专家身份评审我的申报书」 | 必须配置；免费优先 |
| [`aminer-topic-advisor-selection`](skills/aminer-topic-advisor-selection/SKILL.zh.md) | Stable | 科研选题与导师选择：评估方向竞争程度、开展选题查新；梳理院系导师名单、逐一建立档案并对比、撰写联系导师邮件 | 「该方向是否仍有研究价值」「帮我梳理该院系的导师名单」 | 必须配置；逐师档案 person_detail ¥1.00/次，先免费收敛再拉详情 |
| [`aminer-patent-tech-intelligence`](skills/aminer-patent-tech-intelligence/SKILL.zh.md) | Stable | 专利与技术情报：撰写产业技术调研报告、指标对标、URS/SOP 文书；检索现有技术（对比文件）、起草交底书与权利要求、答复审查意见 | 「撰写一份XX产业技术调研报告」「检索X之前公开的现有技术」 | 必须配置；免费优先，批量排查注意 person_detail 单价 |

**示例提示词**：

- 论文精读（`aminer-paper-deep-reading`）：精读《Attention Is All You Need》：总结问题、方法、实验设计与关键数字，并给出可继续深入的方向。
- 论文写作与返修（`aminer-paper-writing`）：帮我撰写这篇论文的 Related Work，每个论断配上真实检索到的引用，并模拟审稿人给出一轮评审意见。
- 实验分析与结果撰写（`aminer-experiment-to-paper`）：我的实验复现不出论文报告的指标，帮我排查；并核实该指标的文献依据。
- 学位论文全流程（`aminer-thesis-writing`）：帮我完成开题文献调研与题目查新，再逐条处理导师对第二章的批注。
- 科研项目申报（`aminer-grant-application`）：提取这份申报指南中的申报要件，帮我凝练科学问题并按节撰写，最后以评审专家身份评审一遍。
- 科研选题与导师选择（`aminer-topic-advisor-selection`）：评估「检索增强生成用于工业缺陷检测」这一方向的竞争程度，并对该选题进行查新。
- 专利与技术情报（`aminer-patent-tech-intelligence`）：撰写一份固态电解质产业技术调研报告，并检索该申请日之前公开的最接近现有技术。

## 检索与发现

| 技能 | 状态 | 用途 | 触发词 | Token |
| --- | --- | --- | --- | --- |
| [`aminer-free-academic`](skills/aminer-free-academic/SKILL.md) | Stable | 用 7 个免费接口检索论文、学者、机构、期刊、专利的基本信息，零费用 | 「按标题检索这篇论文」「该学者的研究兴趣和引用量」 | 接口免费，仍需 Token |
| [`aminer-academic-search`](skills/aminer-academic-search/SKILL.md) | Stable | 完整学术数据查询：论文、学者、机构、期刊、专利的深度检索，以及论文实验数据的结构化查询（29 个 API） | 「构建学者完整画像」「返回 Experiment JSON」 | 必须配置；部分 API 计费；实验检索 ¥0.10/次 |
| [`aminer-daily-paper`](skills/aminer-daily-paper/SKILL.md) | Stable | 按主题、学者画像或作者信息推荐论文，输出 Markdown 或飞书卡片 | 「推荐 8 篇 XX 方向近期高引论文」 | 必须配置 |
| [`aminer-deep-search`](skills/aminer-deep-search/SKILL.zh.md) | Stable | 为综述收集数百篇候选论文：多轮检索、去重、沿参考文献雪球式扩展 | 「收集 200 篇综述候选论文」 | 必须配置 |
| [`sota-finder`](skills/sota-finder/SKILL.zh.md) | Stable | 检索某任务当前或历史上的最优结果（SOTA），按可比口径拆分榜单，每条标注来源 | 「当前 XX 任务的 SOTA 是多少」 | 可选；仅 AMiner 增强时需要 |

**示例提示词**：

- 快速查论文（`aminer-free-academic`）：查找 10 篇近期关于长上下文语言模型的论文，返回标题、年份、期刊或会议、引用量和链接。
- 调研学者或研究方向（`aminer-academic-search`）：整理 Andrew Ng 的研究画像，包括研究兴趣、代表论文、主要合作者和近期工作。
- 检索结构化实验（`aminer-academic-search`）：返回这篇论文的原始 Experiment JSON，并按方法和数据集名称精确过滤。
- 获取聚焦阅读清单（`aminer-daily-paper`）：推荐 8 篇关于工具调用型多模态智能体的论文，优先选择近期且高引用的工作。
- 为综述收集文献（`aminer-deep-search`）：收集 200 篇检索增强生成方向的候选论文，从高质量种子论文继续扩展，去重后导出文献清单。
- 查找 SOTA 并建立榜单（`sota-finder`）：查找当前 DocVQA SOTA，拆分不可比的评测范围，并生成带来源的榜单和标准产物。

## 阅读与整理

| 技能 | 状态 | 用途 | 触发词 | Token |
| --- | --- | --- | --- | --- |
| [`aminer-pdf-ocr`](skills/aminer-pdf-ocr/SKILL.zh.md) | Stable | 将论文 PDF 转换为 Markdown 全文，并提取实验方法、数据集、指标 | 「将这篇 PDF 转换为 Markdown」 | 必须配置 |
| [`aminer-exp-extraction`](skills/aminer-exp-extraction/SKILL.md) | Stable | 从论文 Markdown 抽取实验方法、数据集、指标和结果，输出 JSON | 「从论文 Markdown 抽取方法/数据集/指标」 | 需 BIGMODEL_API_KEY，不用 AMiner Token |
| [`scientific-taxonomy`](skills/scientific-taxonomy/SKILL.md) | Stable | 将一批论文按标题和摘要整理为层次清晰的分类树（Markdown） | 「将这些论文组织成分类树」 | 可选；仅补全元数据时需要 |
| [`paper-source-trace`](skills/paper-source-trace/SKILL.zh.md) | Stable | 将论文中的论点追踪到引用来源，解释引用意图，生成引用关系图 | 「将关键论点追踪到引用来源」 | 可选；仅 AMiner 增强时需要 |

**示例提示词**：

- 解析 PDF 并抽取实验（`aminer-pdf-ocr`）：将这篇论文 PDF 转换为 Markdown，并抽取实验方法、数据集和指标的 JSON。
- 从 Markdown 抽取实验（`aminer-exp-extraction`）：读取这篇论文的 Markdown 文件，抽取实验方法、数据集、指标和关键结果，输出为一个 JSON 文件。
- 整理论文集合（`scientific-taxonomy`）：将这些论文的标题和摘要组织成层次清晰的 Taxonomy，并保存为 taxonomy.md。
- 追踪论文来源（`paper-source-trace`）：分析这篇 PDF，将每个关键论点追踪到引用上下文和来源，解释引用意图，并生成 Markdown、JSON、SVG 和 HTML 产物。

## 调研报告

| 技能 | 状态 | 用途 | 触发词 | Token |
| --- | --- | --- | --- | --- |
| [`deep-research`](skills/deep-research/SKILL.zh.md) | Stable | 撰写带引用的调研报告：分层结构，每个论断均可追溯到证据台账 | 「调研 XX 行业，撰写一份带引用的报告」 | 必须配置；免费优先，计费上限 ¥20 |

**示例提示词**：

- 撰写带引用的研究报告（`deep-research`）：调研中国大模型行业，撰写一份带引用的报告，每个论断都有证据台账支撑。

## 论文实验核查

| 技能 | 状态 | 用途 | 触发词 | Token |
| --- | --- | --- | --- | --- |
| [`baseline-finder`](skills/baseline-finder/SKILL.md) | Preview | 对照实验与引用证据，核查论文是否遗漏了应当比较的实验基线 | 「还应比较哪些实验基线」 | 需要模型 API Key 和 AMiner Token；部分 API 计费；PDF 模式需 GROBID |

**示例提示词**：

- 检查实验基线覆盖（`baseline-finder`）：检查这篇论文的实验部分是否可能遗漏直接实验基线，并区分有证据支持的比较项与待作者核实的候选。

## 引用核查

| 技能 | 状态 | 用途 | 触发词 | Token |
| --- | --- | --- | --- | --- |
| [`pdf-citation-verifier`](skills/pdf-citation-verifier/SKILL.zh.md) | Stable | 逐条核验论文 PDF 的参考文献是否真实存在，找出编造的引用 | 「检查这篇 PDF 的参考文献是否真实存在」 | 必须配置 |
| [`structured-reference-audit`](skills/structured-reference-audit/SKILL.zh.md) | Stable | 保守核验参考文献：先解析 PDF 建立台账，再逐条查询；查不到不等于伪造 | 「保守核验参考文献」 | AMiner 解析需 Token；需 GROBID 或已有 TEI |
| [`citation-faithfulness`](skills/citation-faithfulness/SKILL.zh.md) | Stable | 逐条检查正文引用是否真正支持论断、是否曲解被引文献 | 「引用是否忠于原文」「该引用是否支撑这一论断」 | 不需要 AMiner Token，需联网 |

**示例提示词**：

- 识别虚假参考文献（`pdf-citation-verifier`）：核验这篇论文 PDF 中的所有参考文献，标出不存在、可疑或需要人工复核的条目。
- 保守核验结构化参考文献（`structured-reference-audit`）：将这篇 PDF 拆成参考文献台账，再逐条通过 AMiner 解析；未命中不能直接判定为伪造。
- 核查引用忠实性（`citation-faithfulness`）：逐条检查这篇论文的正文引用，获取被引来源，并判断上下文中的论断是否得到原文支持。

## 易混技能如何选择

| 你的需求 | 选用 | 而非 |
|---|---|---|
| 单步检索论文、学者、机构、期刊、专利，零费用 | `aminer-free-academic` | `aminer-academic-search`（需要完整摘要、学者履历、引用关系、组合工作流时才用） |
| 数百篇候选文献清单，不撰写报告 | `aminer-deep-search` | `deep-research` |
| 一份带引用、有证据台账的研究报告 | `deep-research` | `aminer-deep-search` |
| 几篇个性化推荐阅读 | `aminer-daily-paper` | `aminer-deep-search` |
| 判断参考文献是否真实存在，直接给出判定 | `pdf-citation-verifier` | `structured-reference-audit` |
| 保守核验参考文献，未命中不等于伪造 | `structured-reference-audit` | `pdf-citation-verifier` |
| 判断引用内容是否忠于被引原文 | `citation-faithfulness` | `pdf-citation-verifier` |
| 追溯论点来源、引用意图，生成引用图 | `paper-source-trace` | `citation-faithfulness` |
| 核查论文是否可能遗漏直接实验基线 | `baseline-finder` | `aminer-deep-search`（它收集候选论文，不评估基线覆盖） |
| 将 PDF 转换为全文 Markdown | `aminer-pdf-ocr` | `aminer-exp-extraction`（输入已是 Markdown 时才用） |

## 设计原则

所有技能都遵守以下原则：

1. **引文真实性红线**：检索到才写入，宁可说「未检索到」也绝不编造充数；每条结果三态标注（已核实 / 存疑 / 查无）。
2. **学术数据优先**：论文、学者、机构、期刊、专利等学术查询优先走 AMiner 开放平台；免费接口先行，计费调用先估算成本再执行。
3. **先分诊再执行**：看似相同的请求实为多种任务类型，先判别类型，再按对应的输出契约执行。
4. **首答即全部**：首答按请求类型给出完整产物，不依赖反问澄清。
5. **失败显式报错**：零产出的静默失败绝不发生；失败时保留已输入材料，重发同一句即可断点续传。
6. **交付自带下一步**：每次交付末尾给出可继续的维度、待办或下一节提示。
7. **约束解析并回显**：字数、条数、年份窗、模板等写入指令即为验收标准，动笔前解析回显；配额未满时明确说明缺口。
8. **跨会话状态**：同一稿件、课题或名单跨周迭代是常态，续作继承增量而非从头重写。
9. **载体优先**：引导用户提供真实材料（稿件、数据、意见、模板）——以实际提供的材料为准，不依赖口头描述。
