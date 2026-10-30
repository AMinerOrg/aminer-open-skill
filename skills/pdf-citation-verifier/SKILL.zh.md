---
name: pdf-citation-verifier
version: 1.0.0
author: AMiner
contact: report@aminer.cn
description: >
  [激活条件] 当用户提供论文 PDF（文件路径或上传），并要求核验、审计、检查参考文献是否为真实存在的文献时使用——例如"检查这篇论文的参考文献有没有伪造"、"找出虚假引用"、"验证 bibliography"。
  [适用场景] 把 PDF 上传到 AMiner pdf-citation-verifier 服务，轮询异步作业并返回每条参考文献的判定（REAL / LIKELY_REAL / NEEDS_REVIEW / LIKELY_FAKE / FAKE）以及整体是否存在 hallucination 的结论。
  [路由规则] 不要用于普通论文检索、学者查询、引用意图分析或引用图谱构建——这些场景应改用 aminer-academic-search、aminer-free-academic 或 paper-source-trace。本 Skill 只判断"引用是否真实存在"。
metadata:
  {
    "openclaw":
      {
        "emoji": "🕵️",
        "requires": {
          "bins": ["python3"],
          "env": ["AMINER_API_KEY"]
        },
        "primaryEnv": "AMINER_API_KEY"
      }
  }
---

# PDF Citation Verifier（PDF 引用核验）

把一篇论文 PDF 上传到 AMiner `pdf-citation-verifier` 服务，等待异步作业完成，并返回结构化的核验结果。可以通过自然语言触发，也可以使用 `/pdf-citation-verifier`。

## 这个 Skill 做什么

服务端会从 PDF 中解析参考文献，逐条调用 AMiner SearchPro 查询，给每条引用一个标签：

- `REAL`——AMiner 中能高置信度匹配。
- `LIKELY_REAL`——部分匹配，大概率真实。
- `NEEDS_REVIEW`——证据不足，需要人工审阅。
- `LIKELY_FAKE`——部分不匹配，疑似伪造。
- `FAKE`——找不到合理匹配。

网关返回统一信封 `{"code": 200, "success": true, "msg": "", "data": ..., "log_id": "..."}`，脚本会自动拆掉这层再输出。

- `POST /api/v3/paper/citation/verify/upload` 的 `data` 是对象：`{"job_id": "verify_..."}`。
- `GET /api/v3/paper/citation/result?job_id=...` 的 `data` 是只含一个元素的数组，元素里有顶层字段 `is_finish`、`has_hallucination`、`hallucination_ratio`、`total`、`counts_by_status`、`summary`、`urls`、`report`、`result` 等。
- 一旦脚本看到 `is_finish: true`，会**自动 GET `urls.result`**（逐条引用 JSON）合并进返回 payload 的 `details` 字段——这样一个 `--output` 文件里同时有 summary 和每条记录的 `status` / `confidence` / `title` / `first_author` / `key_reasons` / `top_match`，用户不必在 5 分钟内去点 OSS 链接。

Skill 返回这个记录加上 `job_id`，用户后续可凭 `job_id` 再次查询。

## 文件结构

- `SKILL.md` / `SKILL.zh.md`——英文 / 中文 Skill 定义（本文件）。
- `commands/pdf-citation-verifier.md`——slash command 入口。
- `scripts/verify_pdf.py`——HTTP 客户端：上传 → 轮询 → 拆封信封后打印结果记录。
- `scripts/render_report.py`——把结果 JSON 渲染成自包含 HTML 报告卡（仅标准库）。
- `requirements.txt`——Python 依赖（`requests`）。

## Pre-flight 检查

在执行脚本前必须先过下面三项；任何一项失败立即停止并告知用户。

**1. AMINER_API_KEY**

```bash
[ -z "${AMINER_API_KEY+x}" ] && echo "AMINER_API_KEY missing" || echo "AMINER_API_KEY exists"
```

