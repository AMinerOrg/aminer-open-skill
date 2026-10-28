---
name: paper-insight-classification
version: 0.1.0
author: Community contribution
description: >
  [Activation] Use this skill when the user gives a paper (PDF / Word / text) and asks how insightful it is relative to the literature it cites — e.g. "evaluate the insight of this paper", "how much does this paper add beyond its references", "extract and classify the opinion sentences", "compare the depth of human-written and AI-generated surveys", "评估论文的 insight / 洞察 / 见解", "抽取观点句并分类", or mentions InsightEval.
  [Capability] Implements the InsightEval method (SIGIR'26 demo). Scripts parse the paper into sentences with sections and citation markers and build labeling batches; the agent classifies every sentence as context / citation / opinion, then scores each opinion sentence against evidence from the references it cites on Depth / Breadth / Height (1-5) and types each section as descriptive / comparative / analytical. A final script produces a paper-level insight report (JSON / Markdown / CSV) with composite scores, low / medium / high levels, distributions, top and bottom sentences and caveats. Optional evidence lookup uses free scholarly APIs; no API key required.
  [Routing] Do NOT use this skill to check whether citations are faithful to their sources (`citation-faithfulness`), whether references exist (`pdf-citation-verifier`, `structured-reference-audit`), or to extract the reference list itself (`paper-reference-extraction`, whose `references.json` is the recommended input here). It judges the text relative to its cited references; it does not judge whether the experiments or conclusions are correct.
metadata:
  {
    "openclaw":
      {
        "emoji": "💡",
        "requires": {
          "bins": ["python3"],
          "env": []
        }
      }
  }
---

# 论文 Insight 分类（InsightEval 方法）

insight 不等于新颖：它是论文相对于**被引文献**带来的**理解增量**。流程对应 InsightEval 的四个 Stage：

1. **句子** —— 每句 → `context`（背景）/ `citation`（只概述前人）/ `opinion`（作者的解读、批评、综合）。
2. **证据** —— 为每个观点句收集它所引用文献的标题与摘要。
3. **评分** —— 把观点句与证据比较，给 **Depth 深度 / Breadth 广度 / Height 高度**（1–5）打分，合成综合分和 `low / medium / high` 等级。
4. **报告** —— 论文级统计、章节类型与等级、高/低洞察句、总体评价。

脚本负责解析、切批、证据检索和汇总；**分类与评分需要判断力，由你完成**。开始标注前先读 [references/rubric.md](references/rubric.md)（英文）：里面有定义、边界情形、评分锚点和示例。

## 环境要求

- Python ≥ 3.10，`pip install -r requirements.txt`（PyMuPDF）。
- 输入：`.pdf`、`.docx`、`.txt`、`.md`。扫描件需先 OCR（例如 `aminer-pdf-ocr`）。
- 只有可选的证据检索（`fetch_evidence.py`）需要联网。

## 工作流

`<work>` 是工作目录（如 `work/<论文名>/`）；脚本路径相对本 skill 目录。

### 0.（推荐）先得到结构化参考文献

用 `paper-reference-extraction` 产出 `<work>/out/references.json`。有了它，证据检索用的是校验过的标题，而不是规则猜测。

### 1. 解析并切批

```bash
python scripts/prepare_sentences.py <paper.pdf> --references <work>/out/references.json -o <work>/sentences.json
```

输出 `sentences.json` 和 `<work>/stage1/batch_NNN.txt`（每批 40 句，按阅读顺序）。看摘要：句子数、带引用句数、规则先验分布、告警。句子数为 0 多半是扫描件，如实告知用户。

### 2. Stage 1 · 句子类型（你来做）

逐批读 `stage1/batch_NNN.txt`，每批写一个 `<work>/labels/stage1_NNN.json`：

```json
{"range": [1, 40], "opinion": [3, 14, 16], "citation": [22, 23, 25]}
```

`range` 内没列出的句子 = `context`；`range` 声明该文件覆盖的句子，漏标的批次会在报告里告警。`rule=` 只是先验：重点复核每个 `rule=opinion`，并留意它漏掉的解释、对比、批评类句子。

### 3.（可选，联网）抓被引文献摘要

```bash
python scripts/fetch_evidence.py <work>/sentences.json --stage1 <work>/labels -o <work>/evidence.json
```

只检索观点句用到的文献（arXiv 编号 → OpenAlex → Semantic Scholar）。只有标题相似度 ≥ 0.9 且年份/第一作者不矛盾的记录才会被接受，否则标 `matched=false`，**不会拿相近的另一篇顶替**。没有网络、或手头有被引文献全文时，可按 [references/output-schema.md](references/output-schema.md) 的格式自己写 `evidence.json`（支持 `passages` 正文段落）。跳过这一步也能评分，但置信度会偏低，报告会据实提示。

### 4. 生成评分批次

```bash
python scripts/prepare_scoring.py <work>/sentences.json --stage1 <work>/labels --evidence <work>/evidence.json
```

输出 `<work>/stage2/batch_NNN.txt`（每批 8 个观点句，附上一句和证据摘录）、`stage2/plan.json`、`<work>/sections.txt`。观点句很多（> 60）时加 `--max-opinions 60` 均匀抽样，并在最终汇报里说明“抽样评分”。

### 5. Stage 2 · 三维评分（你来做）

逐批读 `stage2/batch_NNN.txt`。对每个观点句：和证据比较、写 rationale，再给整数 `depth` / `breadth` / `height`（1–5）和 `confidence`。每批一个文件 `<work>/scores/stage2_NNN.json`：

```json
[{"id": 18, "depth": 2, "breadth": 3, "height": 4, "confidence": "medium",
  "rationale": "对照 R10、R18：把两篇‘新颖性评估’上升为‘相对理解增量’的概括，摘要里没有该提法；但无法确认综合了几篇。"}]
```

纪律（详见 rubric）：只和证据比较；奖励新增内容，不奖励肯定的语气；证据已明确写出的内容 Depth ≤ 2；无证据时 `confidence: low` 且不给 5；rationale 点名对比的 `R#`。

### 6. 章节类型（你来做）

读 `<work>/sections.txt`，把列出的每个章节判为 `descriptive` / `comparative` / `analytical`，写 `<work>/labels/sections.json`：

```json
{"2": "analytical", "4": "descriptive"}
```

键是章节 `idx`。只有列出的章节（含引用、≥ 3 句）才参与章节类型统计。

### 7. 汇总、补写总体评价、重跑

```bash
python scripts/aggregate_insight.py <work>/sentences.json --stage1 <work>/labels --scores <work>/scores \
  --sections <work>/labels/sections.json --summary <work>/summary.md --outdir <work>/out
```

第一次运行时 `summary.md` 还不存在，报告里“总体评价”处是占位提示。读统计、章节表和高/低洞察句，写 3–5 句总体评价（哪一维领先、强弱章节、证据是否扎实、必须随数字一起交代的限定），存为 `<work>/summary.md`，再运行同一条命令。产出：`insight_report.json`、`insight_report.md`（语言跟随论文，可用 `--lang zh|en` 指定）、`insight_sentences.csv`。可选：`--weights 1,1,1`、`--thresholds 2.5,3.5`、`--top-k 5`。

### 8. 汇报

给用户：论文标题、句子类型分布、已评分观点句数（是否抽样）、综合分与等级、三维均值与画像、章节类型/等级分布、2–3 个最高与最低洞察句（含理由）、**所有告警与限定**（证据覆盖、`confidence=low` 占比、默认阈值），以及输出文件路径。口径是“相对被引文献的洞察信号”，不是对论文价值的判决。

## 约定

- 综合分 = 三维得分的加权平均（默认等权，保持 1–5 刻度）。等级：`< 2.5` 低、`< 3.5` 中、其余高。论文只给出等级占比而未公布阈值，所以这是本 skill 的默认设定，汇报时要说明。
- 参照：论文 Table 1（综述论文，Qwen3-32B）的均值大致为 Depth 2.9–3.0、Breadth 2.5、Height 2.8–3.0。

## 相关 skill

- `paper-reference-extraction` —— 产出第 1 步用的 `references.json`。
- `citation-faithfulness` —— 问的是引用是否被来源**支持**；本 skill 问的是作者在来源之外**增加了什么**。两者互补，结论不要混用。

## 开发

脚本只依赖标准库和 PyMuPDF（通过内置解析器 `scripts/pdfparse/`）。

```bash
python -m pytest tests -q
```
