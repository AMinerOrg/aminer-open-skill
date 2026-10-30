---
name: pdf-citation-verifier
version: 1.0.0
author: AMiner
contact: report@aminer.cn
description: >
  [Activation] Use this skill when the user provides a paper PDF (file path or upload) and asks to verify, audit, or fact-check its references / citations / bibliography — e.g. "check whether the references in this PDF are hallucinated", "find fake citations", "verify the bibliography".
  [Capability] Uploads the PDF to the AMiner pdf-citation-verifier service, polls the asynchronous job, and returns a per-reference classification (REAL / LIKELY_REAL / NEEDS_REVIEW / LIKELY_FAKE / FAKE) plus an overall hallucination summary.
  [Routing] Do NOT use for general paper search, scholar lookup, citation-intent analysis, or building a citation graph — use aminer-academic-search, aminer-free-academic, or paper-source-trace instead. This skill only verifies whether references actually exist.
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

# PDF Citation Verifier

Verify whether the references in a paper PDF actually exist by submitting the PDF to the AMiner `pdf-citation-verifier` service, polling the asynchronous job, and returning a structured summary. Invoke via natural language or `/pdf-citation-verifier`.

## What This Skill Does

For each reference parsed from the uploaded PDF, the upstream service queries AMiner SearchPro and labels the citation with one of:

- `REAL` — high-confidence match in AMiner.
- `LIKELY_REAL` — partial match, likely genuine.
- `NEEDS_REVIEW` — evidence is inconclusive; ask a human.
- `LIKELY_FAKE` — partial mismatch, probably fabricated.
- `FAKE` — no plausible match found.

Each call to the gateway returns the standard envelope `{"code": 200, "success": true, "msg": "", "data": ..., "log_id": "..."}`. The script unwraps it before printing.

- `POST /api/v3/paper/citation/verify/upload` returns `data: {"job_id": "verify_..."}`.
- `GET /api/v3/paper/citation/result?job_id=...` returns `data: [<record>]` where the single record has top-level fields like `is_finish`, `has_hallucination`, `hallucination_ratio`, `total`, `counts_by_status`, `summary`, `urls`, `report`, `result`.
- Whenever the script sees `is_finish: true`, it also auto-downloads `urls.result` (the per-reference JSON) and inlines it as `details` on the returned payload — so a single `--output` file contains both the summary and every record's `status` / `confidence` / `title` / `first_author` / `key_reasons` / `top_match`, with no need to follow the 5-minute OSS link.

The skill returns that record plus the `job_id` so the user can re-poll later.

## File Map

- `SKILL.md` / `SKILL.zh.md` — English / Chinese skill definitions (this file).
- `commands/pdf-citation-verifier.md` — slash command entry.
- `scripts/verify_pdf.py` — HTTP client: upload → poll → print the unwrapped result record.
- `scripts/render_report.py` — renders the result JSON into a self-contained HTML report card (stdlib only).
- `requirements.txt` — Python dependencies (`requests`).

## Pre-flight

Run these checks before invoking the script. Stop and surface the error to the user if any check fails.

**1. AMINER_API_KEY**

```bash
[ -z "${AMINER_API_KEY+x}" ] && echo "AMINER_API_KEY missing" || echo "AMINER_API_KEY exists"
```

If missing, stop and tell the user to obtain a token from https://open.aminer.cn and `export AMINER_API_KEY=<token>`. **Never print the token value.**

**2. Python dependency**

```bash
python3 - <<'PY'
import importlib.util
missing = [name for name in ("requests",) if importlib.util.find_spec(name) is None]
print("Missing: " + ", ".join(missing) if missing else "Python dependencies exist")
PY
```

If missing, instruct: `pip install -r "${CLAUDE_PLUGIN_ROOT}/requirements.txt"`.

**3. PDF input**

The user must supply an existing local `.pdf` file path. If they only describe a paper without a file, ask them to provide the PDF path. Do not invent or download a PDF.

## Execution Example

Basic verification with defaults (max 50 references, auto-polls until done):

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/verify_pdf.py" \
  --pdf "/abs/path/to/paper.pdf"
```

Full options:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/verify_pdf.py" \
  --pdf "/abs/path/to/paper.pdf" \
  --max-refs 80 \
  --strict \
  --timeout 900 \
  --poll-interval 5 \
  --output outputs/pdf-citation-verifier/<safe-paper-stem>/result.json
```

Submit-only (no polling, return `job_id` for later lookup):

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/verify_pdf.py" \
  --pdf "/abs/path/to/paper.pdf" --no-wait
```

Fetch the result for an existing `job_id` (no new upload):

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/verify_pdf.py" \
  --job-id verify_20260527T090207Z_a72c9ba5
```