缺失则停止，引导用户到 https://open.aminer.cn 获取 Token，然后 `export AMINER_API_KEY=<token>`。**任何输出中都不得打印 token 的值。**

**2. Python 依赖**

```bash
python3 - <<'PY'
import importlib.util
missing = [name for name in ("requests",) if importlib.util.find_spec(name) is None]
print("Missing: " + ", ".join(missing) if missing else "Python dependencies exist")
PY
```

缺失则提示安装：`pip install -r "${CLAUDE_PLUGIN_ROOT}/requirements.txt"`。

**3. PDF 输入**

用户必须提供存在的本地 `.pdf` 路径。如果只描述了论文但没给文件，必须主动追问 PDF 路径。**不要自行编造或下载 PDF。**

## 执行示例

默认参数（最多核验 50 条，自动轮询到完成）：

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/verify_pdf.py" \
  --pdf "/abs/path/to/paper.pdf"
```

完整参数：

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/verify_pdf.py" \
  --pdf "/abs/path/to/paper.pdf" \
  --max-refs 80 \
  --strict \
  --timeout 900 \
  --poll-interval 5 \
  --output outputs/pdf-citation-verifier/<safe-paper-stem>/result.json
```

仅提交不等待（拿到 `job_id` 后让用户自己查）：

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/verify_pdf.py" \
  --pdf "/abs/path/to/paper.pdf" --no-wait
```

凭已有 `job_id` 直接拉结果（不重新上传）：

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/verify_pdf.py" \
  --job-id verify_20260527T090207Z_a72c9ba5
```

## 参数说明

| 参数 | 默认 | 说明 |
| --- | --- | --- |
| `--pdf` | 必填（除非给了 `--job-id`） | 本地 `.pdf` 路径。服务端 body 上限 50 MB。 |
| `--job-id` | – | 不上传，只拉已有作业的结果。 |
| `--max-refs` | 50 | 服务端硬上限 100。 |
| `--strict` | 关闭 | 开启后对部分匹配会更严格地判 FAKE。 |
| `--no-wait` | 关闭 | 与 `--pdf` 连用：仅提交作业并返回 `job_id`，不轮询；与 `--job-id` 连用：单次查询后立即返回，不进入轮询循环。 |
| `--timeout` | 600 | 轮询的整体超时（秒）。 |
| `--poll-interval` | 5 | 两次轮询之间的间隔（秒）。 |
| `--request-timeout` | 120 | 单次 HTTP 请求超时（秒）。 |
| `--output` | - | 可选：把最终 JSON 同步落到本地路径。 |

## 环境变量

| 变量 | 是否必需 | 用途 |
| --- | --- | --- |
| `AMINER_API_KEY` | 是 | 写入请求头 `Authorization` 的 JWT。 |
| `PDF_CITATION_VERIFIER_BASE_URL` | 否 | 覆盖网关 base URL，默认 `https://datacenter.aminer.cn/gateway/open_platform`。 |

## 运行约束

- **绝对不要**以任何方式打印、日志或回显 `AMINER_API_KEY` 的值。
- **绝对不要**伪造核验结果。脚本失败或超时时，原样汇报错误，不得自行编造。
- 响应中的 `urls`、`report`、`result`、`pdf` 都是服务端产物，多半是带有效期 `url_expire_seconds` 的预签名链接。不要谎称这些路径在用户本机存在；需要本地 JSON 副本时用 `--output`。
- 注意单用户活跃作业上限（服务端超出会返回 429）。出现 429 时停下并告知用户先等已提交的作业完成。
- 任何 `LIKELY_FAKE` / `FAKE` 都只是"需要人工复核"的信号，不是终审。展示结果时尽量带上 `counts_by_status` 与逐条原因（若响应包含）。

## 结果展示

脚本返回后，至少向用户呈现：

