<div align="center">
  <h1>AMiner Open Skills</h1>
  <p>
    <a href="LICENSE"><img alt="License" src="https://img.shields.io/badge/license-MIT-2ea44f"></a>
    <a href=".claude-plugin/marketplace.json"><img alt="Version" src="https://img.shields.io/badge/version-1.15.0-0969da"></a>
    <a href="SKILLS.en.md"><img alt="Skills" src="https://img.shields.io/badge/skills-21-0ea5e9"></a>
    <a href="INSTALL.en.md"><img alt="Install" src="https://img.shields.io/badge/install-Claude%20Code%20%7C%20Codex%20%7C%20OpenClaw-111827"></a>
    <a href="README.md"><img alt="Language" src="https://img.shields.io/badge/language-English%20%7C%20中文-1f6feb"></a>
  </p>
  <p>
    <a href="https://www.aminer.cn/">Website</a>
    · <a href="#use-online-research-workflow-skills">Use online</a>
    · <a href="SKILLS.en.md">Skill Catalog</a>
    · <a href="INSTALL.en.md">Installation</a>
    · <a href="https://open.aminer.cn/open/docs">Open Platform Docs</a>
    · <a href="README.md">中文</a>
  </p>
  <p>
    <img src="assets/readme-banner-en-v2.png" alt="AMiner Open Skills: research skills powered by real academic data" width="100%">
  </p>
  <p>
    <b>AMiner web app: Smart Search, AI Reading, Res Labs, AI2000 and more built in — visit <a href="https://www.aminer.cn">https://www.aminer.cn</a></b>
  </p>
</div>

---

`aminer-open-skill` collects reusable research skills built on AMiner academic data for the full research lifecycle, emphasizing real academic data, verifiable evidence chains, and directly usable research artifacts.

## Use online: research workflow skills

The following 7 skills can be used directly in the AMiner web app: click the button on the right to open one, no installation needed. They can also be installed to a local agent, see [Installation Guide](INSTALL.en.md).

