#!/usr/bin/env python3
"""Minimal experiment-data extractor: md -> preprocess -> GLM filter -> GLM -> JSON.

Strips the skill's run/manifest/monitor machinery — just the core extraction
chain, reusable as a library or CLI. Dependencies: requests, pypdf-free (md
input only); reuses the vendored pipeline modules for prompt/repair/normalize
so output stays identical to the production workflow (prod-wf4 v0.8.0).

Both model stages call the same public BigModel service (default glm-5.3-flash, the fast variant; override with LLM_MODEL / --llm-model, e.g. glm-5.3 or glm-5.2):
sentence filter (GLM, SciBERT replacement) + extraction, both via
https://open.bigmodel.cn/api/paas/v4/chat/completions. No internal/AMiner
service is used anywhere in this skill.

Usage:
  # single paper
  python3 extract_experiments.py --md paper.md -o out.json

  # batch (one md per paper, named <paper_id>.md)
  python3 extract_experiments.py --md-dir md_papers/ -o-dir out_json/

Endpoints via env or flags:
  LLM_CHAT_URL      (default https://open.bigmodel.cn/api/paas/v4/chat/completions)
  LLM_MODEL         (default glm-5.3-flash; glm-5.3 / glm-5.2 also valid)
  BIGMODEL_API_KEY  (BigModel auth for BOTH stages; falls back to OPENAI_API_KEY)
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

SKILL_ROOT = Path(__file__).resolve().parent
if str(SKILL_ROOT) not in sys.path:
    sys.path.insert(0, str(SKILL_ROOT))

from pipeline.benchmark.stages.openai_chat_llm_client import OpenAIChatLLMClient
from pipeline.production.adapters.glm_sentence_filter import filter_sentences_glm
from pipeline.production.adapters.wf4_prompt_adapter import build_wf4_prompt_for_adapter
from pipeline.production.adapters.wf4_stages import (
    WF4_MAX_QWEN_SENTENCES,
    prepare_llm_inputs_wf4,
    run_llm_stage_wf4,
)

# Frozen production semantic params (Guardrail #1 of the source skill).
BERT_THRESHOLD = 0.6
LLM_TEMPERATURE = 0.05
LLM_MAX_TOKENS = 2048


def filter_sentences(
    sentences: list[str],
    *,
    paper_title: str,
    llm_client: OpenAIChatLLMClient | None = None,
) -> tuple[list[str], dict]:
    """Stage-A: GLM sentence filter (the only filter backend — no SciBERT).

    Returns (kept_sentences, filter_stats).
    """
    resp = filter_sentences_glm(
        sentences, paper_title=paper_title, client=llm_client,
        threshold=BERT_THRESHOLD, cap=WF4_MAX_QWEN_SENTENCES,
    )
    stats = {
        "filter": "glm",
        "kept_count": resp["kept_count"],
        "total": resp["total"],
        "elapsed_sec": resp["elapsed_sec"],
    }
    return resp["kept"], stats


def extract_paper(
    md_path: Path,
    *,
    llm_url: str,
    llm_model: str = "glm-5.3-flash",
    paper_id: str | None = None,
    request_timeout: int = 180,
) -> dict:
    """One paper through the full chain. Returns the extraction result dict."""
    pid = paper_id or md_path.stem
    t0 = time.perf_counter()

    # Stage-P: preprocess (strip references + compact markdown) + section
    # union + split + wash. Produces english_sentences and paper_title.
    prepared = prepare_llm_inputs_wf4(md_path)

    # One shared BigModel client for BOTH model stages (sentence filter +
    # extraction) — keep-alive session, same key, same model.
    client = OpenAIChatLLMClient(
        api_url=llm_url, timeout=request_timeout, default_model=llm_model
    )

    # Stage-A: GLM sentence filter (score >= 0.6, cap 60).
    kept, filter_stats = filter_sentences(
        prepared.english_sentences,
        paper_title=prepared.paper_title,
        llm_client=client,
    )

    # Stage-B: WF4 prompt -> LLM -> JSON repair -> normalize (same code path
    # as production run_llm_stage_wf4; temperature/max_tokens frozen).
    from pipeline.production.adapters.wf8_stages import BertStageResult

    bert_result = BertStageResult(
        llm_input=kept,
        sentence_selection={"max_llm_sentences": WF4_MAX_QWEN_SENTENCES},
        bert_raw={"kept_count": len(kept), "total": len(prepared.english_sentences)},
        timings={"bert_filter": 0.0},
    )
    md_text = md_path.read_text(encoding="utf-8")
    stage = run_llm_stage_wf4(
        prepared, bert_result, client,
        llm_model_tag=llm_model or None,
        # BigModel's max_tokens includes reasoning tokens and glm-5.3 always
        # thinks (thinking.level=low), so the frozen answer budget (2048 on a
        # non-reasoning backend) becomes 8192 reasoning-inclusive here.
        num_predict_override=8192,
        full_text=md_text,  # dataset confidence scoring + fallback coercion
    )

    elapsed = round(time.perf_counter() - t0, 2)
    value = stage.value or {}
    return {
        "paper_id": pid,
        "paper_title": value.get("paper_title") or prepared.paper_title,
        "research_problem": value.get("research_problem"),
        "research_problem_description": value.get("research_problem_description"),
        "research_problem_aliases": value.get("research_problem_aliases") or [],
        "domain": value.get("domain"),
        "experiments": value.get("experiments") or [],
        "stats": {
            "sentences_total": len(prepared.english_sentences),
            "sentences_kept": len(kept),
            "filter": filter_stats,
            "experiments": len(value.get("experiments") or []),
            "parse_error": (stage.error or "") or None,
            "elapsed_sec": elapsed,
        },
    }


# Public-URL guard for --csv downloads (same policy as aminer-pdf-ocr's
# url_guard): http(s) only, host must resolve to public addresses, every
# redirect hop re-validated, response size capped.
MAX_REDIRECTS = 5
MD_MAX_BYTES = 32 * 1024 * 1024  # far above any paper markdown


class UrlGuardError(ValueError):
    """A --csv md_url points at a non-public or malformed target."""


def assert_public_http_url(url: str) -> None:
    """Allow only http(s) URLs whose host resolves to public addresses."""
    import ipaddress
    import socket
    from urllib.parse import urlparse

    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise UrlGuardError("only http(s) URLs are allowed")
    host = (parsed.hostname or "").strip("[]")
    if not host:
        raise UrlGuardError("URL is missing a hostname")
    lowered = host.lower()
    if lowered in {"localhost", "metadata.google.internal"} or lowered.endswith(".localhost"):
        raise UrlGuardError("refusing to fetch a local or metadata host")
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as exc:
        raise UrlGuardError(f"cannot resolve host {host}: {exc}") from exc
    for info in infos or []:
        ip = ipaddress.ip_address(info[4][0])
        if (ip.is_private or ip.is_loopback or ip.is_link_local
                or ip.is_reserved or ip.is_multicast or ip.is_unspecified):
            raise UrlGuardError("refusing to fetch a private or local URL")


def fetch_public_text(url: str, *, timeout: float, max_bytes: int = MD_MAX_BYTES) -> str:
    """GET a public URL as utf-8 text; redirects re-validated, size-capped."""
    from urllib.parse import urljoin

    import requests

    current = url
    for _ in range(MAX_REDIRECTS):
        assert_public_http_url(current)
        resp = requests.get(current, timeout=timeout, allow_redirects=False, stream=True)
        try:
            if resp.is_redirect or resp.is_permanent_redirect:
                location = resp.headers.get("Location")
                if not location:
                    raise UrlGuardError("redirect is missing Location")
                current = urljoin(current, location)
                continue
            resp.raise_for_status()
            chunks: list[bytes] = []
            total = 0
            for chunk in resp.iter_content(8192):
                if not chunk:
                    continue
                total += len(chunk)
                if total > max_bytes:
                    raise UrlGuardError(f"download exceeds {max_bytes} bytes")
                chunks.append(chunk)
            return b"".join(chunks).decode("utf-8", errors="replace")
        finally:
            resp.close()
    raise UrlGuardError("too many redirects")


def download_md(paper_id: str, md_url: str, cache_dir: Path, timeout: int = 60) -> Path:
    """Download a paper md by URL into cache_dir/<paper_id>.md (skip if cached).

    Refuses non-http(s), localhost/private-network, and metadata-host URLs.
    """
    target = cache_dir / f"{paper_id}.md"
    if target.exists() and target.stat().st_size > 0:
        return target
    target.write_text(fetch_public_text(md_url, timeout=timeout), encoding="utf-8")
    return target


def load_csv_pairs(csv_path: Path) -> list[tuple[str, str]]:
    """Read paper_id,md_url pairs from a CSV (header row optional)."""
    import csv

    pairs: list[tuple[str, str]] = []
    with open(csv_path, newline="", encoding="utf-8-sig") as fh:
        for row in csv.reader(fh):
            if len(row) < 2:
                continue
            pid, url = row[0].strip(), row[1].strip()
            if not pid or not url or pid.lower() == "paper_id":
                continue
            pairs.append((pid, url))
    return pairs


def main() -> int:
    ap = argparse.ArgumentParser(description="Minimal GLM experiment extractor")
    ap.add_argument("--md", type=Path, help="single markdown file of the paper")
    ap.add_argument("--md-dir", type=Path, help="directory of <paper_id>.md files")
    ap.add_argument("--csv", type=Path, help="CSV with paper_id,md_url rows (md downloaded to --md-cache)")
    ap.add_argument("--md-cache", type=Path, default=Path("md_cache"), help="download cache dir for --csv mode")
    ap.add_argument("-o", "--output", type=Path, help="output JSON path (single mode)")
    ap.add_argument("-o-dir", "--output-dir", type=Path, help="output dir (batch mode)")
    ap.add_argument("--llm-url", default=None, help="LLM chat URL (env LLM_CHAT_URL, default Zhipu BigModel)")
    ap.add_argument("--llm-model", default=None, help="LLM model id (env LLM_MODEL, default glm-5.3-flash)")
    ap.add_argument("--request-timeout", type=int, default=180)
    args = ap.parse_args()

    import os

    llm_url = (args.llm_url or os.environ.get("LLM_CHAT_URL") or
               "https://open.bigmodel.cn/api/paas/v4/chat/completions")
    llm_model = args.llm_model or os.environ.get("LLM_MODEL") or "glm-5.3-flash"

    from pipeline.production.adapters.gateway_auth import resolve_bigmodel_token
    # Both model stages (filter + extraction) authenticate against BigModel.
    if not resolve_bigmodel_token():
        print("ERROR: BIGMODEL_API_KEY not set — both the GLM sentence filter "
              "and the extraction stage need it (OPENAI_API_KEY accepted as "
              "fallback). Get one at https://open.bigmodel.cn/.", file=sys.stderr)
        return 1

    if args.csv:
        pairs = load_csv_pairs(args.csv)
        if not pairs:
            print(f"no paper_id,md_url rows found in {args.csv}", file=sys.stderr)
            return 1
        args.md_cache.mkdir(parents=True, exist_ok=True)
        jobs: list[tuple[Path, str]] = []
        for pid, url in pairs:
            try:
                jobs.append((download_md(pid, url, args.md_cache, timeout=args.request_timeout), pid))
            except Exception as exc:  # noqa: BLE001 — per-paper isolation
                print(f"[download] {pid}: FAIL {type(exc).__name__}: {exc}", file=sys.stderr)
    elif args.md:
        jobs = [(args.md, args.md.stem)]
    elif args.md_dir:
        if not args.output_dir:
            ap.error("--md-dir requires -o-dir")
        jobs = [(p, p.stem) for p in sorted(args.md_dir.glob("*.md"))]
    else:
        ap.error("provide --md, --md-dir, or --csv")
        return 1

    if not jobs:
        print("no papers to process", file=sys.stderr)
        return 1

    print(f"[extract] {len(jobs)} paper(s) | filter=glm | llm={llm_url} | model={llm_model}")
    ok = fail = 0
    for i, (md_path, pid) in enumerate(jobs, 1):
        try:
            result = extract_paper(
                md_path,
                llm_url=llm_url,
                llm_model=llm_model,
                paper_id=pid,
                request_timeout=args.request_timeout,
            )
            if args.md and args.output:
                out_path = args.output
            elif args.md:
                out_path = Path(md_path.stem + ".experiments.json")
            else:
                args.output_dir.mkdir(parents=True, exist_ok=True)
                out_path = args.output_dir / f"{pid}.json"
            out_path.write_text(
                json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
            )
            s = result["stats"]
            flag = "ERR" if s["parse_error"] else "ok"
            print(f"[{i}/{len(jobs)}] {pid}: {flag} "
                  f"exp={s['experiments']} sents={s['sentences_kept']}/{s['sentences_total']} "
                  f"{s['elapsed_sec']}s -> {out_path}")
            ok += 0 if s["parse_error"] else 1
            fail += 1 if s["parse_error"] else 0
        except Exception as exc:  # noqa: BLE001 — per-paper isolation
            print(f"[{i}/{len(jobs)}] {pid}: FAIL {type(exc).__name__}: {exc}",
                  file=sys.stderr)
            fail += 1
    print(f"[extract] done: {ok} ok, {fail} failed")
    return 0 if fail == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
