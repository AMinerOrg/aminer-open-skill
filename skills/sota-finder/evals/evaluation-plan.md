# `sota-finder` SOTA Discovery Evaluation Plan v4.1

## 1. 目标

本套件包含 **20 cases**，只评测 Skill 的核心任务：从真实用户问题出发，检索当前或历史 SOTA，核对可比口径，建立有用的 Leaderboard，并给出有证据支撑的领先结果与覆盖缺口。

本版不把基础设施故障、隐私限制、覆盖写入、字段一致性、产物格式或负向路由作为独立 Case。此类行为由单元测试或专项集成测试负责，避免稀释 SOTA Discovery 的综合质量信号。

历史套件保留在 [`evals-v3.0.0.json`](./evals-v3.0.0.json)、[`evals-v2.1.1.json`](./evals-v2.1.1.json) 和 [`evals-v1.1.0.json`](./evals-v1.1.0.json)。

## 2. 每个 Case 的统一能力合同

所有 Case 都完整评测以下七项能力，而不是把它们拆成零散小题：

1. `query-formulation`: 使用全称、缩写、别名、任务名和方法名形成有效检索式。
2. `source-coverage`: 覆盖适用的官方页面、论文、预印本、仓库、模型卡和聚合站。
3. `scope-comparability`: 正确区分数据集、版本、split、指标、协议和关键设置。
4. `evidence-verification`: 核对分数、日期、方法身份、设置与原始来源。
5. `leaderboard-construction`: 建立足够完整、范围清楚且可直接使用的榜单。
6. `sota-identification`: 指出证据最充分的 SOTA；若无统一冠军，则按范围给出结论。
7. `coverage-gaps`: 说明未覆盖、未核验或不可比较的结果，并合理停止搜索。

标准产物仍可由 Skill 默认生成，但不作为本套件的主要评分对象。

## 3. Case 分层

| 类型 | 数量 | 主要问题 |
|---|---:|---|
| `benchmark-sota` | 10 | 单一 benchmark 或官方挑战中的当前 SOTA |
| `multitrack-sota` | 5 | 总榜、子榜、历史阶段或输入种子更新 |
| `open-world-sota` | 5 | 没有统一官方榜单，需要先建立可比范围 |

探索成本分为：`quick` 5 个、`standard` 10 个、`deep` 5 个。场景层级为 `simple_daily` 5 个和 `complex_daily` 15 个，不包含人为设计的边界 Case。

执行模式为 `live_web` 18 个和 `aminer_optional` 2 个。所有 Case 都必须使用实时 Web Search；AMiner 仅在 Case 17 和 18 中作为可选的论文发现补充，不影响基础完成条件。

## 4. Case 矩阵

| Case | 任务 | 类别 | 层级 | 模式 | 语言 | Must-pass |
|---:|---|---|---|---|---|---|
| 01 | 中文：SWE-bench Verified 当前官方 SOTA | `benchmark-sota` | `quick` | `live_web` | zh | 是 |
| 02 | English: current LiveCodeBench code-generation SOTA | `benchmark-sota` | `quick` | `live_web` | en | 否 |
| 03 | 中文：DocVQA 近期 SOTA 与分范围榜 | `benchmark-sota` | `standard` | `live_web` | zh | 是 |
| 04 | 中文：LibriSpeech 语音识别 SOTA | `benchmark-sota` | `quick` | `live_web` | zh | 是 |
| 05 | 中文：COCO 目标检测 test-dev SOTA | `benchmark-sota` | `standard` | `live_web` | zh | 否 |
| 06 | 中文：ImageNet-1K 图像分类 SOTA | `benchmark-sota` | `quick` | `live_web` | zh | 否 |
| 07 | 中文：KITTI 3D 目标检测官方榜 SOTA | `benchmark-sota` | `standard` | `live_web` | zh | 是 |
| 08 | 中文：BraTS 脑肿瘤分割挑战 SOTA | `benchmark-sota` | `standard` | `live_web` | zh | 否 |
| 09 | English: current LongBench v2 long-context SOTA | `benchmark-sota` | `quick` | `live_web` | en | 否 |
| 10 | 中文：ChartQA 当前 SOTA 与协议变体 | `benchmark-sota` | `standard` | `live_web` | zh | 否 |
| 11 | 中文：MTEB 中文检索总榜与数据集分榜 | `multitrack-sota` | `standard` | `live_web` | zh | 是 |
| 12 | 中文：MMMU 总榜与学科分项 SOTA | `multitrack-sota` | `standard` | `live_web` | zh | 否 |
| 13 | 中文：Video-MME 多赛道 SOTA | `multitrack-sota` | `standard` | `live_web` | zh | 否 |
| 14 | English: historical and current image-captioning SOTA | `multitrack-sota` | `standard` | `live_web` | en | 否 |
| 15 | 中文：用最新证据更新历史 SOTA 榜单 | `multitrack-sota` | `standard` | `live_web` | zh | 是 |
| 16 | 中文：无统一榜单的长文档 RAG 引用忠实度 SOTA | `open-world-sota` | `deep` | `live_web` | zh | 是 |
| 17 | 中文：科研文献问答与答案可验证性 SOTA | `open-world-sota` | `deep` | `aminer_optional` | zh | 否 |
| 18 | 中文：可复现的多模态文档问答 SOTA | `open-world-sota` | `deep` | `aminer_optional` | zh | 否 |
| 19 | English: text-to-image prompt-following SOTA across benchmarks | `open-world-sota` | `deep` | `live_web` | en | 否 |
| 20 | 中文：文档抽取与 OCR 跨基准 SOTA | `open-world-sota` | `deep` | `live_web` | zh | 是 |

