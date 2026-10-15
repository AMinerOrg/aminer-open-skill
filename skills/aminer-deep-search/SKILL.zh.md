---
name: aminer-deep-search
version: 2.2.0
author: AMiner
contact: report@aminer.cn
description: >
  仅当用户明确需要大规模学术论文收集时激活本 skill：构建 50 篇以上的综述/文献回顾参考文献库、
  组建大候选论文池、或从种子论文做引用滚雪球。
  仅出现"综述/文献回顾"字样不足以触发——如果用户只要一个综述式回答、少量论文清单（<50 篇）
  或单篇查询，不要使用本 skill：免费单步查询走 aminer-free-academic，深入分析或 <50 篇的检索走
  aminer-academic-search，个性化推荐走 aminer-daily-paper。
  由宿主模型（正在运行本 skill 的模型）亲自驱动循环：扩展查询、判断相关性、做引用滚雪球、决定何时终止。
  附带脚本只是纯工具命令，调用 AMiner 开放平台的正规接口并只输出 JSON tool-result，无需配置任何额外 LLM。
  支持结构化约束（年份区间、作者、机构、来源、语言、排除词、引用区间）与多种排序目标
  （最新、相关性、影响力、经典+最新）。
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

# AMiner 深度收集

宿主模型直驱的综述文献收集。你（正在读这份文档的模型）就是控制器：运行工具脚本、阅读 JSON 输出、自己判断相关性、迭代直到达成收集目标。

## 路由规则（先读这个）

| 任务形态 | Skill |
|---|---|
| 单次免费 API 能回答的查询（按标题找论文、按名字找学者、机构/期刊标准化） | `aminer-free-academic` |
| 单实体深挖、多条件检索、或 50 篇以内的论文收集 | `aminer-academic-search` |
| 个性化论文推荐 | `aminer-daily-paper` |
| 大规模候选收集（≥50 篇）、综述文献库构建、引用滚雪球 | **本 skill** |

不要仅凭"综述/文献回顾"字样触发；按用户实际需要的**收集规模**触发。

## Pre-flight

1. 检查 key（不打印值）：

```bash
[ -z "${AMINER_API_KEY:-}" ] && echo "AMINER_API_KEY missing" || echo "AMINER_API_KEY exists"
```

缺失时停止并让用户设置 `AMINER_API_KEY`（控制台：https://open.aminer.cn/open/board?tab=control）。绝不打印 key。

2. 确认 `topic` 和 `target-size`（默认 400）。

3. **提取用户的硬约束**——年份区间、来源、作者、机构、语言、排除词、排序目标（最新/影响力/经典+最新）。把年份区间和必备字段写入状态文件，让 `add` 机械化执行校验：

```bash
python3 scripts/paper_set.py init --topic "..." --year-from 2020 --year-to 2025 --require-fields year
```

注意：AMiner 没有文献类型（期刊/会议/预印本）过滤参数；用户有此要求时如实说明，退化为按 venue 事后过滤。

4. 若轮次计划预估费用 ≥¥5，先告知用户并获得确认再开始。

## 工具

两个脚本都在本 skill 目录的 `scripts/` 下。stdout 只输出一个 JSON 文档（即 tool-result）；诊断信息与 `[cost]` 费用行走 stderr。脚本不做任何相关性打分——那是你的工作。

### `scripts/aminer_api.py` — AMiner 接口调用

| 子命令 | 端点 | 价格 |
|---|---|---|
| `search [--query Q] [--title T] [--abstract A] [--author 作者] [--org 机构] [--venue 期刊] [--size 20] [--year-from Y] [--year-to Y] [--order n_citation\|year] [--max-pages 3]` | GET `/api/paper/search/pro`（每页 100 条）+ 免费 `paper/info` 补全 | ¥0.01/页 |
| `qa-search [--query "自然语言问题"] [--topic-high '[["词A","词B"],["词C"]]'] [--size 20] [--year-from Y] [--year-to Y] [--citation-sort]` | POST `/api/paper/qa/search`（固定 `use_topic=true`：`use_topic=false` 时后端忽略 `query`）+ 免费补全 | ¥0.05/次 |
| `qa-search-pro [--query Q] [--query-type auto\|topic\|keywords\|title\|identifier] [--authors ...] [--orgs ...] [--venues ...] [--year-from Y] [--year-to Y] [--languages en zh] [--all-terms ...] [--any-terms ...] [--exclude-terms ...] [--search-in all\|title\|title_keywords\|abstract] [--min-citations N] [--max-citations N] [--sort relevance\|balanced\|recent\|citation] [--size 10]` | POST `/api/paper/qa/searchPro`（每页 10 条，cursor 翻页）+ 免费补全 | ¥0.30/页 |
| `info --ids id1 id2 ...` | POST `/api/paper/info`（≤100 个 id 分批） | 免费 |
| `references --ids id1 id2 ... [--per-seed 20]` | 每个 seed 调 GET `/api/paper/relation` + 免费补全 | ¥0.10/篇 seed |

