---
name: paper-source-trace
version: 1.0.0
author: AMiner
contact: report@aminer.cn
description: >
  Use when a user provides an academic paper PDF, extracted paper text, citation contexts, or references and asks for paper source tracing, claim-centered source tracing, citation intent extraction, entity/relation extraction, contribution mapping, citation graph JSON, SVG/HTML citation maps, or optional AMiner metadata/citation enrichment.
  Do NOT use this skill for simple paper lookup by title, scholar search, or lightweight academic queries — use aminer-free-academic or aminer-academic-search for those instead.
metadata:
  {
    "openclaw":
      {
        "emoji": "🧭",
        "requires": {
          "bins": ["python3"],
          "env": []
        },
        "primaryEnv": "AMINER_API_KEY"
      }
  }
---

# Paper Source Trace

Paper Source Trace 将单篇目标论文转换为以 claim 为中心、证据可追溯的来源追踪产物。本 Skill 只有一个规范名称：`paper-source-trace`。

你可以用自然语言或 `/paper-source-trace` 触发本 Skill。

## 语言路由

- 用户主要使用中文，或明确要求中文输出时，使用本 `SKILL.zh.md`。
- 其他情况使用 `SKILL.md`。
- 无论使用哪种语言，`json/graph/citation_graph.json` 的 key、intent label、relation type、source role 和参数名都保持英文。

## 中文工作流

### 标准产物

在证据和文件系统权限允许时，生成以下产物：

- `analysis.md`：面向人阅读的中文分析报告。
- `json/graph/citation_graph.json`：遵循 `references/schema.md` 的规范机器可读图谱。
- `citation_map.svg`：可生成时输出静态引用图谱。
- `citation_map.html`：有图谱数据时输出单文件交互图谱。
- `citation_map_chain.svg`：仅在 `svg: both` 时输出的链式来源追踪 SVG。
- `citation_map_spec.md`：仅在 SVG 生成存在限制或失败时输出。

默认输出目录：

```text
outputs/paper-source-trace/<safe-paper-stem>/
```

推荐目录结构：

```text
analysis.md
citation_map.svg
citation_map.html
citation_map_chain.svg          # only when svg is both
citation_map_spec.md            # only when SVG generation has caveats or fails
json/graph/citation_graph.json
json/aminer/*.json              # only when AMiner raw results are saved
json/extraction/*.json          # only when structured intermediates are saved
```

旧参数兼容：如果用户写 `mode: current`，视为 `svg: radial`；`mode: example` 视为 `svg: chain`；`mode: all` 视为 `svg: both`。如果同时提供 `svg` 和 `mode` 且两者冲突，必须询问用户确认。`hybrid`、`interactive graph`、`expandable knowledge graph`、`交互图谱` 或 `可展开知识图谱` 表示用户需要标准产物 `citation_map.html`；它不是 SVG 模式，也不改变 SVG 选择。

### 启动确认

在读取论文、抽取引用、检查 `AMINER_API_KEY`、调用 AMiner 或生成 SVG 之前，必须先请用户确认：

- SVG 输出：`radial`、`chain` 或 `both`。
- AMiner 增强：`on` 或 `off`。

如果用户已经给出其中一个或两个设置，先复述为暂定选择，再请求最终确认。用户回答前不要继续执行。

如果确实无法进行交互确认，使用推荐默认值：`svg: both` 和 `aminer: on`。但预估 AMiner 成本达到或超过 `¥5` 时，仍必须先请求明确确认；如果缺少 `AMINER_API_KEY`，跳过 AMiner 增强并继续本地分析。

### 核心规则

1. 只使用用户提供的论文文本、引用上下文、参考文献、用户笔记，或用户明确要求的 AMiner 结果作为证据。
2. 不凭领域记忆推断 citation intent。
3. AMiner 增强必须显式开启；未请求时不检查 `AMINER_API_KEY`。
4. AMiner 只能补充 paper ID、URL、候选参考文献匹配和外部引用关系，不能替代本地 citation context，也不能单独证明 intent 或 source trace。
5. 保留不确定性；当引用上下文、参考文献匹配或来源角色证据不完整时降低置信度。
6. `citation_sentence` 和 `context` 必须保留目标论文原文语言。它们是原始证据锚点，不是跟随用户语言改写的解释。
7. `evidence`、`summary`、`notes`、Markdown 报告正文以及 SVG/HTML 可见 UI 文案跟随用户输出语言。
8. 如果可以写入文件，不要只给聊天摘要。

