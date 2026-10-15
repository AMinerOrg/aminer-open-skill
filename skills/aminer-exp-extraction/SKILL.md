---
name: aminer-exp-extraction
version: 1.0.0
author: AMiner
contact: report@aminer.cn
description: >
  [Activation] Use when the user provides paper markdown file(s) and requests experiment data extraction (methods, datasets, metrics, results).
  [Scope] For each paper md: preprocess -> GLM sentence filter (glm-5.3-flash, SciBERT replacement) -> LLM extraction (glm-5.3-flash) -> one JSON per paper. Both model stages call the same Zhipu BigModel chat-completions API. Extraction semantic params (prompt, temperature 0.05, cap 60) are frozen, identical to the production prod-wf4 workflow.
  [Routing] Input is local md files (--md/--md-dir) or paper_id+md_url CSV rows (--csv). Use aminer-pdf-ocr first when the source is a PDF (it produces the md). Use aminer-academic-search for searching papers by topic.
metadata:
  {"openclaw": {"emoji": "🧪", "requires": {"bins": ["python3"], "env": ["BIGMODEL_API_KEY"]}, "primaryEnv": "BIGMODEL_API_KEY"}}
---

# Experiment Data Extraction

One script, one chain: `md -> preprocess -> GLM filter -> LLM -> JSON`. No manifests, no run state, no monitoring — just extraction. A single model service (Zhipu BigModel, default `glm-5.3-flash`) powers both the sentence filter and the extraction.

## Pre-flight

1. Install `requests` from `requirements.txt`.
2. `BIGMODEL_API_KEY` must be set — it authenticates BOTH model stages (sentence filter + extraction) as `Authorization: Bearer` (`OPENAI_API_KEY` accepted as fallback). Never print key values. No other credential or internal service is used.
3. Optional overrides (env or flags):
   - `LLM_CHAT_URL` — default `https://open.bigmodel.cn/api/paas/v4/chat/completions` (used by both stages)
   - `LLM_MODEL` — default `glm-5.3-flash` (fast variant, used by both stages; `glm-5.3` / `glm-5.2` also valid)
4. Input is the paper's markdown: a LOCAL file (`--md`/`--md-dir`), or `paper_id,md_url` CSV rows (`--csv`, md downloaded to `--md-cache`, cached across re-runs). Local mode: file stem = paper_id.

## Run

```bash
# single paper
python3 extract_experiments.py --md /path/to/paper.md -o out.json

# batch: one md per paper, named <paper_id>.md
python3 extract_experiments.py --md-dir md_papers/ -o-dir out_json/

# batch from paper_id + md_url (CSV: header paper_id,md_url; md downloaded to md_cache/)
python3 extract_experiments.py --csv papers.csv --md-cache md_cache/ -o-dir out_json/
```

Per-paper failures don't stop the batch; exit code 2 means at least one failed. CSV downloads are cached — re-runs skip already-downloaded papers.

## Output

One JSON per paper: `paper_id`, `paper_title`, `research_problem(_description/_aliases)`, `domain`, `experiments[]` (name, type, methods, datasets, metrics, key_results, conclusion, limitations, evidence), plus `stats` (sentence counts, filter backend, elapsed). Schema identical to the production workflow's predictions.

## API contract

The skill contacts exactly ONE service: the public Zhipu BigModel chat-completions API. No internal/AMiner gateway is called anywhere (the SciBERT `/filter/batch` path was removed; stale vendored call sites raise explicitly).

- Sentence filter (Stage-A, GLM): one chat call to `{LLM_CHAT_URL}` with a numbered-sentence scoring prompt (system prompt + user prompt, `temperature: 0.05`). GLM returns `{"kept": [{"i", "score"}, ...]}`; client keeps score ≥ 0.6 (frozen threshold), original order, cap 60 (`WF4_MAX_QWEN_SENTENCES`). Unparseable response is a hard error; an explicitly empty kept list is a legitimate "no experiment sentences" result.
- Extraction (Stage-B): `POST {LLM_CHAT_URL}` (Zhipu BigModel `https://open.bigmodel.cn/api/paas/v4/chat/completions`, default model `glm-5.3-flash`) standard OpenAI messages format, `stream: false`, `temperature: 0.05`, `max_tokens: 2048` (frozen). Auth: `Authorization: Bearer $BIGMODEL_API_KEY`.
- Paper md download (`--csv` mode) fetches the user-provided `md_url` (public OSS/HTTP link) into `--md-cache`; no AMiner API is queried. Non-http(s), localhost/private-network, and metadata-host URLs are refused, redirects are re-validated per hop, and downloads are size-capped (same policy as `aminer-pdf-ocr`).
