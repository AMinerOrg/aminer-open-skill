---
name: sota-finder
version: 1.0.0
author: AMiner
contact: report@aminer.cn
description: >
  面向研究任务或 benchmark 查找近期或历史 SOTA，并建立有来源、可比较、可直接使用的 Leaderboard。适用于 benchmark 调研、跨论文结果比较、开放网络 SOTA 检索，以及从自然语言、论文、URL、仓库、表格或已有结果文件生成结构化榜单产物。可比结果进入主榜，有用但不可比的候选放入清楚标注的参考区。
  不适用于不需要结果比较的一般文献综述，也不适用于仅抽取单篇给定论文表格而不进行更广泛 SOTA 检索的任务。
metadata:
  {
    "openclaw":
      {
        "emoji": "🏆",
        "requires": {
          "bins": ["python3"],
          "env": []
        }
      }
  }
---

# SOTA Finder

先给出有用答案。证据用于支撑榜单，不能挤占结果本身。

## 路由任务

选择足以回答用户的最轻投入：

- `direct`：并不需要实际榜单调研，或给定材料已经足够回答。直接在聊天中回复；只有用户要求时才生成文件。
- `quick`：一个明确 benchmark 或窄范围，且官方或一手结果页面容易获得。
- `standard`：默认层级，适用于多个来源、多个明显范围、用户提供种子材料，或需要做实际选型的任务。
- `deep`：没有统一 benchmark、要求广泛历史覆盖、存在许多竞争范围，或涉及重要部署与复现约束。

输入与工具分开处理：优先使用用户提供的文件和 URL；用户要求离线时禁止联网；AMiner 始终可选。除非用户限制来源，否则默认进行外部检索。为归纳和交付预留足够时间，不要把整个任务耗在发现阶段。

## 调研并建立榜单

1. 检索任务名称、全称、缩写、别名、数据集、指标和主要子任务。覆盖官方榜单或 benchmark 页面、论文与预印本、作者仓库或模型卡、聚合站。聚合站用于发现候选；重要排名在可行时回到更强来源核验。
2. 先覆盖所有实质范围，再深入其中某一项。当套件、子任务、测试集、指标变体或评测设置存在实质差异时拆榜，不强行制造一个总冠军。
3. 将有用结果分为：
   - **主榜（Main Leaderboard）**：benchmark 或数据集、split、metric、direction 和关键评测设置一致，包含数值分数及可信的逐行来源。
   - **参考结果（Reference Results）**：有用的近期或历史候选，但不可直接比较、仅部分核验，或采用不同协议。
   - **冲突或不可访问（Conflicts / Unavailable）**：会影响解释的矛盾、更正、撤回或不可访问结果。
4. 排名结论优先使用官方结果页和一手材料。记录足以解释结论的来源、日期、方法、分数、设置、代码或权重可用性及实践约束。非关键字段不明时保留为 unknown，不要因此删掉有用结果。
5. 当继续检查不太可能改变重要榜首、范围、冲突或实践建议时停止扩展。只说明会实质影响理解的限制。

对于已经找到、但原生工具难以读取逐行内容的公开 HTML、JSON、CSV、XML 或文本结果端点，可选用受限读取器保存一份本地副本：

```bash
python3 "<skill-root>/scripts/fetch_source.py" "<URL>"
```

不要把它扩展成爬虫，也不要为了编写一次性抓取设施而延误交付。

## AMiner

AMiner 可用于论文发现、元数据和相关工作扩展，但不能替代官方页面、论文、仓库或一般 Web 检索。本 Skill 必须能在没有 AMiner 时正常开始和完成。预计付费或不确定调用累计达到约人民币 5 元前，集中询问一次。

## 生成产物

`direct` 默认不生成产物，除非用户明确要求。其他情况按照 [references/data-contract.md](references/data-contract.md) 在最终目录外准备一份 working JSON，然后校验并构建：

```bash
python3 "<skill-root>/scripts/build_outputs.py" \
  --input "/path/to/research-input.json" \
  --output-dir "/path/to/output/bundle" \
  --validate-only
python3 "<skill-root>/scripts/build_outputs.py" \
  --input "/path/to/research-input.json" \
  --output-dir "/path/to/output/bundle"
```

缺少 `openpyxl` 时安装 `requirements.txt`。最终目录包含：

- `brief-report.md`：简洁扩展报告；
- `full-report.html`：完整、自包含报告；
- `leaderboards.xlsx`：索引和各范围榜单；
- `evidence.json`：结构化结果与证据。

在 working JSON 中修复具体校验错误后重新构建。若某个产物失败，仍需返回聊天中的可用结果，并准确说明缺少的文件。

## 聊天输出

先给出用户真正需要的结论：各范围证据最充分的领先者、是否不存在统一可比冠军，以及必要时最适合复现或落地的选择。随后：

1. 展示每个实质范围的主榜；榜单仍便于阅读时尽量完整展示；
2. 简要保留重要但不可比的论文、预印本、仓库或聚合站候选；
3. 只补充会改变结论的指标、截止日期、冲突或覆盖缺口；
4. 已生成文件时直接链接四项产物。

使用清楚自然的语言。聊天中不展示 evidence ID、搜索日志、例行校验和防御性套话。会影响选择或部署的代码、权重、许可证、硬件、成本和关键设置应予以保留。

## 边界

用户可见文字跟随用户语言；JSON key、ID、枚举值、metric 名称和其他稳定机器字段保持英文。不得把实质不可比的结果混入同一主榜，不得虚构缺失分数，也不要在 Skill 内建立通用 benchmark 规则库。
