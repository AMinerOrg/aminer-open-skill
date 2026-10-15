---
name: deep-research
version: 1.0.0
author: AMiner
contact: report@aminer.cn
description: >
  基于 AMiner 开放平台数据与宿主原生 web 工具，产出一份带引用、分层编号的研究报告——并在同一次运行中产出 Evidence Ledger：报告背后那份自描述、带版本的 JSON（sources、claims、figures、probes），下游任何系统可直接原样复用。
  当用户需要文献综述、研究全景、实体调研、趋势对比、行业 / 市场调研，或任何"要的是有出处的研究报告而非一次查询"的请求时激活本 skill。
  由宿主模型（正在运行本 skill 的模型）驱动一个固定的研究循环——先侦察问题、从检索返回的内容归纳大纲、按小节检索、把每个来源记入证据台账、发现缺口、迭代——没有台账来源支撑的结论不得进入报告。
  AMiner 的路由与定价位于 scripts/aminer_open.py；web 证据来自宿主自身的 WebSearch 与 WebFetch。免费优先；预估 AMiner 花费达 CNY 10+ 需显式确认，CNY 20 为硬上限。不调用任何额外 LLM 服务。
  路由到其他 skill：单点查询（用 aminer-free-academic）、只要数百篇论文清单而不要报告的综述收集（用 aminer-deep-search）、个性化推荐（用 aminer-daily-paper）。
metadata:
  {
    "openclaw":
      {
        "requires": {
          "bins": ["python3"],
          "env": ["AMINER_API_KEY"]
        },
        "primaryEnv": "AMINER_API_KEY"
      }
  }
---

# Deep Research 深度研究

你是研究者，而不是一个搜索框的封装。先侦察问题，让报告的结构跟随检索实际返回的内容，把每个来源记入台账，写一份每条结论都能回指到你检索到的来源的报告。

## 语言路由

- 当用户主要用中文写作或明确要求中文输出时，使用本文件（`SKILL.zh.md`）。
- 其余请求使用 `SKILL.md`。
- 两种流程下，代码、命令、台账字段名与 API 名保持英文；只有叙述文字切换语言。

## Deep Research 产出两份产物 (v6 §1.2/§7.6)

Deep Research **不只是**一个终端成果（给人看的报告）。一次 DR 迨行在同一条流程上产出两份产物——一份带引用的报告，以及一份 **Evidence Ledger**：引擎自身用来给每条结论把关的那份结构化 JSON（sources、claims、figures、datums、probes、outline、spend）。台账是自描述、可复用的；下游任何系统拿它做什么，是那个系统的事，不是 skill 的事。skill 不认识、也不命名任何消费者：

```text
Deep Research Engine (scripts/evidence.py + scripts/aminer_open.py)
   ↓ 一次运行
   ├── Evidence Ledger      (scripts/evidence.py 状态 JSON — 自描述、可复用)
   └── Report + appendices  (evidence.py render --material → --renumber → --appendix)

自检，无外部消费者：evidence.py check · evaluation/evaluate.py
```

台账是引擎自身的状态——它**不是手写的**，而是从研究循环里自然落出来的 (§7.6)。它是一份自描述、带版本的 JSON：下游任何人（一个 context store、一个 RAG 索引、一个评审流水线，或什么都没有）都可以原样读取。skill 产出它就止步——不导出、不转换、不把它适配到任何其他系统的 schema；那种适配是外部系统的职责，不是 skill 的。

### 子模块 (v6 §7.13)