## Parameters

| Flag | Default | Notes |
| --- | --- | --- |
| `--pdf` | required (unless `--job-id`) | Local `.pdf` file path. Server caps body at 50 MB. |
| `--job-id` | – | Skip upload and just fetch the result for an existing job. |
| `--max-refs` | 50 | Server hard cap is 100. |
| `--strict` | off | Stricter FAKE judgement on partial matches. |
| `--no-wait` | off | With `--pdf`: submit and return `job_id` without polling. With `--job-id`: single fetch, return immediately without looping. |
| `--timeout` | 600 | Overall polling timeout in seconds. |
| `--poll-interval` | 5 | Seconds between result polls. |
| `--request-timeout` | 120 | Per-HTTP-request timeout. |
| `--output` | - | Optional path to also write the JSON response. |

## Environment Variables

| Var | Required | Purpose |
| --- | --- | --- |
| `AMINER_API_KEY` | yes | JWT used in the `Authorization` header. |
| `PDF_CITATION_VERIFIER_BASE_URL` | no | Override the gateway base URL. Defaults to `https://datacenter.aminer.cn/gateway/open_platform`. |

## Runtime Constraints

- **Never** print, log, or echo the value of `AMINER_API_KEY`.
- **Never** fabricate verification verdicts. If the script fails or times out, surface the error verbatim — do not synthesize results.
- `urls`, `report`, `result`, `pdf` in the response point to server-side artifacts and may be pre-signed for `url_expire_seconds`. Do not claim those local paths exist on the user's machine. Use `--output` if the user needs a local copy of the JSON.
- Respect the per-user active job cap (server returns 429 when exceeded). If a 429 surfaces, stop and tell the user to wait for prior jobs to finish.
- Treat any `LIKELY_FAKE` / `FAKE` verdict as a flag for human review, not a final accusation. Surface `counts_by_status` and per-record reasons when the response includes them.

## Output Presentation

After the script returns, summarize the result for the user with at minimum:

- `job_id`
- `total` (number of references verified)
- `has_hallucination`, `hallucination_ratio`
- A short table built from `counts_by_status` (REAL / LIKELY_REAL / NEEDS_REVIEW / LIKELY_FAKE / FAKE / etc.)
- If `details.records[]` is present (auto-fetched from `urls.result`), list each FAKE / LIKELY_FAKE / NEEDS_REVIEW record's `title`, `first_author`, `year`, and `key_reasons` so the user does not have to follow the 5-minute OSS link
- Any `urls.report` / `urls.result` links from the response, with a note that they may expire after `url_expire_seconds`
- If `website_records[]` is present, list each entry's `raw` (first ~80 chars), the reachable URL(s), and its original `status`; then show `website_summary` (`total_website_citations`, `adjusted_hallucination_ratio`). Explicitly note that `adjusted_hallucination_ratio` excludes website-type citations and that the original `hallucination_ratio` is still in the payload.
- The full JSON should be either saved (via `--output`) or echoed back to the user, never silently dropped.

## HTML Report Card

After the verification finishes (and after the Local Non-Reference Filter when it applies), generate a visual report card with the standard renderer — do not hand-write ad hoc HTML:

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/render_report.py" \
  --input "<result-json-path>" \
  --output "<same-dir>/report.html" \
  --lang zh   # zh when the conversation is mainly Chinese, en otherwise
