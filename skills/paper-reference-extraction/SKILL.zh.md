---
name: paper-reference-extraction
version: 0.1.0
author: Community contribution
description: >
  [Activation] Use this skill when the user gives a paper (PDF / Word / text) and wants its reference list turned into structured data — e.g. "extract the references of this paper", "convert the bibliography to BibTeX / JSON", "which papers does this PDF cite", "find uncited or duplicate references", "提取/解析/结构化这篇论文的参考文献", "把参考文献转成 BibTeX".
  [Capability] A rule-based script parses the PDF layout, splits the reference section, extracts DOI / arXiv / URL / year, and records where each reference is cited in the body. The agent then fills title / authors / venue / kind from each entry's raw text, and a second script verifies that every field is grounded in that raw text (anything the raw text does not contain is dropped) and exports references.json, references.bib and references.md. Runs locally; no API key, no network.
  [Routing] Do NOT use this skill to decide whether a reference EXISTS or is fabricated (`pdf-citation-verifier`, `structured-reference-audit`), or whether a citation is faithful to its source (`citation-faithfulness`). It only extracts and structures what the paper itself prints. Its output (`references.json`) is a good input for those skills and for `paper-insight-classification`.
metadata:
  {
    "openclaw":
      {
        "emoji": "📚",
        "requires": {
          "bins": ["python3"],
          "env": []
        }
      }
  }
---

# 论文参考文献结构化提取（Paper Reference Extraction）

把一篇论文的参考文献变成**有原文依据的结构化记录**。脚本负责确定性的部分（版面解析、切分、DOI / arXiv / URL / 年份抽取、正文被引统计）；**你**读每条的原文，填写标题、作者、出处、类型；再由校验脚本丢弃所有原文里找不到依据的字段。

不做的事：不联网检索、不判断文献是否真实存在（用 `pdf-citation-verifier` / `structured-reference-audit`）、不判断引用是否忠实（用 `citation-faithfulness`）。

## 环境要求

- Python ≥ 3.10，`pip install -r requirements.txt`（PyMuPDF）。
- 输入：`.pdf`、`.docx`、`.txt`、`.md`。扫描件没有文字层，需先 OCR（例如 `aminer-pdf-ocr`）。
- `scripts/pdfparse/` 是内置的版面感知论文解析器（基于 PyMuPDF），无其他依赖。

## 工作流

`<work>` 是你选的工作目录（例如 `work/<论文名>/`）；脚本路径相对本 skill 目录。

### 1. 抽取原始条目

```bash
python scripts/extract_references.py <paper.pdf> -o <work>/references.raw.json
```

看终端摘要：参考文献条数、DOI / arXiv / URL / 年份命中数、正文引用句数、列而未引的编号、悬空编号、告警。

| 情况 | 处理 |
| --- | --- |
| 条数明显偏少，或告警“无法按规则切分” | 读 JSON 里的 `references_text`，自己切分，按 `{"id": n, "label": "[n]", "raw": "…", "doi": "", "arxiv": "", "url": "", "year": null}` 写回 `references` 数组，再继续 |
| 没有可提取的文字 | 扫描件。告诉用户需要 OCR；绝不凭记忆重建参考文献 |
| 作者-年份制 | `cite_count` / `uncited` 是按“姓氏+年份”匹配的，仅供参考 |

### 2. 结构化（你来做）

读 `references.raw.json`，**每批 ≤ 15 条**，依据每条的 `raw` 填写下列字段，保存为 JSON 数组 `<work>/enriched.json`（也可分批存成 `<work>/enriched/` 下的多个文件）：

```json
[{"id": 1, "title": "", "authors": ["", ""], "year": 2020, "venue": "", "doi": "", "arxiv": "", "url": "", "kind": "conference",
  "volume": "", "issue": "", "pages": "", "publisher": ""}]
```

字段规则：

- `title` —— 文献本身的标题，保持原文语言；不含引号、作者、出处、年份。拿不准就留空，不要猜。
- `authors` —— 按原文顺序的全名。原文写 `et al.` / `等` 就停在那里，**不要凭记忆补全**；GB/T 7714 的 `Vaswani A` 保持原样。
- `year` —— 原文出现过的整数（`2020a` 取 2020）。
- `venue` —— 期刊 / 会议 / 出版社 / 预印本库，**逐字抄自原文**，缩写不要擅自展开。
- `doi` / `arxiv` / `url` —— 原文印了才填，**绝不凭记忆补 DOI**。条目里已有规则抽取的值，照抄或留空。
- `kind` —— `journal | conference | preprint | book | thesis | report | web | software | dataset | other`。线索：GB/T 7714 标记 `[J] [C] [M] [D] [R] [EB/OL]`、“In Proceedings…”、“arXiv preprint”、“Ph.D. thesis”、只有 URL 的网页或仓库。
- `volume` / `issue` / `pages` / `publisher` —— 可选，同样必须是原文印出来的。
- 带 `hints: ["link_may_be_truncated"]` 的条目，DOI/URL 可能被换行截断；采信其尾部之前先核对原 PDF 页面文本。

### 3. 校验、合并、导出

```bash
python scripts/finalize_references.py <work>/references.raw.json --enriched <work>/enriched.json --outdir <work>/out
```

生成 `references.json`（完整结果）、`references.bib`、`references.md`，并打印每个被丢弃的字段、质量不是 `complete` 的条目、疑似重复条目。`--lang zh|en` 可指定 `references.md` 的语言（默认跟随论文语言）。

- 被丢弃的字段不要换个写法再塞回去。如果校验误杀了原文里确实有的内容（例如被断词破坏的标题），回到原文核对、修改 `enriched.json` 后重跑。
- 没有可靠标题的条目会得到规则兜底的占位标题，并标记 `title_fallback`，汇报时要说明。

### 4. 汇报

给用户一段简短总结：论文标题、参考文献条数、质量分布（complete / partial / poor）、DOI 与 arXiv 覆盖率、列而未引 / 悬空 / 重复条目、被丢弃字段，以及三个输出文件的路径。贴出前 3–5 条结构化记录供抽查。

## 输出

见 [references/schema.md](references/schema.md)（英文）。`references.json` 里的每条记录是普通参考文献（`id, label, title, authors, year, venue, doi, arxiv, url, kind, raw`）的超集，另有 `volume / issue / pages / publisher / cite_count / cited_in / quality / issues`，可直接喂给其他 skill，例如 `paper-insight-classification --references`。

## 已知局限

- 双栏、跨页、脚注式引用依赖内置解析器；特殊排版可能切错。条数与正文引用的最大编号对不上时，先怀疑切分，而不是论文。
- 参考文献区里的纯数字行会被当作页码过滤，因此尾部单独折行的 DOI/URL（如 `…emnlp.` 后面单独一行的 `259`）可能丢失尾部。
- 不联网：某条记录是否真实存在，交给核验类 skill。

## 开发

```bash
python -m pytest tests -q
```
