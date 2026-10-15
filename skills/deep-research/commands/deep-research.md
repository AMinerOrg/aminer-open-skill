---
description: Produce a cited research report and evidence ledger from AMiner data and web tools
argument-hint: "[research topic | topic: ... genre: academic|industry]"
allowed-tools: Read, Bash, Glob, Grep, WebSearch, WebFetch
---

# /deep-research - Deep Research

User invoked the deep-research skill with the following arguments:

```text
$ARGUMENTS
```

## Your task

Follow `${CLAUDE_SKILL_DIR}/SKILL.md`. You are the researcher: scout the question, induce the outline from what retrieval returns, retrieve per section, keep every source in an evidence ledger, and write a cited report where each claim points back to a retrieved source. No claim reaches the report without a ledger source.

Use this command for tasks that need a sourced report — literature review, research landscape, entity investigation, trend comparison, or industry / market survey — not for a single lookup or a bare bibliography.

### 1. Parse `$ARGUMENTS`

- `topic`: required research topic. Preserve the user's wording. If absent or too vague, ask for a concrete topic (at most two questions, and only when different answers would change the scope).
- `genre`: optional, `academic` (default — literature reviews, landscapes, investigations) or `industry` (industry / market surveys: "行业调研", "市场格局", "竞争格局").

### 2. Pre-flight

Check the key without printing it:

```bash
[ -z "${AMINER_API_KEY:-}" ] && echo "AMINER_API_KEY missing" || echo "AMINER_API_KEY exists"
```

If missing, stop and ask the user to set `AMINER_API_KEY` (console: https://open.aminer.cn/open/board?tab=control). Never print the key. The scripts are pure stdlib — no dependency installation is needed except `matplotlib` for figure rendering (see `requirements.txt`).

Set the workspace once — the skill owns no ledger location, the path is the host's choice. The default (overridable via `$DR_WORKDIR`) is a **per-run** directory under the current project: `outputs/<topic-slug>-<YYYYMMDD-HHMM>/`, resolved to an absolute path at invocation time. Derive the slug from the topic (letters / digits / CJK / hyphens, ≤40 chars); every run gets its own directory, so runs never overwrite each other:

```bash
export DR_WORKDIR="${DR_WORKDIR:-$(pwd)/outputs/<topic-slug>-$(date +%Y%m%d-%H%M)}"
export DR_LEDGER="${DR_WORKDIR}/evidence-ledger.json"
mkdir -p "$DR_WORKDIR/figures"
```

Tell the user the resolved absolute ledger path before starting (e.g. `ledger → /abs/path/outputs/rag-evaluation-20260826-1432/evidence-ledger.json`) — nothing should land in a mystery location. Every `evidence.py` / `evaluate.py` call then reads `$DR_LEDGER` (or pass `--state` / `--ledger` explicitly); keep figures under `${DR_WORKDIR}/figures/`, the appendix next to the ledger, and the report under `${DR_WORKDIR}/`. Never write the ledger under `${CLAUDE_SKILL_DIR}` (the skill tree is read-only source).

Answer in the user's language unless they ask otherwise.

### 3. Run the research loop

Execute the Method from `${CLAUDE_SKILL_DIR}/SKILL.md`, following `references/research-loop.md`:

- **Round 0 — scout, then induce.** `evidence.py init --topic "..."` (add `--genre industry` for an industry report), run 3–4 `paper_qa_search_pro` probes in `query_type: "auto"` separated by object and structured filter, triage with free `paper_info`, buy `paper_detail` for keepers, then induce 2–4 numbered top-level sections (one a `disagreement` subsection) from what came back. Do not invent section titles before retrieval.
- **Each round** — retrieve per section (AMiner via `scripts/aminer_open.py` + the host's `WebSearch` / `WebFetch`) → `add --aminer` / web sources tagged `--probe <id>`, then tag the keepers with `--section <id>` and `drop` the noise → read (free `paper_info` before paid `paper_detail`) → `evidence.py gaps` → decide whether to continue. For an industry report, capture every number you will cite as a datum (`evidence.py datum add`), web-first.
- **Wrap-up** — `evidence.py check` must exit 0 (a ¥20 accumulated spend blocks it); `render --final` gives the ledger view (numbering, claims per section, bibliography) and `render --appendix --out auto` writes the appendix file; then **write the report as prose from the ledger's claims — do not paste `render --final` into the body**. If the report has figures, run `figure add` → `scripts/chartrender.py` → `figure mark-rendered` first.

Cost control: free first; route by query shape (`paper_qa_search_pro` ¥0.70 default, `paper_search_pro` ¥0.01 for structured filters); at ¥10 show the call plan and wait for confirmation (`--confirm-high-cost`), at ¥20 `check` blocks. A typical run lands near ¥4–6.

### 4. Present the result

Report the report path, the ledger path, and the total spend (from the ledger). If AMiner returned fewer sources than the topic needed, ship a clearly limited report and say so in the Limitations section — never fabricate sources or citations. If the run fails due to missing configuration or API errors, show the actionable error without exposing the key.
