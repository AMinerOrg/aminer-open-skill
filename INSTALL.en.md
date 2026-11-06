# Installation Guide

[← Back to README](README.en.md) · [中文](INSTALL.md)

Every directory under `skills/` is an independently installable skill. Whichever method you use, keep the full skill directory (`SKILL.md`, `scripts/`, `references/`, etc.) — do not copy `SKILL.md` alone. Then configure the token as described in [Configure the token when required](#5-configure-the-token-when-required).

| Your environment | Recommended method |
|---|---|
| Claude Code, Codex, OpenClaw, Cursor, Trae, and other mainstream agents | [`npx skills`](#1-npx-skills-recommended) |
| Claude Code, with slash commands | [Plugin](#2-claude-code-plugin) |
| No network install, or a pinned version | [Manual install](#3-manual-install-codex--openclaw--other-agents) |

## 1. `npx skills` (recommended)

Requires [Node.js 18 or later](https://nodejs.org/); no global CLI install needed. List the installable skills first:

```bash
npx skills add AMinerOrg/aminer-open-skill --list
```

Install into the current project (omit `--global`) or for your user (add `--global`). `--agent` accepts values such as `claude-code`, `codex`, `openclaw`, `cursor`, `trae`:

```bash
# Free entry point only, into the current project's Claude Code
npx skills add AMinerOrg/aminer-open-skill --agent claude-code --skill aminer-free-academic --yes

# Several skills, globally for Codex
npx skills add AMinerOrg/aminer-open-skill --global --agent codex \
  --skill aminer-free-academic --skill aminer-academic-search --yes

# Every skill
npx skills add AMinerOrg/aminer-open-skill --global --agent claude-code --skill '*' --yes
```

List and update:

```bash
npx skills list --global
npx skills update --global --yes
```

`npx skills` manages skill files only — Python dependencies are covered in [Python dependencies](#4-python-dependencies); slash commands require the [plugin install](#2-claude-code-plugin).

## 2. Claude Code plugin

The repository ships a plugin manifest, [`.claude-plugin/marketplace.json`](.claude-plugin/marketplace.json) (marketplace name `aminer-open-skills`), with one plugin per skill. In Claude Code, run:

```text
/plugin marketplace add AMinerOrg/aminer-open-skill
/plugin install aminer-free-academic@aminer-open-skills
```

For other skills, replace `aminer-free-academic` with a name from the [Skill Catalog](SKILLS.en.md), or run only the first line and pick plugins in the `/plugin` UI. To pull new versions:

```text
/plugin marketplace update aminer-open-skills
```

The plugin install also registers each skill's slash commands (its `commands/` directory). They carry the plugin-name prefix, e.g. `/aminer-daily-paper:aminer-dp`, `/aminer-deep-search:aminer-deep-search`.

## 3. Manual install (Codex / OpenClaw / other agents)

```bash
git clone https://github.com/AMinerOrg/aminer-open-skill.git ~/ai-skills/aminer-open-skill
```

Put each selected `skills/<skill-name>/` directory, whole, into your agent's skill directory:

| Agent | User-level skill directory | Project-level skill directory |
|---|---|---|
| Claude Code | `~/.claude/skills/` | `<project>/.claude/skills/` |
| Codex | `~/.codex/skills/` | — |
| OpenClaw and other agents | see their docs | see their docs |

Prefer symlinks over copies, so a `git pull` in the clone updates the skills:

```bash
ln -s ~/ai-skills/aminer-open-skill/skills/aminer-free-academic ~/.codex/skills/aminer-free-academic
```

Manual installs do not register slash commands (command files depend on the plugin variable `CLAUDE_PLUGIN_ROOT`); trigger skills with natural language instead.

## 4. Python dependencies

Skill scripts need `python3`. Most skills use only the standard library; the following need extra packages:

| Skill | Dependencies |
|---|---|
| `aminer-daily-paper` | PyYAML |
| `aminer-pdf-ocr` | requests, pypdf |
| `aminer-exp-extraction` / `pdf-citation-verifier` / `structured-reference-audit` | requests |
| `deep-research` | matplotlib (report figures) |
| `sota-finder` | openpyxl (Excel export) |
| `baseline-finder` | httpx, openai, pypdf |

The seven research-workflow skills (`aminer-topic-advisor-selection` / `aminer-paper-deep-reading` / `aminer-paper-writing` / `aminer-experiment-to-paper` / `aminer-thesis-writing` / `aminer-grant-application` / `aminer-patent-tech-intelligence`) depend on the standard library only — no extra installation needed.

```bash
python3 -m pip install -r skills/<skill-name>/requirements.txt
```

`baseline-finder` also provides a standalone CLI. Install the skill directory itself in an isolated environment as described in its [SKILL.md](skills/baseline-finder/SKILL.md); this installs dependencies and registers the `baseline-finder` command.

`structured-reference-audit` also needs a reachable [GROBID](https://github.com/kermitt2/grobid) service or existing TEI files.

## 5. Configure the token when required

Generate a token in the [AMiner Console](https://open.aminer.cn/open/board?tab=control), then set `AMINER_API_KEY` in the environment used by your assistant:

```bash
export AMINER_API_KEY="<YOUR_TOKEN>"
```

For local Claude Code, Codex, and similar conversational sessions, the repository provides quick setup tools:

```text
Windows:       tools\setup-aminer-token.cmd
PowerShell:    .\tools\setup-aminer-token.ps1
macOS/Linux:   ./tools/setup-aminer-token.sh
```

OpenClaw uses its own environment configuration:

```bash
openclaw config set env.vars.AMINER_API_KEY "<YOUR_TOKEN>"
```

Standalone CLI commands, CI jobs, and scheduled tasks must set the token where the command runs. Not every skill requires a token — check the Token column of the [Skill Catalog](SKILLS.en.md) first.

## 6. Token and billing notes

- Never print, log, or commit `AMINER_API_KEY`.
- `aminer-exp-extraction` calls the Zhipu BigModel API instead: set `BIGMODEL_API_KEY` for it (`OPENAI_API_KEY` accepted as fallback). It never uses the AMiner token.
- Free AMiner APIs still require a token. Start with `aminer-free-academic` before using paid APIs.
- Some tasks may incur API charges. Review the estimated cost before approving large searches or expensive calls.
- The setup tools under `tools/` configure local chat sessions only. Set the token separately for OpenClaw, CLI, CI, and scheduled jobs.
- For direct API integration rather than Skill usage, see the [AMiner Open Platform documentation](https://open.aminer.cn/open/docs).

## 7. Repository layout

```text
aminer-open-skill/
├── .claude-plugin/marketplace.json   # Claude plugin manifest
├── tools/                            # quick token-setup scripts for local sessions
└── skills/
    ├── <skill-name>/
    │   ├── SKILL.md                  # skill definition: frontmatter + rules + workflow, loaded by the agent on trigger
    │   ├── SKILL.zh.md               # Chinese mirror (where provided)
    │   ├── commands/                 # slash commands (where provided)
    │   ├── scripts/                  # tool scripts calling the AMiner Open Platform
    │   ├── references/               # prompts and reference rules
    │   ├── evals/                    # evaluation samples
    │   └── requirements.txt
    └── ...
```
