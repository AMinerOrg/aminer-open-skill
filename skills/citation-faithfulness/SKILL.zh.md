---
name: citation-faithfulness
version: 1.1.0
author: AMiner
contact: report@aminer.cn
description: >
  [Activation] Use this skill when the user gives a paper PDF and asks whether its in-text citations are FAITHFUL to what the cited sources actually say — e.g. "check if this paper misrepresents its references", "does citation [12] actually support this claim", "verify the citations are not distorting the sources", "核查引用是否忠于原文", "有没有曲解参考文献".
  [Capability] Reads the PDF locally (Read tool), extracts every in-text citation together with the specific claim it supports, retrieves each cited source from the open web (WebSearch/WebFetch; arXiv full text or abstract), and has the agent judge each claim–source pair as SUPPORTED / PARTIALLY_SUPPORTED / NOT_SUPPORTED / NOT_IN_SOURCE / UNVERIFIABLE, with an evidence quote and confidence. No API key required.
  [Routing] Do NOT use this skill to check whether a reference EXISTS / is hallucinated (a real paper vs a fabricated one) — that is `pdf-citation-verifier`. Do NOT use it for general paper search (`aminer-free-academic` / `aminer-academic-search`) or citation-intent graphing (`paper-source-trace`). This skill answers one question only: does the cited source actually back up the claim the paper attaches to it.
metadata:
  {
    "openclaw":
      {
        "emoji": "🔎",
        "requires": {
          "bins": [],
          "env": []
        },
        "primaryEnv": "AMINER_API_KEY"
      }
  }
---

# 引用忠实性核查（Citation Faithfulness Checker）

核查一篇 PDF 论文里的正文引用是否**忠于被引原文**。凡是论文写"根据 [X]……"或"[X] 报告了……"的地方，本 skill 都去找 X 的原文实际怎么说，判断论文的声称是否真的被支持——用来抓**曲解、结论说反、张冠李戴、数字对不上、原文根本没这么说**这类错误。

本 skill 是 **agent 驱动**：没有上传服务、不带任何脚本。由 Claude 自己读 PDF、用自带联网工具检索原文、并亲自套用判定 rubric。可用自然语言或 `/citation-faithfulness` 触发。

## 它做什么、不做什么

| | 本 skill（`citation-faithfulness`） | `pdf-citation-verifier` |
| --- | --- | --- |
| 问的问题 | 被引原文**是否真的支持这个声称**？ | 这条参考文献**是否真实存在**？ |
| 抓的错 | 曲解、说反、数字错、过度声称 | 幽灵文献、伪造 DOI |
| 手段 | 读 PDF + 联网取原文 + agent 判定 | 上传 PDF 给 AMiner 服务 |
| 密钥 | 免 key | 需 `AMINER_API_KEY` |

如果用户其实想查"引用是否真实存在/是否幻觉"，请停下并改用 `pdf-citation-verifier`。

## 判定标签

每一个被核查的「声称—原文」对，恰好给一个判定（JSON/表格里保留英文标签，用用户语言解释）：

- `SUPPORTED` 支持 — 原文明确说了论文归因给它的内容。
- `PARTIALLY_SUPPORTED` 部分支持 — 原文支持声称的一部分，但论文夸大了、缩小了、或加了原文没有的限定。
- `NOT_SUPPORTED` 不支持（曲解）— 原文谈到了这个话题，但说的是**不同甚至相反**的东西（真正的曲解）。
- `NOT_IN_SOURCE` 原文查无此说 — 拿到的原文（**全文**）里根本没有这个被声称的事实/结果。
- `UNVERIFIABLE` 无法核实 — 原文取不到，或只拿到摘要而声称指向摘要没覆盖的细节。**这不是指控**，意思是"我们没能核对"，不是"引用错了"。

每条判定附带：来自原文的 `evidence` 证据引句（保留原文语言）、用用户语言写的 `reason` 理由、`retrieval_level` 检索层级（`full_text` / `abstract_only` / `metadata_only` / `not_found`）、`confidence` 置信度（high / medium / low）。完整判定策略见 `references/rubric.md`。

## 硬限制 —— 请向用户交代一次

联网检索经常**只拿得到摘要**、拿不到被引论文全文（付费墙、正文不公开）。你必须遵守其后果：

- 若某声称引用的是原文正文深处的数字/图/细节，而你只拿到摘要 → 判 `UNVERIFIABLE`，**绝不判 `NOT_SUPPORTED`**。没真正读到的引用不许定罪。
- 本 skill 能可靠抓到的是**摘要即可证伪**的错（结论说反、张冠李戴、头条数字对不上、被摘要直接反驳的声称）；藏在付费正文深处的偏差不保证抓得到。
- 用户本地 Zotero 库能提供全文、核查会强得多，但本 skill 按设计只走**联网**检索。

## 文件结构