- `job_id`
- `total`（核验的引用数量）
- `has_hallucination`、`hallucination_ratio`
- 基于 `counts_by_status` 的状态计数小表（REAL / LIKELY_REAL / NEEDS_REVIEW / LIKELY_FAKE / FAKE 等）
- 如果 `details.records[]` 存在（自动从 `urls.result` 拉的），逐条列出 FAKE / LIKELY_FAKE / NEEDS_REVIEW 的 `title`、`first_author`、`year`、`key_reasons`，省得用户去点会过期的 OSS 链接
- 响应里的 `urls.report` / `urls.result` 链接，需要附注会在 `url_expire_seconds` 后过期
- 若存在 `website_records[]`，逐条列出 `raw` 前 80 字符、可达 URL 与原始 `status`；然后展示 `website_summary`（`total_website_citations`、`adjusted_hallucination_ratio`）。明确说明：`adjusted_hallucination_ratio` 排除了网站型引用，原始 `hallucination_ratio` 仍保留在 payload 顶层
- 完整 JSON 要么 `--output` 落盘，要么直接回显给用户，不要静默丢弃。

## HTML 报告卡

核验完成后（如果做了本地 Non-Reference 筛查，则在筛查之后），用标准渲染器生成一张可视化报告卡——**不要临场手写 HTML**：

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/render_report.py" \
  --input "<result-json路径>" \
  --output "<同目录>/report.html" \
  --lang zh   # 对话以中文为主用 zh，否则用 en
```

- `--input` 是 `verify_pdf.py --output` 落盘的 JSON（必须含 `summary`；有 `details.records` 才会渲染逐条聚焦表）。如果本地筛查生成了 `.filtered.json`，优先用它。
- 产出是单个自包含 HTML（内联 CSS、无外部资源）：总览卡片（假引用占比大数字）、五色状态堆叠条 + 图例、聚焦表（每条 FAKE / LIKELY_FAKE / NEEDS_REVIEW 的结论徽章、引用信息、最接近的 `top_match`、人话版判断原因）。
- 所有数字原样取自输入 JSON，渲染器不做任何重新判定。
- 告诉用户报告路径，并主动提出可以 `open` 在浏览器里看。如果本次没有 `--output` JSON（纯对话跑），要么跳过报告，要么先把 payload 写到临时 JSON 再渲染。

## 本地 Non-Reference 筛查

当 `is_finish=true` 且存在 `details.records[]` 时，在最终展示前必须做一轮本地 agent 审阅。这个审阅只使用当前 Claude Code/Codex 宿主 agent；不要调用额外 LLM API，不要要求用户提供额外 key，也不要把筛查结果回传服务端。

筛查必须保守。只剔除明显不是 bibliography reference 的记录，例如正文污染、figure/table/stage/evaluation 叙述、appendix 或 section heading、页眉页脚、页码、图表 caption、非引用类叙述句。不要因为记录是 `FAKE`、`LIKELY_FAKE`、`NEEDS_REVIEW`，不要因为 AMiner 查不到，也不要因为元数据不完整就判为非 ref。模糊记录一律保留在 `filtered_records`。

筛查只能使用这些字段：`id`、`status`、`confidence`、`title`、`first_author`、`year`、`raw`、`key_reasons`、`top_match`。优先看 `raw`；`title` 和 `key_reasons` 只作为辅助信号。

生成可审计的 filtered payload：

- 保留原始服务端 payload 不变。
- 仅给被剔除的记录添加 `llm_filter`：
  - `is_reference: false`
  - `reason: "<简短原因>"`
  - `confidence: <0.0-1.0>`
- 新增 `filtered_records`，包含所有保留记录。
- 新增 `removed_non_reference_records`，包含被剔除记录及其 `llm_filter`。
- 新增 `filtered_summary`，只基于 `filtered_records` 重算：
  - `total`
  - `counts_by_status`
  - `has_hallucination`
  - `hallucination_ratio = (FAKE + LIKELY_FAKE) / total`，如果 `total=0` 则为 `0`

如果用户传了 `--output path.json`，把 filtered payload 写到同目录的 `path.filtered.json`（例如 `result.json` -> `result.filtered.json`）。如果 output 路径没有 `.json` 后缀，就追加 `.filtered.json`。如果没有使用 `--output`，不要创建新文件；只在最终回答中展示 filtered summary 和被剔除记录。

如果 details 自动拉取失败，payload 会带一个 `details_fetch_error` 字段——把错误告诉用户并建议在 `url_expire_seconds` 秒内自行 GET `urls.result`。

如果 `is_finish` 为 `true` 且 `status` / `msg` 指示失败，把信息告知用户并建议重试。

## URL / 网站型引用二次核验

在 Non-Reference 筛查完成、`filtered_records` 就绪之后，再跑一遍**网站型引用识别**——即那种指向真实网页的引用（RFC、blog、GitHub README、标准规范文档、产品主页），而不是期刊 / 会议论文。AMiner SearchPro 以学术论文为主，这类引用即便 URL 完全有效，也常被判成 `LIKELY_REAL / NEEDS_REVIEW / LIKELY_FAKE / FAKE`。这一步把它们单独标出来，让用户能区分"伪造的学术引用"与"合法的网站型引用"。

覆盖范围：

- 只处理 `filtered_records`，不处理 `removed_non_reference_records`。
- 只考虑 `status` 为 `LIKELY_REAL / NEEDS_REVIEW / LIKELY_FAKE / FAKE` 的记录（跳过 `REAL`）。
- 仅从 `raw` 字段抽 URL，正则用 `https?://[^\s<>"'()]+` 之类保守写法。同一条记录内去重。
- `raw` 里没有 URL 的记录直接跳过，不加任何字段。