```

- `--input` is the JSON written by `verify_pdf.py --output` (must contain `summary`; `details.records` enables the per-record focus table). Prefer the `.filtered.json` when the Local Non-Reference Filter produced one.
- The output is a single self-contained HTML file (inline CSS, no external assets): an overview card with the fake-ratio headline number, a five-color stacked status bar with legend, and a focus table listing each FAKE / LIKELY_FAKE / NEEDS_REVIEW record with its verdict badge, citation info, closest `top_match`, and human-readable reasons.
- All numbers come verbatim from the input JSON; the renderer never re-classifies records.
- Tell the user the report path and offer to `open` it in the browser. If no `--output` JSON exists (chat-only run), skip the report or first write the payload to a temp JSON.

## Local Non-Reference Filter

When `is_finish=true` and `details.records[]` is present, perform a local agent review before presenting the final summary. This review uses the current Claude Code/Codex agent only; do not call another LLM API, do not ask for an extra key, and do not send records back to the server.

Filter conservatively. Remove only records that are clearly not bibliography references, such as body-text contamination, figure/table/stage/evaluation prose, appendix or section headings, page headers/footers, page numbers, captions, or non-citation narrative sentences. Do **not** remove a record merely because its status is `FAKE`, `LIKELY_FAKE`, or `NEEDS_REVIEW`, because AMiner has no match, or because metadata is incomplete. Ambiguous records stay in `filtered_records`.

Use only these record fields for the review: `id`, `status`, `confidence`, `title`, `first_author`, `year`, `raw`, `key_reasons`, and `top_match`. Prioritize `raw`; use `title` and `key_reasons` only as supporting signals.

Produce an auditable filtered payload:

- Preserve the original service payload unchanged.
- Add `llm_filter` only to records removed by the local review:
  - `is_reference: false`
  - `reason: "<short reason>"`
  - `confidence: <0.0-1.0>`
- Add `filtered_records` containing all retained records.
- Add `removed_non_reference_records` containing removed records with their `llm_filter`.
- Add `filtered_summary` recomputed only from `filtered_records`:
  - `total`
  - `counts_by_status`
  - `has_hallucination`
  - `hallucination_ratio = (FAKE + LIKELY_FAKE) / total`, or `0` when total is `0`

If the user supplied `--output path.json`, write the filtered payload next to it as `path.filtered.json` (for example, `result.json` -> `result.filtered.json`). If the output path has no `.json` suffix, append `.filtered.json`. If no `--output` was used, do not create a new file; present the filtered summary and removed records in the final answer.

If the inline details fetch failed, the payload carries a `details_fetch_error` string — surface it and tell the user to GET `urls.result` themselves before `url_expire_seconds` runs out.

If `is_finish` is `true` and a `status` / `msg` field signals failure, report it and suggest re-running.

## URL / Website Citation Re-verification

After the Non-Reference filter completes and `filtered_records` is ready, run a second pass to identify **website-type citations** — references that point to a real webpage (RFC, blog post, GitHub README, standards doc, product page) rather than a journal / conference paper. AMiner SearchPro is paper-centric, so those citations often land in `LIKELY_REAL / NEEDS_REVIEW / LIKELY_FAKE / FAKE` even when the underlying URL is perfectly valid. This pass flags them so the user can distinguish "fake academic reference" from "legitimate website citation".

Scope:

- Operate only on `filtered_records` (never on `removed_non_reference_records`).
- Consider only records whose `status` is one of `LIKELY_REAL / NEEDS_REVIEW / LIKELY_FAKE / FAKE` (skip `REAL`).
- Read URLs **only** from the `raw` field. Extract with a conservative regex like `https?://[^\s<>"'()]+`. Deduplicate per record.
- If a record has no URL in `raw`, leave it untouched — no metadata added.

Probing rules (use the hosting agent's WebFetch tool; do NOT call any external LLM API and do NOT require an extra key):

- HTTP 2xx or 3xx (allow up to 3 redirects) → `reachable`.
- Any other status / timeout / DNS failure → `unreachable`.
- 401 / 403 → `unreachable_paywalled` (do not treat as reachable).
- Skip URLs that resolve to `localhost` or private IP ranges (10/8, 172.16/12, 192.168/16, 169.254/16, ::1, fc00::/7).
- Per-URL timeout: 15s. At most 3 URLs per record; if a record has more, set `url_probe_truncated: true` on that record and probe the first 3 only.
- Never fabricate an HTTP response. On WebFetch failure, record `unreachable` with the error verbatim in `reason`.
- Do not send record data to any third-party service beyond the URL host itself.

For every record that contains at least one URL, attach a `url_verification` object:

```json
"url_verification": {
  "urls": ["<url1>", "<url2>"],
  "reachable_urls": ["<url1>"],
  "is_website_citation": true,
  "reason": "<short reason>",
  "url_probe_truncated": false
}
```

`is_website_citation` is `true` iff at least one URL is `reachable`.

Add two new top-level fields to the returned payload:

- `website_records`: every record where `is_website_citation: true`. **Do NOT change its original `status`.** The WEBSITE label lives only in the agent-side view; the server verdict is preserved for audit.
- `website_summary`:
  - `total_website_citations`: N (count of records in `website_records`)
  - `from_status`: `{ "LIKELY_REAL": a, "NEEDS_REVIEW": b, "LIKELY_FAKE": c, "FAKE": d }`
  - `adjusted_hallucination_ratio`: `(FAKE_count + LIKELY_FAKE_count − c − d) / max(filtered_total − N, 1)`
  - `note`: `"WEBSITE citations excluded from academic-hallucination ratio."`

Output file conventions (mirror the Non-Reference filter):

- If the user gave `--output path.json`, also write `path.website_verified.json` alongside `path.filtered.json`. If the output path has no `.json` suffix, append `.website_verified.json`.
- If no `--output`, do not create new files; only surface the results in the reply.

Do NOT change the server-side `hallucination_ratio` or `counts_by_status`. All website-aware numbers live in `website_summary` only.