- `scripts/evidence.py` — **引擎 + 证据台账 + 报告渲染器**：研究循环、机器可消费的台账状态（`{version, topic, probes, outline, sources, claims, figures, datums, spend}`）、`analyze()` 自检，以及 `render`。
- `scripts/aminer_open.py` — AMiner 开放平台检索（stdlib urllib，28 个端点，价格目录，费用文档）。DR 自身的花费追踪路径 (§7.14)。
- `scripts/chartrender.py` — 把一个已登记的 figure 渲染成 PNG。由宿主调用（`aminer_open.py` 的兄弟工具，绝不被 `evidence.py` 派生——后者保持纯离线台账）：确定性的 matplotlib 模板（`bar` / `hbar` / `line` / `pie` / `heatmap`），或一个宿主写的 B 脚本在尽力而为的沙箱里运行（无网络、锁定 cwd、30 秒超时、禁用 token 扫描、数据经 stdin 传入）；B 脚本失败则回退到对应模板。figure 的数字始终来自台账，因此 `check` 的 data↔source 把关在任何路径下都成立。
- `evaluation/evaluate.py` — 来自 `analyze()` 的质量报告 (§7.13 第 5 个子模块，§7.15 内部验证)。
- `samples/patchtst_v3_ledger.json` — v3 schema 的样例台账 (PatchTST)。
- `references/research-loop.md` — 实际流程（任务开始时读它）。

## 适用范围

- 用于：文献综述、研究全景、学者 / 机构 / 期刊 / 专利调研、趋势与对比类问题、行业 / 市场调研、任何需要引用的场景。
- 路由到别处：单点查询（`aminer-free-academic`）、数百篇论文的综述文献清单（`aminer-deep-search`）、个性化推荐（`aminer-daily-paper`）。

## 预检