| Skill | What it does | Try&nbsp;online |
|---|---|:---:|
| **Paper deep reading** | Close reading, line-by-line translation, reproduction audits | [![Try online](https://img.shields.io/badge/Try_online_%E2%86%97-1f6feb?style=for-the-badge)](https://www.aminer.cn/?skill=aminer-paper-deep-reading) |
| **Journal manuscript writing, review, and revision** | Draft with real citations, mock review, reply to reviewers | [![Try online](https://img.shields.io/badge/Try_online_%E2%86%97-1f6feb?style=for-the-badge)](https://www.aminer.cn/?skill=aminer-journal-paper-write-review-revise) |
| **From experiments to manuscript** | Debug experiments, write up results, verify methods | [![Try online](https://img.shields.io/badge/Try_online_%E2%86%97-1f6feb?style=for-the-badge)](https://www.aminer.cn/?skill=aminer-experiment-to-paper) |
| **Thesis proposal to defense** | Proposal novelty check, chapter drafting, defense prep | [![Try online](https://img.shields.io/badge/Try_online_%E2%86%97-1f6feb?style=for-the-badge)](https://www.aminer.cn/?skill=aminer-degree-thesis-proposal-to-defense) |
| **Project application** | Parse the call, frame the question, draft, mock review | [![Try online](https://img.shields.io/badge/Try_online_%E2%86%97-1f6feb?style=for-the-badge)](https://www.aminer.cn/?skill=aminer-grant-application) |
| **Research topic and advisor selection** | Assess topic novelty; compare a department’s advisors | [![Try online](https://img.shields.io/badge/Try_online_%E2%86%97-1f6feb?style=for-the-badge)](https://www.aminer.cn/?skill=aminer-topic-advisor-selection) |
| **Industry intelligence and patents** | Tech surveys, prior-art search, claims, OA replies | [![Try online](https://img.shields.io/badge/Try_online_%E2%86%97-1f6feb?style=for-the-badge)](https://www.aminer.cn/?skill=aminer-patent-tech-intelligence) |

## Local skills

The other 14 skills run in a local agent (Claude Code, Codex, OpenClaw, and others); see [Quick install](#quick-install) below. Follow the link after each category for full details and example prompts.

**Search and discovery** · [Examples and details →](SKILLS.en.md#search-and-discovery)

- [`aminer-free-academic`](skills/aminer-free-academic/SKILL.md): Free lookups of papers, scholars, institutions, venues, and patents
- [`aminer-academic-search`](skills/aminer-academic-search/SKILL.md): Full academic data queries (29 APIs), including structured experiment data
- [`aminer-daily-paper`](skills/aminer-daily-paper/SKILL.md): Paper recommendations by topic or scholar profile
- [`aminer-deep-search`](skills/aminer-deep-search/SKILL.md): Collect hundreds of candidate papers for a survey
- [`sota-finder`](skills/sota-finder/SKILL.md): Find SOTA results and build sourced leaderboards

**Reading and organizing** · [Examples and details →](SKILLS.en.md#reading-and-organizing)

- [`aminer-pdf-ocr`](skills/aminer-pdf-ocr/SKILL.md): Convert paper PDFs to full-text Markdown
- [`aminer-exp-extraction`](skills/aminer-exp-extraction/SKILL.md): Extract experiment details from paper Markdown as JSON
- [`scientific-taxonomy`](skills/scientific-taxonomy/SKILL.md): Organize a set of papers into a hierarchical taxonomy
- [`paper-source-trace`](skills/paper-source-trace/SKILL.md): Trace claims to cited sources and draw citation maps

**Research reports** · [Examples and details →](SKILLS.en.md#research-reports)

- [`deep-research`](skills/deep-research/SKILL.md): Write cited research reports with a traceable evidence ledger

**Paper experiment checks** · [Examples and details →](SKILLS.en.md#paper-experiment-checks)

- [`baseline-finder`](skills/baseline-finder/SKILL.md): Check whether a paper misses baselines it should compare against

**Citation checking** · [Examples and details →](SKILLS.en.md#citation-checking)

- [`pdf-citation-verifier`](skills/pdf-citation-verifier/SKILL.md): Verify that the references in a paper PDF actually exist
- [`structured-reference-audit`](skills/structured-reference-audit/SKILL.md): Conservative reference audit: unresolved does not mean fabricated
- [`citation-faithfulness`](skills/citation-faithfulness/SKILL.md): Check whether citations faithfully represent their sources

## Quick install

**1. Install skills** (requires Node.js 18+; replace `--skill` with the skills you need, or `'*'` for all):

```bash
npx skills add AMinerOrg/aminer-open-skill --agent claude-code --skill aminer-free-academic --yes
```

Claude Code users can also install as plugins, which also registers each skill's slash commands:

```text
/plugin marketplace add AMinerOrg/aminer-open-skill
/plugin install aminer-free-academic@aminer-open-skills
```

**2. Configure the token**: generate one in the [AMiner Console](https://open.aminer.cn/open/board?tab=control) and set it in the agent's environment:

```bash
export AMINER_API_KEY="<YOUR_TOKEN>"
```

**3. Start using**: describe your task in plain language and the agent picks the right skill.

Manual install, Python dependencies, OpenClaw setup, and billing notes are in the [Installation Guide](INSTALL.en.md).

## Feedback and contact

- Usage questions and bugs: [GitHub Issues](https://github.com/AMinerOrg/aminer-open-skill/issues)
- Email: [report@aminer.cn](mailto:report@aminer.cn)
- API access and billing: [AMiner Open Platform](https://open.aminer.cn/open/docs)

Skills in this repository are maintained by the AMiner team; external skill submissions are not accepted at this time. Released under the [MIT License](LICENSE).

## Star History

[![Star History Chart](https://api.star-history.com/svg?repos=AMinerOrg/aminer-open-skill&type=Date)](https://star-history.com/#AMinerOrg/aminer-open-skill&Date)