选择检索子命令：`search` 是廉价批量主力（¥0.01 拿 100 条；按字段字面匹配，年份在客户端过滤）。`qa-search` 便宜地处理自然语言问题。`qa-search-pro` 单价是 `search` 的 30 倍且每页只有 10 条——只在 `search` 表达不了的硬约束（语言过滤、排除词、引用区间、多值作者/机构/来源过滤）时使用。注意：`qa-search-pro` 需要账号开通该 API 权限；若返回 HTTP 400 权限错误，让用户去 AMiner 控制台开通，并退回 `search`。若续页请求失败（后端偶尔会在翻页中途使 cursor 失效），脚本会返回已收集的页并向 stderr 打 `[warning]`，而不是整体报错——出现该警告后结果少于 `--size` 属预期，不是错误。

`search` 字段注意：多字段之间是 AND 关系；匹配是字面的，`--author` 需要全名（"Ashish Vaswani" 而非 "Vaswani"）——组合查询返回 0 时，先逐个去掉字段再放弃。

输出形状：检索类子命令和 `info` 输出 `[{id, title, year?, venue?, authors?, doi?, n_citation_bucket?, abstract_slice?, url}]`；`references` 额外带 `source_paper_ids`（哪些 seed 引用了该论文），且结果中排除 seed 本身。`doi` 只有 `search` 返回（其余端点不含 DOI）。

### `scripts/paper_set.py` — 跨轮状态文件（无网络）

状态文件默认是工作目录下的 `outputs/paper_set.json`。去重是三重键：AMiner ID、小写 DOI、标准化标题——同一论文的预印本与正式版会合并成一条记录（正式版 venue 优先；备用 ID 存入 `alt_ids`）。

```bash
# 先记录一次硬约束，此后每次 add 自动校验
python3 scripts/paper_set.py init --topic "..." --year-from 2020 --year-to 2025 --require-fields year

# 把保留的结果管道进去；--source 逐篇记录检索来源
python3 scripts/aminer_api.py search --query "..." \
  | python3 scripts/paper_set.py add --source "search:..."
# → {"added": N, "duplicates": M, "merged_versions": K, "rejected": R, "reject_reasons": {...}, "total": T}

python3 scripts/paper_set.py stats     # 总量、分层、字段完整度、按年分布
python3 scripts/paper_set.py mark-expanded --ids id1 id2   # 记录已滚雪球的 seed
python3 scripts/paper_set.py promote --ids id1 id2         # 提升到精选层（curated）
python3 scripts/paper_set.py log-round --queries "q1" "q2" --added N --rejected R  # 轮次 trace
python3 scripts/paper_set.py export -o outputs/final_papers.json [--tier curated|candidate|all]
```

`add` 也接受 `--ids id1 id2 ...` 直接加裸 id（注意：裸 id 不带年份/标题，`init` 要求这些字段时会被拒绝——请改用管道传补全后的 JSON）。带 `source_paper_ids` 的条目（来自 `references`）会自动把对应 seed 记为已扩展，并写入 `references:<seed>` 来源。

如需先筛选再入库，先阅读搜索输出，再只把保留的条目管道进去：

```bash
printf '%s' '[{"id":"...","title":"..."}]' | python3 scripts/paper_set.py add --source "search:..."
```

## 每轮协议（核心）

### 第 0 轮 — 规划