1. 除非用户另有要求，用用户的语言作答。
2. 至多问两个问题，且仅当不同答案会改变研究范围时才问。否则说出你的假设并开始。
3. AMiner key 在 shell 环境里作为 `AMINER_API_KEY` —— 宿主在调用 skill 前把它 export 进来（如 `export AMINER_API_KEY=…` 或 source 一个 `.env`），`aminer_open.py` 只从这里读，别处不读。若 key 缺失或无效，脚本返回鉴权错误——此时停下，指引用户去 [AMiner Console](https://open.aminer.cn/open/board?tab=control)。绝不请求、打印、记录或保存 token。

## 工具

| 需求 | 工具 |
| --- | --- |
| 论文、学者、机构、期刊、专利 | `scripts/aminer_open.py` — 带价格的 AMiner 允许端点 |
| web 知道而 AMiner 不知道的：项目页、文档、标准、排行榜、发布、新闻 | 宿主原生的 `WebSearch` 与 `WebFetch` |
| probes、outline、sources、claims（含逐字 `--evidence`）、datums（采集的数据点）、覆盖缺口、引用编号、spend | `scripts/evidence.py` — 离线台账 |
| 轮末决策面：复杂度档位、轮次小结、方向备忘录、决策记录、评估信号、引证忠实性核验 | `scripts/evidence.py` — `tier` / `round` / `memo` / `decide` / `signals` / `verify`（全部离线；每个数字由引擎算出，每道阈值由引擎把关） |
| 写草稿前的写作准备面：每节写作目标与现有素材量、素材块（claims + 逐字证据 + 来源笔记）、按引用次数排序的回读清单、未引用池、备忘录 | `evidence.py render --material`（离线、引擎拼装——草稿从它出发写，不凭记忆） |
| 把一个已登记的 figure 渲染成 PNG —— 可视化台账已核验数字的图表，或按日期事件的结构化时间线 | `scripts/chartrender.py` — matplotlib 模板（`bar` / `hbar` / `line` / `pie` / `heatmap` / `timeline`）或沙箱 B 脚本；用 `evidence.py figure mark-rendered` 把结果记回 |

规则：

- 每个 AMiner 请求都走 `scripts/aminer_open.py`。绝不手搓请求、替换别的搜索 API，或调用 `references/api-reference.md` 之外的端点。
- web 证据用宿主自己的工具；不打包或不 shell 出一个爬虫。优先用 `WebFetch` 抓实际页面，而非信任搜索摘要。若原生 web 工具不可用，继续纯 AMiner 路径并在报告里说明。
- 没进台账的东西不得进入报告，且 `evidence.py render` 没打印的小节不得存在。

在选择 AMiner 调用前读 `references/api-reference.md`。它把 `paper_qa_search_pro` 标为默认的主题搜索，解释为何 `query_type: "auto"` 是默认以及何时降到 `topic`，列出能纠偏一个漂移查询的字段，并标注哪些端点是免费的。

## 方法

遵循 `references/research-loop.md`。它是实际流程——在任务开始时读它，而不是等你已经花了钱之后。

其形：

- **Round 0 —— 先侦察，评档，再归纳。** 定义问题，`evidence.py init`（行业 / 市场调研传 `--genre industry`——genre 在 `init` 设定，驱动 figures-expected 的 `check`），跑 3–4 个 `paper_qa_search_pro` probe（`query_type: "auto"`，约 ¥2.80）——按对象与结构化过滤器分开，而非换措辞——用免费 `paper_info` 做分诊，给留下的候选买 `paper_detail`，然后登记复杂度档位（`evidence.py tier --level simple|moderate|complex --reason …`——simple 2 方向 × 1 补轮 × 3 轮、moderate 3 × 2 × 6、complex 5 × 3 × 10；自登记起引擎**拒绝**一切超额的大纲/轮次登记），再从返回内容归纳出 2–4 个带编号的顶层小节，每个含 2–4 个子小节，其中恰有一个是 `disagreement` 子小节。写作目标不在此设定——上游的章目标在报告期对着整堆素材分配，收尾步骤照做（从素材面出发，按素材充分度）。用户给了篇幅，现在就换算成字当量以 `--length-budget` 登记（一页 ≈ 700,上限钳在 80000）。检索前不要臆造小节标题。
- **图表主题——大纲定型后规划，再专题检索至数据充足。** 通读大纲，判断哪些位置"需要且可以"插图；每个图表主题记一条 `evidence.py figure plan --section <id> --topic <要回答的定量问题> [--type]`（Genre B 报告零规划会触发 `figure_plans_industry_expected` 告警）。**派发在记计划的当场，不在作图时，且一次全派**：能派子代理的宿主，每个开放计划当场派一个图表子代理，整批并发派出、绝不逐个等；每个任务书带检索预算——至少 10 次调用（网页加 AMiner 合计），不到这个数不得说"无公开数据"；契约与阅读子代理相同——任务书进、记录出；控制台是台账唯一写入者，由它入账记录并跑渲染链（`datum add --plan` → `figure add --charted-by agent` → `chartrender.py` → `figure mark-rendered`），规则见 `references/chart-guide.md` §Who charts；主会话自己跑检索循环仅限没有子代理能力的宿主，且成图时必须 `figure add --charted-by controller --charted-reason <为什么没派子代理>`——例外须自证，附录 C 会报告每张图由谁完成。图型按 `references/chart-guide.md` 的选型矩阵定——常见定量问题对应六种模板形状，其余走 `--code` 脚本；照片、架构图、流程图没有通道，用文字或表格表达。每轮检索同时服务开放中的规划：按主题搜数字（数字密集文档类型优先；语料类主题直接从台账著录聚合闭环），读到就 `datum add --plan fpN` 记点，检索到数据能组成一张完整的图为止（≥3 个是引擎底线不是完整标准）——`figure add --from-datums … --plan fpN` 成图闭环。确实无公开数据的主题带原因放弃（`figure plan --abandon`），在局限节如实交代。
- **每轮** —— 按小节与开放规划检索（AMiner + web）→ 把结果用 `--probe <id>` 不打标地 pipe 进来，再只给留下的打 `--section <id>` 标、`drop` 掉噪声 → 读（免费 `paper_info` 分诊先于付费 `paper_detail`；**能派子代理的宿主把阅读也委派出去**：每个阅读子代理领同一小节的一批 keeper（3–6 条），分诊完即派——任务书=小节主题+本轮缺口+这批源的著录行+记录纪律，交付物=记录本身，父会话经 `add`/`claim`/`fulltext` 原样入账；失败的读者重试至多 3 次，再失败由父会话自己读这批——绝不造假记录；无子代理的宿主自己读。两种形态下都一样）留下的源**读的当场写 300–800 字综述级 `note`,一批一清、绝不收尾补记**——零笔记的活源会被 `check` 直接拦下（读或扔,零豁免——图表数据源、语料统计源也不例外）,被引源笔记不足 300 告警；claim 随记逐字 `--evidence` 摘录，**成段 100–500 字**，全碎告警；读了全文的小节写下方向 `memo`（600–1200 字，即该节叙事底稿））→ `evidence.py gaps` → **对着引擎算出的信号收轮**：`signals` 打印评估面（来源多样性、证据质量、核验统计、最近五次决策——每个数字由引擎算出，未记录的输入如实说未记录），`round --why-stopped … --direction … --next-query …` 落轮次小结（空手轮显示为 `rounds_without_yield`——如实写，绝不报"已充分"），**本轮新增的有据 claim 当场吃核验判定**（见下——紧随其后的决策要读到降级），`decide --action stop|continue|rerun… --reason …` 记录决策。决策规则在 `references/research-loop.md` §5——投入配档位、深度看备忘录、单源依赖必补、矛盾先解决、历史不重复、**停轮理由逐条交代存量告警**(本轮已处理/权衡后接受/移交局限)——档位轮数上限到点即拒。
- **轮界核验、写前收口** —— 两道引擎闸门收口。逐字证据：凡要承载引用的 claim 都带 `--evidence` 摘录（**至少 8 字符的句子片段**——孤立单字或裸数字会被拒绝），引擎对来源已存文本做空白不敏感子串校验；对不上=转述冒充引文——被标记，claim 降级为背景信息。引证忠实性：记 `evidence.py verify --claim cN --supported|--unsupported --confidence 0-1 --reason …`（疑罪从无——只揪明确矛盾：数字不在、实体错、时点错；不支撑判定必须带理由，且理由逐条各写——同一段模板文案刷满整批会被引擎标记）。**谁来判**：能派子代理的宿主对全部有据 claim 冷判——裁判只看论断（≤1200 字）、逐字摘录（每条 ≤1500 字）与来源标题（不带题目、不带其他 claim、不带预期结论），负担得起时一 claim 一判（批量裁判看得见兄弟 claim——是声明的妥协，批要小），同一疑罪从无尺度，其 `--batch` JSON 原样入账；裁判失败/超时/输出畸形记为未定论——绝不算通过、也绝不由你补判；整批二选一，方法散文如实声明核验形态。无子代理的宿主自判并声明——引擎闸门（0.6/半数上限）两种形态一视同仁。闸门由引擎执行：置信度低于 0.6 的"不支撑"算"拿不准"放行；一次核验批降级不超过半数。被降级的 claim 在 `render --final` 中带标记、不得承载引用；`check` 以 `claims_awaiting_verify` 警告直至每条有据 claim 都有判定，附录 C 报告通过/降级/未定论分布。**时序**（上游在波次边界、评估器之前跑核验，降级自然触发补检）：每轮新增有据 claim 在收轮时判掉，`signals`/`decide` 之前——写前那遍只是清尾。
- **收尾** —— `evidence.py check` 必须退出 0，随后 `evidence.py render --final` 给出台账视图（编号、每小节 claims、稳定的台账源编号），`evidence.py render --material` 给出**写作准备面**：每小节的现有素材量（**此时**定 `target_chars`——即上游的报告期时序；用 `outline set --force` 以同一结构重登记，节 id 按位置稳定、挂节不断。**总量先行**：用户未给篇幅则常态 2–3 万、至多 5 万、以讲透为准——素材只负责**分配**厚薄，各章不必等长，厚的多写薄的少写；素材是分配器不是封顶——绝不按"每节素材的一小半"做算术砍目标，降总量的唯一合法理由是素材覆盖不了主题且须在局限交代（素材薄先回检索，不是先降目标）；`check` 两种坏耦合都观测:`write_targets_over_material` 与 `sections_under_targeted_vs_material`）、素材块（claims 带 `[@n]` 标记、逐字证据、来源笔记——笔记就是素材通道）、按 claim 引用次数排序的回读清单（每节至多 5 篇核心原文，写该节前用 web 工具回读）、**未引用池**（挂节但无 claim 引用的源——可引池是整个台账不是 claim 集；池里的源要用先读，不用就 drop；**图的语料源也是池员**——解读聚合图的正文要点名其构成源，上游没有"只进图不进文"的源类）、最新备忘录——**草稿按顶层节逐节写——动笔每节前只取该节的素材块、未引用池与该节目标，写完再进下一节（上游逐章生成，每章的提示词只装该章素材——对着整堆素材一口气写正是薄节的来源），引用一律用 `[@n]` 占位符（n 为台账编号；每源每节 1-2 处，标在承载其关键事实的句子上，过渡与自己的综合判断不挂；核心对象每个写足一段，次要对象合并一句带过），绝不把 `render --final` 贴进正文**（不要 `c1` id、不要 `_来源：` 行、不要 `_（分歧）_` 标签、不要裸 `冲突：` 项目符号），末尾放一个参考文献标题，内含一行 `{{references}}` 占位符。claims 是骨架不是上限：每个小节要把其中的 claims 展开成完整段落，写进台账里已付费换来的机制、数字与细节（论文摘要、专利全文笔记、web 页面事实），并向该节登记的写作目标写——只复述 claim 一句话是缺陷；`render --renumber` 对任一小节正文不足 300 单位（中文字符或英文词，引用/标题/图片/表格不计）硬报错，与"引用指向空处"同级。接着 `render --renumber --draft <path> --out <path>` 把占位符替换为按正文首现递增的稠密引用号（相邻引用以空格分隔 `[3] [7]`），把参考文献槽填成只含被引源的文献表，在交付报告旁写一个 citation-map sidecar，并**记录**正文当量与登记目标的偏差进台账（`length_report`——±20% 容差,总量与每节,只记录不重写:供复盘与下一轮定目标,绝非闸门——绝不为了凑字数注水）——`[@n]` 指向未知或已丢弃的源会硬报错。**偏差超容差且素材未尽的小节不算写完：回素材块与未引用池续写该节，重跑 `render --renumber` 再量——不带只写一半的报告交付。**最后 `render --appendix --out auto --citation-map <sidecar>` 写出各附录表（附录 D 为报告↔台账编号对照）并返回报告要引用的那一行——附录最后渲染、出自封账的台账：其后任何入账（晚 claim、核验、figure）都须重跑附录，绝不手改其表格。若报告有 figure，注册 → 渲染 → 回写这条链必须先跑过——正常路径是轮中按图表子代理交付的记录、由控制台完成并回写；到收尾还有计划没成图、又没有 `--charted-by controller --charted-reason` 声明，说明图表阶段的派发被跳过了——先补流程（派发，或声明例外）再收尾。`render --final` 为每个已登记 figure 输出一个 `_[FIGURE fN] …_` 占位符，你在组装草稿时用图片嵌入替换它。对于行业报告，figure 和一张竞品对比表是预期项，不是可选项。

快速开始：

```bash
python3 "${CLAUDE_SKILL_DIR}/scripts/evidence.py" init --topic "RAG evaluation"
# 行业 / 市场调研：
# python3 "${CLAUDE_SKILL_DIR}/scripts/evidence.py" init --topic "中国大模型行业调研" --genre industry

python3 "${CLAUDE_SKILL_DIR}/scripts/evidence.py" probe --axis topic --via paper_qa_search_pro \
  --query "retrieval augmented generation evaluation"
python3 "${CLAUDE_SKILL_DIR}/scripts/aminer_open.py" --api paper_qa_search_pro \
  --params '{"query":"retrieval augmented generation evaluation","query_type":"auto","year_from":2023,"sort":"balanced"}' \
  | python3 "${CLAUDE_SKILL_DIR}/scripts/evidence.py" add --aminer --probe p1
python3 "${CLAUDE_SKILL_DIR}/scripts/aminer_open.py" --api paper_info --params '{"ids":["<id>","<id>"]}' \
  | python3 "${CLAUDE_SKILL_DIR}/scripts/evidence.py" add --aminer
python3 "${CLAUDE_SKILL_DIR}/scripts/evidence.py" drop --source 7 9 --reason "off topic"
python3 "${CLAUDE_SKILL_DIR}/scripts/aminer_open.py" --api paper_detail --params '{"id":"<id>"}' \
  | python3 "${CLAUDE_SKILL_DIR}/scripts/evidence.py" add --aminer

python3 "${CLAUDE_SKILL_DIR}/scripts/evidence.py" outline set --json '[
  {"title":"Evaluation methods","from_probes":["p1"],"children":[
    {"title":"LLM-judge metrics"},
    {"title":"Disagreement: judge validity","kind":"disagreement"}]}]'

python3 "${CLAUDE_SKILL_DIR}/scripts/evidence.py" add --section 1.1 --json '[{"kind":"paper","id":"<id>","title":"..."}]'
python3 "${CLAUDE_SKILL_DIR}/scripts/evidence.py" claim --section 1.1 --supports 1 4 \
  --text "LLM-judge metrics dominate reported RAG evaluation since 2023"
python3 "${CLAUDE_SKILL_DIR}/scripts/evidence.py" gaps
```

## 调用脚本 —— 以及台账在哪

通过 `${CLAUDE_SKILL_DIR}` 调用脚本，这样脚本路径不依赖 cwd。skill **不拥有任何台账位置**——路径由宿主选定。当没有任何一方指定时，默认把本次运行的工作区设在当前项目下的 `outputs/<主题slug>-<YYYYMMDD-HHMM>/` 每运行一目录（台账在其根、图在 `figures/` 下，各次运行互不覆盖），解析成绝对路径并告诉用户台账在哪——这是宿主施加的默认，不是引擎的假设。设一次，`export DR_LEDGER=<workspace>/evidence-ledger.json`，之后每个 `evidence.py` / `evaluate.py` 调用都从 `$DR_LEDGER` 读（或显式传 `--state` / `--ledger`）。skill 不假设 `knowledge/`、`.zscience/` 或任何目录——持久化与 scratch 是宿主的职责；台账是 skill 的输出（以及可选的输入），不是 skill 拥有的文件。绝不把台账写到 `${CLAUDE_SKILL_DIR}` 下（skill 树是只读源）。

台账*就是* skill 的结构化输出——一份自描述、带版本的 JSON。skill 产出它就止步：不导出、不转换、不把它适配到任何其他系统的 schema。任何想要另一种形态的研究成果的系统（context store、RAG 索引、简报）都在 skill 之外自己读台账并做那件事。

```bash
# 台账视图 —— 用来对照写草稿的content基准（编号是台账 n）
python3 "${CLAUDE_SKILL_DIR}/scripts/evidence.py" render --final
# 写作准备面 —— 每节：写作目标、素材块（claims + 证据 + 来源笔记）、
# 回读清单、备忘录；草稿从这份素材出发写
python3 "${CLAUDE_SKILL_DIR}/scripts/evidence.py" render --material
# 交付报告：[@n] 占位符换成按首现递增的 [N]，参考文献槽变成只含被引源的
# 文献表，并写一个 citation-map sidecar
python3 "${CLAUDE_SKILL_DIR}/scripts/evidence.py" render --renumber \
  --draft <draft.md> --out <report.md>
# 附录（检索日志 / 花费 / 数据与方法 / 引用号对照）写在台账旁边
python3 "${CLAUDE_SKILL_DIR}/scripts/evidence.py" render --appendix --out auto \
  --citation-map <report-citation-map.json>
# skill 对台账的自有质量报告 (§7.13)
python3 "${CLAUDE_SKILL_DIR}/evaluation/evaluate.py" --ledger "$DR_LEDGER"
```

## 花费控制

- 免费优先：付费之前先用免费的发现与消歧端点；免费 `paper_info` 先于付费 `paper_detail`。
- **按查询形态路由。** `paper_qa_search_pro`（¥0.70）是主题与多过滤搜索的默认项，也是 Round 0 侦察所用。当查询已经是结构化过滤（作者、机构、期刊，或带引用/年份排序的单个受控关键词）时，降到 `paper_search_pro`（¥0.01）。
- **以 `query_type: "auto"` 发送查询——即 query 模式。** 相比非 LLM 模式约 5 秒 vs 0.4 秒，远在 30 秒超时之内（付费端点不自动重试），召回更好。仅在字面词匹配时降到 `topic`，并在那时用 `all_terms` 锚定概念。按对象与过滤分 probe，绝不按换措辞分。
- **读你所引——全文优先。** 搜索结果不带摘要；免费 `paper_info` 切片约 190 字符；`paper_detail` ¥0.01 给全摘要 + 关键词；而开放获取的**原文**（arXiv PDF/HTML/TeX、Google Patents、出版商 OA 页）用宿主 web 工具读取，并经 `evidence.py fulltext --source N --url … --via …` 记账——免费，不占 AMiner 预算；从原文提取的数字写进该次记录的 `--note`，数字溯源检查以 note 为凭。确实无公开原文时记录降级：`fulltext --unavailable`。当一条结论依赖的来源从未被好好读时，`check` 以 `cited_sources_without_detail` 警告；当被引论文/专利既未读全文也未标记不可得时，以 `cited_sources_without_fulltext` 警告——静默降级与没去找无法区分。
- **专利质量靠筛选，不靠排序。** 专利通道只按相关度返回（不像论文通道可按引用/年份排序），检索侧把池子拉宽（`size` 到 100、翻页），详情入库后按等级筛：发明授权 > 有受让人的申请公开 > 实用新型与无受让人的申请。`check` 以 `claims_weak_patent_sole_support` 警告量化结论单源压在低等级专利上；`render --renumber` 以 `weak_patent_numbers` 报告整句引用全是低等级专利的数字——交叉验证，或在报告里明说是单方设计主张。
- **每次结果都看 `warnings` 和 `total`。** `aminer_open.py` 把它们从响应里提出来；一条 warning 意味着跑的查询不是你发的那个。
- 付费调用前用 `--dry-run` 或 `--batch` 估算整条计划链。`add --aminer` 把实际花费累计进台账；一个你丢弃了命中的付费调用仍需 `evidence.py spend`。
- 一个完整学者画像约 ¥6.00。到 ¥10.00 展示调用计划并等确认，然后传 `--confirm-high-cost`。累计到 ¥20.00 时，`check` 阻断——停下并交付部分结果。

## 预算

2–4 个顶层小节 · 每个 2–4 个子小节、其中一个是 disagreement 子小节 · 3–4 个 probe（约 ¥2.80）· 大纲前用 `evidence.py tier` 登记复杂度档位（simple 2×1×3 · moderate 3×2×6 默认 · complex 5×3×10——方向 × 补轮 × 轮数；引擎拒绝超额登记，`--wasted` 轮记录但不计数）· 每轮 ≤2 次付费 `paper_qa_search_pro` 调用且 ≤3 次 web 调用，¥0.01 的 `paper_search_pro` 不限 · 每个顶层小节 ≤8 个候选 · 每任务 ≤50 次付费 detail 调用 · ≤5 次 `paper_relation` 扩展 · 每报告 ≤6 个 figure（每小节 ≤2；Genre A 可选、Genre B ≥1 预期；无花费——由 `chartrender.py` 本地渲染，当数值数据单薄时 `timeline` 模板跑按日期的事件）· ¥10.00 确认阈值 · ¥20.00 硬上限。一次典型运行落在 ¥4–6 附近，其中搜索约占 92%——省搜索，不省摘要。

## 失败处理

- **空搜索**：在*不同轴*上重述一次——不同的主题短语或结构化过滤，而非换同义词——然后报告缺口，而不是第三次尝试。
- **歧义实体**：展示顶部候选并让用户选。绝不给每个候选都买 detail。
- **API 错误**：报告公开的端点名与可操作信息；绝不暴露 header 或凭据。
- **挨饿的小节**：把它并入邻居，而不是为对称去买搜索。单薄的子小节就写成单薄、并标注单薄。
- **证据单薄**：`check` 失败，于是收窄结论并交付一份明确受限的报告。绝不用记忆填补缺口。
- **无 web 工具**：继续用 AMiner 并在报告的 Limitations 小节记录该限制。

## 输出

按 `references/report-format.md` 写最终报告。两种 genre，从任务框架里选：一份**学术综述**（默认——文献综述、研究全景、实体调研）和一份**行业报告**（行业 / 市场调研："行业调研"、"市场格局"、"竞争格局"）。无论哪种 genre，报告都是**你从台账 claims 写出的散文——不是把 `render --final` 贴进正文。** `render --final` 是台账视图：从一次运行里取小节 / 子小节编号、每小节按序的 claim 集合，以及稳定的台账源编号；把每个子小节写成承载其 `[@n]` 引用占位符的流畅散文，并在对比多个实体时用表。`render --renumber` 把草稿变成交付报告——按正文首现递增的 `[N]` 编号、只含被引源的文献表，以及一个 citation-map sidecar。不要把台账脚手架——claim id（`c1`）、来源池行（`_来源：`）、`_（分歧）_` / `_（解读）_` 标签，或裸 `冲突：` 项目符号——贴进报告；那些是台账内部物。附录**不是**报告的一部分：`render --appendix --out auto` 把附录 A（检索日志）、B（调用与花费）、C（数据与方法）写到台账旁的一个文件，你只往附录 C 追加几条台账无从知晓的方法事实。probe id、检索轴、API 名、价格与筛选计数都待在那个文件里，绝不进报告。对于**行业报告**，骨架是咨询形态（执行摘要 / 市场规模 / 带对比表的玩家格局 / 竞争动态 / 技术与专利 / 供应链与算力 / 政策 / 展望），检索以 web 为先（市场数据、融资、芯片、政策），AMiner 作为技术 / IP 通道，且至少一张 figure（市场份额 / 玩家 / 时间线）加一张玩家对比表是预期项，不是可选项。`render` 按台账 topic 的语言输出其标题；照印参考标题与条目，而非翻译它们。

## 规则

- **台账里没有的，不得进报告。** `render` 没打印的小节不存在；没有台账来源的 claim 不出现。
- **"figure" 的两层含义。** 小写 *figure*（如 `claims_with_unsourced_numbers` 里的）指一条结论里引用的数字——它必须出现在某个被引来源里。一个已登记的 *Figure*（`figure add`，id `f1…`）指渲染成 PNG 的图表——它的 `data` 受同一数字溯源规则检查（`figures_unsupported_numbers`）。两者都取自台账数字；都不许显示台账未背书的数字。
- **对抗式核验是强制的。** 每个顶层小节都有一个 `disagreement` 子小节；每条关键结论都对照一个可能反驳它的来源做了检查。
- **证据是逐字的，落地即核验。** 承载引用的 claim 记录 `--evidence` 摘录（引擎对来源文本校验），并在其所属轮次收轮时获得 `verify` 判定（支撑与否 + 置信度）——降级发生时检索还有预算补救。被任一闸门降级的 claim 是背景信息——留在台账里，但绝不在报告中承载引用。
- **不伪造引用。** 每条引用必须是 `aminer_open.py` 返回的真实实体，或经 `WebFetch` 实际抓取的页面。
- **大结果落盘。** 当搜索结果超过 20 条或裸 API 输出超过 5000 字符时，把中间结果写到宿主选定的 scratch 路径（如 `$DR_WORKDIR/scratch/`），而非留在上下文里。skill 不假设 `.zscience/` 或其他 scratch 目录。stdout 只给短状态：`"Found N results, saved to <path>"`。