## 5. 执行与评分

每个 Case 使用 0-4 分五档量表，但不再把七项能力简单等权平均。最终用户价值优先，权重如下：

| 维度 | 权重 |
|---|---:|
| 检索式与术语覆盖 | 3% |
| 来源覆盖 | 7% |
| 范围与可比性 | 15% |
| 关键结果核验 | 10% |
| Leaderboard 完整性与可用性 | 25% |
| SOTA 判断、清晰结论与实用推荐 | 25% |
| 覆盖缺口处理 | 5% |
| 阅读友好性 | 10% |

搜索次数、证据数量、审计篇幅和思维链长度本身不得加分。来源与检索只在其改善覆盖、准确性或结论可信度时得分。正常、可靠的完成质量通常为 3 分；4 分要求有明确的正面证据，不能因为文件齐全或措辞谨慎而默认给满分。

建议判定：

- 4 分：完整、准确、清晰，对用户决策直接有用，且没有实质遗漏。
- 3 分：主体正确，仅有轻微遗漏。
- 2 分：可部分使用，但覆盖、可比性或证据存在明显缺口。
- 1 分：仅完成少量检索或产生不可靠的小榜单。
- 0 分：未完成该能力，或结论具有实质误导性。

阅读友好性单独按相同五档评分，只检查聊天答复和 `brief-report.md`。清晰结论应先于方法、证据和限制；短榜应尽量完整，长榜应合理压缩并指向完整结果。审计语言、重复免责声明和检索过程不构成高质量说明。

效率采用确定性扣分而不是由 Judge 主观奖励。成功运行的软时间预算为：`quick` 600 秒、`standard` 1200 秒、`deep` 1800 秒。超出预算 1.5、2、3 倍以内分别扣 2、5、8 分，超过 3 倍扣 10 分；超过 2 倍时总分最高为 85。基础设施失败重试单独记录，不作为 Skill 质量扣分。

Runner 默认不设置硬进程超时：软时间预算只用于引导交付和计算效率分，不得在 Agent 仍正常工作时强制终止。仅当操作者显式传入正数 `--timeout-seconds` 时启用硬超时；联网限流、流中断或认证故障应按基础设施失败重试，不能据此评价 Skill 质量。

为防止平均分掩盖核心失败，`scope-comparability`、`leaderboard-construction` 和 `sota-identification` 任一低于 2 分时，Case 不通过。触发 Case 明列的严重失败条件时总分封顶 60；Hard failure 仍直接记 0 分。

阅读友好性为 0 分时总分封顶 60，为 1 分时封顶 75。这样即使证据与文件齐全，只要最终结果仍被过程说明淹没、缺少可读结构或用户难以找到结论，也不能获得通过分。

### Must-pass status

Case 01、03、04、07、11、15、16、20 为代表性 Must-pass。发布候选必须全部完成，且每个 Case 的 `scope-comparability`、`evidence-verification`、`leaderboard-construction` 和 `sota-identification` 均不得低于 2 分。

建议总体验收线：

- 20 Case 全部产生可评分结果；
- 每个 Case 至少 80/100，且三个核心维度均达到最低要求；
- 全体平均分与类别宏平均均不低于 80/100，最低类别不低于 70/100；
- Must-pass 全部通过；
- 不出现把明显不可比结果混排后宣布唯一冠军的严重错误。

## 6. Live-web drift policy

本套件不冻结方法名和分数。评测时记录绝对日期、模型、Token、缓存 Token、用时和 Agent 轨迹，并按当日可访问证据评分。榜单自然更新不视为回归；以下情况才视为失败：来源覆盖明显不足、范围划分错误、关键数字不可核验、遗漏大量明显候选、错误识别 SOTA，或未说明重要覆盖缺口。

如 Web Search 或评测基础设施异常，应将运行标记为无效并重跑，不得将基础设施失败计入 Skill 质量，也不得据此继续迭代 Skill。

## 7. 维护与验证

- 结构合同由 [`tests/test_eval_suite.py`](../tests/test_eval_suite.py) 锁定。
- 正式套件只保留真实 SOTA 搜索任务；边界与工程行为进入独立测试。
- 增删 Case 时保持中文为主、三类任务和三档探索成本的整体平衡。
- 全量在线评测成本较高，仅在套件结构验证通过且环境正常时运行。