- `SKILL.md` / `SKILL.zh.md` — 英文 / 中文 skill 定义（本文件）。
- `commands/citation-faithfulness.md` — slash 命令入口。
- `references/rubric.md` — 五档判定 rubric（改编自 `paper-source-trace` 的证据协议）。
- `references/output-schema.md` — 返回值契约：报告的精确 JSON 结构（顶层对象 + 单条声称记录 + 不变式）。
- 无脚本、无 `requirements.txt`：本 skill 只用 Read、WebSearch、WebFetch 三个工具。

## Pre-flight 检查

运行前确认：

1. **PDF 输入** — 用户给了存在的本地 `.pdf` 路径。若只报了论文名没给文件，主动追问。**绝不自行编造或下载论文来核查。**
2. **工具可用** — 本 skill 需要 `Read`、`WebSearch`、`WebFetch`。若环境无联网，停下并告知：忠实性核查必须取到被引原文，无联网时只能给 `UNVERIFIABLE`。
3. **范围预期** — 全覆盖一篇 40 篇参考的论文≈40+ 次联网检索。大批量前先提醒用户并提供缩小范围选项（见参数）。

`AMINER_API_KEY` 为**可选**。若已设置，可用 `GET https://datacenter.aminer.cn/gateway/open_platform/api/paper/search?title=...`（请求头 `Authorization: ${AMINER_API_KEY}`、`X-Platform` 写成当前宿主：`claude-code` / `cursor` / `codex` / `openclaw` / `unknown`、`X-Skill-Name: citation-faithfulness`、`X-Skill-Version` 为本文件 frontmatter 的 `version`）更快解析某条参考文献的 DOI/摘要。仅作增强——不设也能完整运行。**禁止回显 token 值。**

## 执行流程

按序走以下五阶段。全部用你自己的工具做，任何阶段不许编造。

### S0 — 摄入 PDF

用 `Read` 工具读 PDF（每次渲染至多 20 页；长论文按页范围多次读，如 `pages: "1-20"` 再 `"21-40"`）。务必同时拿到**正文**和**参考文献表**（通常在末几页）。若抽取有噪声（双栏、表格、连字），记录之——噪声抽取按 rubric 降低置信度。

### S1 — 抽取「声称—引用」对

逐句扫正文，对每处 in-text citation，记录它支撑的**具体声称**——不只是"这里有个引用"。构建列表：

```
{ claim_id, claim_text, citation_sentence, section, cited_refs: [标记...], claim_type }
```

- `citation_sentence` — 引用所在句子，保留论文**原文语言**（不要翻译）。
- `claim_type` — 取值：
  - `specific` — 归因于原文的事实、数字、数据集、结果或方法（**最高优先、最可核验**）。
  - `method` — "我们采用/扩展了 [X] 的方法"。
  - `background` — 泛指/前人工作性质的指向（**可核验性低；单纯一句"见 [X]"往往不是可核查声称**，标注并降优先）。

优先 `specific` 类。没有归因具体内容的背景性指向应列出但通常判 `UNVERIFIABLE`（没有具体可查的东西）——如实说明，别硬编一个声称。

### S2 — 解析参考文献表

把每个正文标记（`[12]`、`(Smith et al., 2021)`、上标等）映射到其完整参考文献条目 → 标题、作者、年份、venue、DOI、arXiv id。**按被引工作去重**：`[12]` 被引五次，只检索一次、五处声称复用同一原文。若某标记无法匹配到文献条目，标 `unmatched_reference: true` 并把该声称判 `UNVERIFIABLE`。

### S3 — 联网取每篇原文

对每一篇**去重后**的被引工作，按下列优先级取原文，并记录你达到的 `retrieval_level`：

1. **arXiv** — 若条目有 arXiv id 或 arXiv 搜得到：`WebFetch https://arxiv.org/abs/<id>` 取摘要；当 `specific` 声称需要正文细节时，再试 `WebFetch https://arxiv.org/html/<id>`（或 `ar5iv.org/abs/<id>` 的 HTML 镜像）取全文 → `full_text`。
2. **开放落地页** — 否则 `WebSearch "<标题>" <一作> <年份>`，再 `WebFetch` 命中最好的一条（出版商摘要页、ACL Anthology、OpenReview、PMC、Semantic Scholar 页）。出版商页通常只给 `abstract_only`；开放获取 HTML/PDF 给 `full_text`。
3. **可选 AMiner 增强** — 若设了 `AMINER_API_KEY` 且网搜结果单薄，用上面的 AMiner `paper/search` 接口解析标题匹配 + 摘要。
4. 合理尝试后仍无可用内容 → `retrieval_level: not_found`。

每篇最多跟进少数几个链接，控制成本、及时收手。**绝不编造你没有 fetch 到的页面内容。**

### S4 — 判定每个「声称—原文」对

套用 `references/rubric.md`。对每条声称，将 `claim_text` 与取到的原文内容比对，从五档里给一个判定，附 `evidence`（原文引句，原语言）、`reason`、`retrieval_level`、`confidence`。