探测规则（使用宿主 agent 的 WebFetch；**不得**调用外部 LLM API，**不得**索要额外 key）：

- HTTP 2xx 或 3xx（最多 3 次跳转）→ `reachable`。
- 其他状态码 / 超时 / DNS 失败 → `unreachable`。
- 401 / 403 → `unreachable_paywalled`（**不**算 reachable）。
- 跳过解析到 `localhost` 或私网 IP 的 URL（10/8、172.16/12、192.168/16、169.254/16、::1、fc00::/7）。
- 单个 URL 超时 15 秒。同一条记录最多探 3 个 URL；如果超过，把 `url_probe_truncated: true` 挂在该记录上，只探前 3 个。
- 绝对不得伪造 HTTP 响应。WebFetch 失败时如实记 `unreachable`，把错误信息原样填进 `reason`。
- 不要把 record 数据发到 URL 所在主机以外的任何第三方服务。

对每一条含 URL 的记录，挂上 `url_verification`：

```json
"url_verification": {
  "urls": ["<url1>", "<url2>"],
  "reachable_urls": ["<url1>"],
  "is_website_citation": true,
  "reason": "<简短原因>",
  "url_probe_truncated": false
}
```

只要至少一个 URL `reachable`，`is_website_citation` 就为 `true`。

在返回 payload 顶层新增两个字段：

- `website_records`：所有 `is_website_citation: true` 的记录。**不**修改其原始 `status`——WEBSITE 分类只存在于 agent 视角，服务端判定保留以便审计。
- `website_summary`：
  - `total_website_citations`：N（即 `website_records` 的长度）
  - `from_status`：`{ "LIKELY_REAL": a, "NEEDS_REVIEW": b, "LIKELY_FAKE": c, "FAKE": d }`
  - `adjusted_hallucination_ratio`：`(FAKE_count + LIKELY_FAKE_count − c − d) / max(filtered_total − N, 1)`
  - `note`：`"WEBSITE citations excluded from academic-hallucination ratio."`

落盘约定（对齐 Non-Reference 筛查）：

- 用户传了 `--output path.json` 时，同目录再写一份 `path.website_verified.json`（与 `path.filtered.json` 并列）。如果输出路径没有 `.json` 后缀，追加 `.website_verified.json`。
- 没有 `--output` 时，不新建文件；只在最终回答中呈现。

**不要**修改服务端返回的 `hallucination_ratio` 与 `counts_by_status`。所有网站感知的统计只放在 `website_summary` 里。
