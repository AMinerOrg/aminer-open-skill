"""Configuration for benchmark module (板块 5)."""

from __future__ import annotations

import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]

# Benchmark identifiers
BENCHMARK_ID = "strategy-benchmark-lab"
BENCHMARK_VERSION = "0.1.0"

# Output directories
BENCHMARK_OUTPUT_DIR = PROJECT_ROOT / "pipeline_output" / "benchmark"
RUNS_DIR = BENCHMARK_OUTPUT_DIR / "runs"
COMPARISONS_DIR = BENCHMARK_OUTPUT_DIR / "comparisons"

# Service URLs (aligned with block 3/4).
# The only model service is the public Zhipu BigModel API (OpenAI-compatible),
# model glm-5.3, used by both the GLM sentence filter and the extraction
# stage. Env overrides LLM_CHAT_URL / LLM_MODEL; yaml `llm_model` and CLI
# --llm-model override upstream (see run_bulk / batch_run_wf4 wiring).
BIGMODEL_CHAT_URL = os.environ.get(
    "LLM_CHAT_URL", "https://open.bigmodel.cn/api/paas/v4/chat/completions"
)
# LLM chat model identifier accepted by the serving backend.
LLM_MODEL = os.environ.get("LLM_MODEL", "glm-5.3-flash")

# Default model configuration
LLM_FALLBACK_MODEL_TAG = "glm-5.3-flash"

# Timeout configuration (BERT_TIMEOUT kept only as the legacy shim default).
BERT_TIMEOUT = 120
LLM_TIMEOUT = 180

# Workflow 1 (wf1-merged) configuration
WF1_BERT_THRESHOLD = 0.6
WF1_MAX_LLM_SENTENCES = 35

# Input directories
DATA_MD_DIR = PROJECT_ROOT / "data" / "md"
DATA_JSON_DIR = PROJECT_ROOT / "data" / "json"

# Union section markers for wf1
EXPERIMENT_SECTION_MARKER = "=== EXPERIMENT ==="
ABSINTRO_SECTION_MARKER = "=== ABSINTRO ==="
# Third block: dataset-section fallback (preprocess shared capability; appended
# only when primary union missed dataset-bearing sections). See
# preprocess/section_union_dataset_fallback.py.
DATASET_FALLBACK_SECTION_MARKER = "=== DATASET_FALLBACK ==="