**铁律**（不许违反）：

- 只有 `full_text` 检索才能支撑 `NOT_IN_SOURCE`。只拿到摘要且声称指向正文细节 → `UNVERIFIABLE`。
- 只有当原文确实说了**不同/相反**且你能引出原句时，才判 `NOT_SUPPORTED`。缺乏佐证 ≠ 矛盾。
- 只有标题/元数据、没有取到原文正文时，绝不给 high 置信。
- 绝不编造证据引句。没取到就是 `not_found`、判 `UNVERIFIABLE`。
- 原文引句保留原语言；`reason` 用用户语言写。

### S5 — 出报告

先给汇总，然后**完整输出每一个非 `SUPPORTED` 项的全部内容**，按严重度排序：`NOT_SUPPORTED` 与 `NOT_IN_SOURCE` 在前，然后 `PARTIALLY_SUPPORTED`，再 `UNVERIFIABLE`。完整 JSON 报告**必须**写到 `output` 路径（用户没给路径时默认写到当前工作目录，见参数）。见结果展示。

## 参数（来自自然语言或 `/citation-faithfulness`）

| 字段 | 取值 | 默认 | 含义 |
| --- | --- | --- | --- |
| `pdf` | PDF 绝对路径 | 必填 | 要核查的论文 |
| `scope` | `all` / `specific-only` / `refs:1,12,23` | `all` | `all` = 每处正文引用；`specific-only` = 只查事实/数字/结果类声称；`refs:...` = 只查这些参考文献编号 |
| `max-refs` | 整数 | 无 | 检索的去重原文数上限（成本护栏） |
| `output` | 路径 | `./citation-faithfulness-<pdf文件名>.json` | 完整 JSON 报告的写出路径。**必写**——用户没给路径时，默认写到当前工作目录、按 PDF 文件名命名。 |

用户默认选**全覆盖**。论文参考很多、在意成本时，主动提供 `specific-only` 或 `max-refs`。

## 运行约束

- **绝不编造判定或证据引句。** 读不到的原文就是 `UNVERIFIABLE`，没有例外。
- `UNVERIFIABLE` 不是论文的过错——对用户说明时，务必把"我们没能核对"和"引用错了"区分开。
- 把 `NOT_SUPPORTED` / `NOT_IN_SOURCE` 当作**待人工复核的标记**，不是最终指控。作者可能引的是另一版本、后面的章节，或你匹配错了原文——都要说明。
- 尊重联网工具上限：每篇限跟进链接数、按被引工作去重、报告有多少篇 `not_found`。跳过的引用绝不静默丢弃——列出来。
- 禁止回显 `AMINER_API_KEY` 的值。

## 结果展示

先汇总，再明细表。

**汇总**
- 论文标题 + 找到的正文引用总数 + 核查的去重原文数。
- 各档计数：`SUPPORTED` / `PARTIALLY_SUPPORTED` / `NOT_SUPPORTED` / `NOT_IN_SOURCE` / `UNVERIFIABLE`。
- 检索覆盖：多少篇达到 `full_text`、多少 `abstract_only`、多少 `not_found`——让用户知道核查到多深。
- 若覆盖较浅，加一句诚实说明（如"40 篇里 18 篇仅摘要；其正文级声称为 UNVERIFIABLE，并非已核实通过"）。

**每个非 `SUPPORTED` 项完整输出**——不是只给一行表格。对每条 `NOT_SUPPORTED` / `NOT_IN_SOURCE` / `PARTIALLY_SUPPORTED` / `UNVERIFIABLE`，按严重度顺序（`NOT_SUPPORTED` 与 `NOT_IN_SOURCE` 在前，它们是可行动的发现）打出完整块：
`claim_id` · 章节 · 判定 · `retrieval_level` · `confidence`，随后是完整的 `citation_sentence`（论文原语言）、被引工作、`evidence` 证据引句（原文语言；未取到要明说）、`reason` 理由、以及 `notes`。不许截断、不许一笔带过——用户必须不打开 JSON 就能独立评判每条被标记的引用。

**`SUPPORTED` 项**只报计数（必要时附几条亮点简述）；其完整记录保留在 JSON 里。

**然后**：**必须**把完整 JSON 报告写到 `output` 路径——用户没给路径时，写到当前工作目录、命名为 `citation-faithfulness-<pdf文件名>.json`——并告知用户路径。这是强制步骤，不以用户是否索要为条件。

## 返回值

报告汇总为单个 JSON 对象，定义见 `references/output-schema.md`——顶层含 `paper` / `run` / `summary` / `claims[]` / `flagged` / `skipped`，每处被核查引用对应一条声称记录。该对象**必写**入 `output`（默认：当前工作目录下的 `citation-faithfulness-<pdf文件名>.json`），屏幕展示也由它渲染。严格遵循该 schema 的字段名、枚举值与不变式，使返回值跨运行稳定。