- 从 topic 派生 4–8 个种子查询：同义词、子领域、方法名、数据集/基准、常用英文缩写。
- 用提取到的硬约束跑 `paper_set.py init`（见 Pre-flight 第 3 步）。
- 根据用户目标选排序策略：
  - 影响力/奠基性论文 → `search --order n_citation`
  - 最新工作 → `search --order year`（或 `qa-search-pro --sort recent`）
  - **经典+最新** → 每个种子查询跑两遍，一遍 `--order n_citation`、一遍 `--order year`，合并入库（状态文件会去重）——避免新论文被高引论文挤掉
  - 未表达偏好 → 默认综合排序（不传 `--order`）
- 预估轮数与费用（search ≈ ¥0.01/页，qa-search ¥0.05，qa-search-pro ¥0.30/页，references ¥0.10/seed）。预估 ≥¥5 时先向用户确认。

### 每一轮（默认最多 12 轮），固定六步

1. **搜索**：对待查队列执行 1–4 个 `search` / `qa-search`，带上用户的结构化过滤（`--author/--org/--venue/--year-from/--year-to`）。优先用 `search`（最便宜）；自然语言问题用 `qa-search`；只有硬约束（语言、排除词、引用区间）无法表达时才用 `qa-search-pro`。
2. **筛选**：阅读 stdout 结果，自己判断主题相关性。硬约束（年份、必备字段）由状态文件机械执行；你负责语义判断。
3. **入库**：只把保留的条目管道进 `paper_set.py add --source "search:<查询>"`。绝不入库你认为跑题的论文。关注输出里的 `rejected`/`reject_reasons`——拒绝率高说明查询正在漂出约束窗口。
4. **查看进度**：跑 `stats` 查看总量、分层与字段完整度。
5. **滚雪球**：从本轮新增的相关论文里挑 ≤5 个强种子（高相关、`--order n_citation` 排前、不在 `expanded_seeds` 中），跑 `references --ids ...`。对输出再做相关性筛选后带 `--source` 入库。没有可入库产出的 seed 用 `mark-expanded` 记录。
6. **记录与决策**：跑 `log-round --queries ... --added N --rejected R` 记录本轮 trace，然后决策：
   - 某个搜索结果 <5 条或质量差 → 换一个改写后的查询（每个方向最多试 2 个变体，之后转滚雪球）；
   - references 持续产出大量相关论文 → 继续从新 seed 滚雪球；
   - 达到 `target-size`、结果枯竭、或连续 2 轮新增 <5 篇 → 终止。

### 收尾

可选地把最强的论文 `promote` 到精选层。跑 `export`（加 `--tier curated` 可单独导出精选集），然后报告：最终篇数、拒绝/合并数、总费用（累加 stderr 的 `[cost]` 行）、输出文件路径。导出文件含每篇论文的完整字段（标题、作者、年份、来源、DOI（如有）、AMiner ID、链接、被引档位、检索来源 `found_by`、分层），以及约束条件与轮次 trace。

## 错误处理

脚本输出结构化 JSON 错误，绝不把错误伪装成空结果。空结果集就是普通的 `[]` 且退出码为 0——它不是错误。

| `error` 值 | 含义 | 处置 |
|---|---|---|
| `missing_aminer_api_key` | 环境变量未设置 | 停止；让用户设置 |
| `invalid_params`（40001） | 请求参数错误 | 修正调用，不要原样重试 |
| `permission_denied`（40301） | key 无权限/余额不足 | 停止；让用户查控制台 |
| `token_expired`（40302）、`invalid_api_key`（40307）、`invalid_token`（40308） | 凭证问题 | 停止；让用户更新 key |
| `rate_limited`（40306） | 访问频率过快 | 放慢节奏；脚本已自动重试 |
| `server_error`（50001）、`http_error`、`network_error` | AMiner 侧/传输故障 | 脚本已重试 3 次；持续出现则如实报告 |

## 规则

1. 绝不编造论文 ID 或标题；只引用工具实际返回的数据。
2. 免费优先：元数据一律来自免费的 `paper/info`（脚本已内置）；绝不为批量元数据调付费的 `paper/detail`。
3. 不要把原始工具输出塞进最终回答；只报告数量与导出文件路径。
4. 绝不打印或记录 `AMINER_API_KEY`。
5. 如果 AMiner 返回的论文少于目标，如实报告实际数量，不要编造。
6. 违反用户硬约束的论文绝不能进入结果集——用 `init` 记录约束，让校验机械化执行。