### AMiner 增强

能够确认时，除非用户确认 `aminer: on` 或明确写出 `AMiner 增强`、`用 AMiner 补全`、`查 AMiner 引用链`、`补全 paper_id`、`enhance with AMiner`、`use AMiner metadata`，否则不启用 AMiner。确实无法确认时，推荐默认值为 `aminer: on`。

开启后：

1. 只检查 `AMINER_API_KEY` 是否存在，绝不打印 token。
2. 如果缺少 token，继续本地分析，并记录 AMiner 增强已跳过。
3. 使用最短可行链路：`paper_search` 或 `paper_search_pro`、`paper_detail`、`paper_relation`、`paper_info`。
4. 对所有计划或完成的 AMiner 调用输出成本摘要。
5. 预估成本达到或超过 `¥5` 时，先请求用户明确确认。
6. 在 `json/graph/citation_graph.json` 的 `metadata.aminer_enrichment` 中记录增强元数据。

### Intent Labels

除非用户明确扩展分类体系，只使用以下 12 类标签：

`background`, `problem`, `core-method`, `supporting-method`, `dataset`, `metric`, `baseline`, `tool-resource`, `theory`, `result-evidence`, `limitation`, `future-work`。

### 执行步骤

1. 先询问启动确认问题，并等待用户回答。
2. 确认输入证据和输出目录。
3. 抽取可靠的论文文本、参考文献条目和 citation contexts。
4. 重要分类或来源追踪前，读取 `references/evidence_protocol.md`。
5. 使用允许的 intent labels 分类每条引用。
6. 在文本支持时抽取目标论文的关键 claims 或 contributions。
7. 构建 `source_traces[]`，把目标 claim 连接到本地 citation contexts、被引文献角色和证据步骤。
8. 抽取解释目标论文的 entities 和 relations。
9. 如果启用 AMiner，只补充元数据，不替代本地证据。
10. 先写入 `json/graph/citation_graph.json`，再生成可视化产物。
11. 写入 `analysis.md`；只有用户明确要求模板或固定格式时才使用 `references/analysis_template.md`。
12. 用同一条渲染命令生成 `citation_map.html` 和已确认的 SVG 输出：`python3 scripts/render_html.py --graph <output>/json/graph/citation_graph.json --output <output>/citation_map.html --svg <radial|chain|both> --language auto`。
13. 不要临场手写 SVG 或 HTML；静态 SVG 两种模式与 HTML 的 `radial / chain` 视图必须共享渲染器布局、配色、语言包、换行、节点优先级和边线规则。
14. 最终回复前验证产物。

### 参考文件

- `references/schema.md`：规范 schema 和 JSON 示例。
- `references/evidence_protocol.md`：证据链和不确定性规则。
- `references/prompts.md`：中英文抽取与审查 prompts。
- `references/visual.md`：SVG 和 HTML 图谱规则。
- `references/analysis_template.md`：显式模板模式下使用的固定报告模板。
- `scripts/render_html.py`：标准图谱渲染器。生成 `citation_map.html`、`citation_map.svg` 和 `citation_map_chain.svg` 时必须使用它，不要临场手写 SVG 或 HTML。

### 质量检查

- 每条 citation 都有 `intent`、`evidence`、`confidence`，并且有 `reference_id` 或 `unmatched_reference: true`。
- 每个 intent label 都属于允许的 12 类。
- 关键引用能追溯到 citation sentence 或本地上下文。
- `citation_sentence` 和 `context` 保留目标论文原文语言；只有解释性字段跟随用户语言。
- 每个 entity 至少由一条 citation 支撑。
- 每条 source trace 至少由一个本地 citation context 支撑；AMiner 元数据不能作为唯一支撑。
- 中文 `citation_map_chain.svg` 使用 `问题链`、`方法链`、`数据链`、`基线链`、`局限/资源链`，不用 radial 分组标签替代。
- 写入 `json/graph/citation_graph.json` 后，用 `scripts/render_html.py` 同时生成 HTML 和 SVG。HTML 与 SVG 必须使用单一可见语言、同一套 canonical group 标签、同一节点排序和同一减少边线策略。
- 静态 SVG 只保留有用主线，密集分组用 `+N` 汇总，不画 citation-to-citation cross-link 或 AMiner-only 关系线。
- 即使 Markdown、SVG 或 HTML 有限制，`json/graph/citation_graph.json` 仍必须完整。
