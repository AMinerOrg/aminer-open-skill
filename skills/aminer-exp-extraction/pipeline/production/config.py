"""Configuration for the production layer (板块 6)."""

from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]

# Remote rule/ML pack (frozen — never rename/move the top dir).
PACK_ROOT = PROJECT_ROOT / "rule_ml_extraction_from_promote" / "rule_extraction_pack"
PACK_ML_SRC = PACK_ROOT / "ml_classification" / "src"
PACK_ML_MODELS = PACK_ROOT / "ml_classification" / "models"

# Output area for production runs.
PRODUCTION_OUTPUT_DIR = PROJECT_ROOT / "pipeline_output" / "production"
RUNS_DIR = PRODUCTION_OUTPUT_DIR / "runs"
PARTIALS_DIR = PRODUCTION_OUTPUT_DIR / "partials"
ML_SCRATCH_DIR = PRODUCTION_OUTPUT_DIR / "ml_scratch"
RUN_HISTORY_PATH = PRODUCTION_OUTPUT_DIR / "production_run_history.jsonl"

# Default workflow.
DEFAULT_WORKFLOW = "prod-wf1-async-v1"

# Service URLs (reuse 板块 5 constants — single source of truth).
from pipeline.benchmark.config import (  # noqa: E402  (intentional late import)
    BIGMODEL_CHAT_URL,
    WF1_BERT_THRESHOLD,
    WF1_MAX_LLM_SENTENCES,
)

# Frozen LLM workflow (板块 5). prod-wf1 wires this as the llm_group source.
WF8_WORKFLOW_ID = "wf8-merged-seven-fields-dev20-v2-wash"
WF8_WORKFLOW_VERSION = "0.2.0-dev20-wash"
WF8_METRICS_CAP = 20
WF8_SENTENCE_CLEAN = True
WF8_LLM_MODE_LABEL = "prod-wf1"

# --- wf4 experimental workflow (LLM multi-exp + datasets) -------------------
# Experimental, non-canonical. Inherits wf3 /filter/batch scheduling but moves
# datasets[] from pack rules to LLM direct extraction. Does NOT alter
# WF1_MAX_LLM_SENTENCES (35) or DEFAULT_WORKFLOW — wf4 has its own cap.
WF4_WORKFLOW_ID = "prod-wf4-llm-datasets-experiment"
WF4_WORKFLOW_VERSION = "0.8.0"  # v0.8 milestone 2026-08-21 (tag v0.8): post-v0.7.0 capability line merged -- rolling R1 production default + completion ledger/resume fallback + 4-artifact compaction + backfill tooling/skill; prediction semantics unchanged since 0.7.1 (TXT-01/02)
WF4_LLM_EXTRACTOR_ID = "llm.wf4_dev20_v2_wash_datasets"
WF4_MAX_QWEN_SENTENCES = 60  # wf4 cap / flat-60 default (NOT WF1_MAX_LLM_SENTENCES=35)
WF4_MAX_EXPERIMENTS = 3  # hard cap after normalize (keep first N)
WF4_MAX_METHODS_PER_PAPER = 3  # paper-level method phrase budget (EXT-09)
WF4_DATASETS_CAP = 20  # max datasets PER EXPERIMENT from normalize_llm_datasets
WF4_SENTENCE_CLEAN_HEADING_KEEP_KEYWORDS = ("dataset", "data")  # headings kept by wf4_sentence_clean

# --- dataset-section fallback (shared preprocess capability) -----------------
# When the primary section-union captured no dataset-bearing section, scan
# non-primary sections at paragraph level for dataset signals and append a
# third marker block so BERT/LLM can see dataset mentions that live under
# non-standard section titles (security/method papers). See
# preprocess/section_union_dataset_fallback.py + STRATEGY_SECTION_UNION_DATASET_FALLBACK.md.
# Phased rollout: wf4 ON (validated here), wf8 OFF (shared capability reserved).
WF4_DATASET_SECTION_FALLBACK = True
WF8_DATASET_SECTION_FALLBACK = False

# Main-project md/json (used when --paper resolves against data/md).
DATA_MD_DIR = PROJECT_ROOT / "data" / "md"
DATA_JSON_DIR = PROJECT_ROOT / "data" / "json"

SMOKE_PAPER_ID = "53e9a3fbb7602d9702d13e26"

# 板块 7 eval lazy md cache (optional resolver hook; empty by default → no behavior
# change for normal prod runs). Eval pre-fills this dir from handoff md_url, then
# batch_run_bert_pipeline._resolve_md picks it up as a third search candidate.
# NOTE: dev_10/dev_100 md are now pinned here too (.gitignore ignores this dir),
# so the fixtures themselves stay small (JSON/text only) and tracked.
EVAL_MD_CACHE_DIR = PROJECT_ROOT / "pipeline_output" / "md_cache"

# --- evaluation fixtures (tracked data assets; md lives in EVAL_MD_CACHE_DIR) -
EVALUATION_FIXTURES_DIR = PROJECT_ROOT / "pipeline" / "evaluation" / "fixtures"

# dev_10 smoke fixture — migrated out of the gitignored pack into the tracked
# evaluation fixtures dir. manifest entries no longer carry `md_path` (md is
# resolved by paper_id via _resolve_md below).
DEV10_MANIFEST = EVALUATION_FIXTURES_DIR / "dev_10" / "manifest.json"
# dev_10 md migrated to the shared eval md_cache. DEV10_MD_DIR is kept as an
# alias pointing at md_cache so the existing _resolve_md bodies (orchestrator +
# wf1/wf2/wf3/wf4/run_single) find dev_10/dev_100 md without any code change.
DEV10_MD_DIR = EVAL_MD_CACHE_DIR
