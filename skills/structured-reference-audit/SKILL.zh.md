---
name: structured-reference-audit
version: 0.1.0
author: Community contribution
description: >
  使用 GROBID 将论文 PDF 拆为可追溯参考文献账本，再逐条通过 AMiner 解析。
  适用于需要保守核验参考文献存在性、且不希望把 PDF 解析失败直接当作虚假引用的场景。
---

# 结构化参考文献核验

本 skill 用于检查参考文献能否对应到学术记录，同时把“PDF 没拆清楚”和“文献不存在”明确分开。它是 `pdf-citation-verifier` 的补充，而不是替代其服务端 PDF 核验。

```text
PDF 或 GROBID TEI
-> GROBID 拆分参考文献
-> Reference Ledger：原始条目、页码锚点、题名/DOI/arXiv、解析警告
-> 对可解析条目逐条 AMiner 题名检索
-> verified_exists / needs_human_review / not_found_in_aminer
```

## 需要什么

- Python 依赖：`pip install -r requirements.txt`
- 输入 PDF 时需要一个已运行的 GROBID 服务，默认地址为 `http://127.0.0.1:8070`。
  GROBID 不会随 skill 打包；如果已有 TEI XML，可直接传 `--tei`，无需本地启动它。
- 调 AMiner 解析需要 `AMINER_API_KEY`；只生成账本时使用 `--skip-resolve`，不需要 token。绝不输出或写入 token。

## 怎么运行

```bash
python3 scripts/structured_reference_audit.py \
  --pdf "/abs/path/paper.pdf" \
  --output "reference-ledger.json"
```

只检查 PDF 是否拆对：

```bash
python3 scripts/structured_reference_audit.py \
  --tei "/abs/path/paper.tei.xml" \
  --skip-resolve \
  --output "reference-ledger.json"
```

## 结果应该怎么说

- `verified_exists`：AMiner 返回高相似度题名匹配。
- `needs_human_review`：解析、匹配或网络证据不足，需要人工查看。
- `not_found_in_aminer`：AMiner 没有返回足够好的题名候选，**不等于**文献是伪造的。
- `parse_quality_insufficient`：PDF/TEI 的参考文献拆分质量不足，不应继续给每条文献下结论。

不要依据本 skill 给作者贴学术不端标签。解析残片应保留在账本供追溯；未决条目应作为人工检查队列展示。
