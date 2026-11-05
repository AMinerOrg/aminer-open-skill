# 安装指南

[← 返回 README](README.md) · [English](INSTALL.en.md)

`skills/` 下每个目录都是一个独立的可安装技能。无论用哪种方式，都要保留完整技能目录（`SKILL.md`、`scripts/`、`references/` 等），不要只复制 `SKILL.md`。安装后再按 [配置 Token](#5-配置-token) 配置 Token。

| 你的环境 | 推荐方式 |
|---|---|
| Claude Code、Codex、OpenClaw、Cursor、Trae 等主流 Agent | [`npx skills`](#1-npx-skills-安装推荐) |
| Claude Code，且需要 slash command | [插件安装](#2-claude-code-插件安装) |
| 无法联网安装、或需要固定版本 | [手动安装](#3-手动安装codex--openclaw--其他-agent) |

## 1. `npx skills` 安装（推荐）

需要 [Node.js 18 或更高版本](https://nodejs.org/)，无需全局安装 CLI。先查看可安装的技能名：

```bash
npx skills add AMinerOrg/aminer-open-skill --list
```

按需安装到当前项目（省略 `--global`）或用户全局（加 `--global`）。`--agent` 取值如 `claude-code`、`codex`、`openclaw`、`cursor`、`trae`：

```bash
# 只安装免费入口，安装到当前项目的 Claude Code
npx skills add AMinerOrg/aminer-open-skill --agent claude-code --skill aminer-free-academic --yes

# 安装多个技能到 Codex 全局
npx skills add AMinerOrg/aminer-open-skill --global --agent codex \
  --skill aminer-free-academic --skill aminer-academic-search --yes

# 安装全部技能
npx skills add AMinerOrg/aminer-open-skill --global --agent claude-code --skill '*' --yes
```

查看与更新：

```bash
npx skills list --global
npx skills update --global --yes
```

`npx skills` 只管理技能文件，Python 依赖见 [Python 依赖](#4-python-依赖)；slash command 需要 [插件安装](#2-claude-code-插件安装)。

## 2. Claude Code 插件安装

本仓库自带插件清单 [`.claude-plugin/marketplace.json`](.claude-plugin/marketplace.json)（市场名 `aminer-open-skills`），每个技能是一个插件。在 Claude Code 中执行：

```text
/plugin marketplace add AMinerOrg/aminer-open-skill
/plugin install aminer-free-academic@aminer-open-skills
```

其他技能将 `aminer-free-academic` 替换为 [技能目录](SKILLS.md) 中的名称即可；也可以只执行第一行，再用 `/plugin` 打开界面勾选。更新版本：

```text
/plugin marketplace update aminer-open-skills
```

插件方式会同时注册技能自带的 slash command（`commands/` 目录），命令带插件名前缀，例如 `/aminer-daily-paper:aminer-dp`、`/aminer-deep-search:aminer-deep-search`。

## 3. 手动安装（Codex / OpenClaw / 其他 Agent）

```bash
git clone https://github.com/AMinerOrg/aminer-open-skill.git ~/ai-skills/aminer-open-skill
```

将需要的 `skills/<skill-name>/` 整个目录放入 Agent 的技能目录：

| Agent | 用户级技能目录 | 项目级技能目录 |
|---|---|---|
| Claude Code | `~/.claude/skills/` | `<项目>/.claude/skills/` |
| Codex | `~/.codex/skills/` | — |
| OpenClaw 等其他 Agent | 见各自文档 | 见各自文档 |

推荐用软链接代替复制，之后在 clone 目录里 `git pull` 即可更新：

```bash
ln -s ~/ai-skills/aminer-open-skill/skills/aminer-free-academic ~/.codex/skills/aminer-free-academic
```

手动安装不会注册 slash command（命令文件依赖插件环境变量 `CLAUDE_PLUGIN_ROOT`），直接用自然语言触发技能即可。

## 4. Python 依赖

技能脚本需要 `python3`。多数技能只用标准库；下列技能需要额外安装依赖：

| 技能 | 依赖 |
|---|---|
| `aminer-daily-paper` | PyYAML |
| `aminer-pdf-ocr` | requests、pypdf |
| `aminer-exp-extraction` / `pdf-citation-verifier` / `structured-reference-audit` | requests |
| `deep-research` | matplotlib（报告插图） |
| `sota-finder` | openpyxl（导出 Excel） |
| `baseline-finder` | httpx、openai、pypdf |

7 个科研工作流技能（`aminer-topic-advisor-selection` / `aminer-paper-deep-reading` / `aminer-journal-paper-write-review-revise` / `aminer-experiment-to-paper` / `aminer-degree-thesis-proposal-to-defense` / `aminer-grant-application` / `aminer-patent-tech-intelligence`）只依赖标准库，无需额外安装。

```bash
python3 -m pip install -r skills/<skill-name>/requirements.txt
```

`baseline-finder` 也提供独立 CLI；按其 [SKILL.md](skills/baseline-finder/SKILL.md) 将技能目录本身安装到隔离环境，可同时安装依赖并注册 `baseline-finder` 命令。

`structured-reference-audit` 还需要可访问的 [GROBID](https://github.com/kermitt2/grobid) 服务，或已有的 TEI 文件。

## 5. 配置 Token

在 [AMiner 控制台](https://open.aminer.cn/open/board?tab=control)生成 Token，然后在 AI 助手使用的环境中配置 `AMINER_API_KEY`：

```bash
export AMINER_API_KEY="<YOUR_TOKEN>"
```

本地 Claude Code、Codex 等对话式会话可以使用仓库提供的快速配置工具：

```text
Windows：       tools\setup-aminer-token.cmd
PowerShell：    .\tools\setup-aminer-token.ps1
macOS/Linux：   ./tools/setup-aminer-token.sh
```

OpenClaw 使用自己的环境配置：

```bash
openclaw config set env.vars.AMINER_API_KEY "<YOUR_TOKEN>"
```

独立 CLI、CI 和定时任务需要在各自运行环境中配置 Token。并非所有技能都需要 Token，配置前先查看 [技能目录](SKILLS.md) 的 Token 列。

## 6. Token 与计费注意事项

- 不要打印、记录或提交 `AMINER_API_KEY`。
- `aminer-exp-extraction` 调用的是智谱 BigModel API：请为它配置 `BIGMODEL_API_KEY`（可回退 `OPENAI_API_KEY`），它不使用 AMiner Token。
- AMiner 免费接口仍需 Token。建议先用 `aminer-free-academic`，仅在必要时调用计费 API。
- 部分任务会产生 API 费用。执行大规模检索或高成本调用前，应先查看预估成本。
- `tools/` 下的配置工具只面向本地对话式环境。OpenClaw、CLI、CI 和定时任务需要单独配置。
- 如果需要直接集成 API 而不是使用 Skill，请参考 [AMiner 开放平台文档](https://open.aminer.cn/open/docs)。

## 7. 仓库目录结构

```text
aminer-open-skill/
├── .claude-plugin/marketplace.json   # Claude 插件清单
├── tools/                            # 本地会话的 Token 快速配置脚本
└── skills/
    ├── <skill-name>/
    │   ├── SKILL.md                  # 技能定义：frontmatter + 规则 + 工作流，触发后由 agent 加载
    │   ├── SKILL.zh.md               # 中文镜像（部分技能提供）
    │   ├── commands/                 # slash command（部分技能提供）
    │   ├── scripts/                  # 调用 AMiner 开放平台的工具脚本
    │   ├── references/               # 提示词与参考规则
    │   ├── evals/                    # 评测样例
    │   └── requirements.txt
    └── ...
```
