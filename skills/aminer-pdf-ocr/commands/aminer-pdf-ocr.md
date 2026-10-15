---
description: OCR a PDF/image then extract structured experiment information (methods, datasets, metrics, results)
argument-hint: [input: <local-pdf | url> output-dir: <dir> ocr-only: yes|no no-save-images: yes|no output: <json-path> | natural language]
allowed-tools: Read, Write, Bash, Glob
---

# /aminer-pdf-ocr — PDF OCR + Experiment Extraction

User invoked the PDF/Image OCR skill with:

```text
$ARGUMENTS
```

## Language Routing / 语言路由

- If `$ARGUMENTS` or the conversation is mainly Chinese, follow **中文命令流程** and read `${CLAUDE_PLUGIN_ROOT}/SKILL.zh.md`.
- Otherwise follow **English Command Flow** and read `${CLAUDE_PLUGIN_ROOT}/SKILL.md`.
- Parameter names stay English: `input`, `output-dir`, `ocr-only`, `no-save-images`, `output`.
- JSON keys stay English (`engine`, `status`, `artifacts`, `counts`, etc.).
- 如果 `$ARGUMENTS` 或对话主要是中文，使用 **中文命令流程**。
- 否则使用 **English Command Flow**。

## English Command Flow

### 1. Pre-flight

1. Check that `AMINER_API_KEY` exists without printing its value. If missing, stop and send the user to https://open.aminer.cn/open/board?tab=control. `OPEN_PLATFORM_TOKEN` is a deprecated fallback only.
2. Check that `requests` and `pypdf` are installed.
3. Confirm the user supplied a local PDF or an HTTP(S) URL. The open API accepts only unencrypted PDFs with 1-30 pages and size <= 10 MiB.

### 2. Run

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/ocr.py" --input "<input>"
```

Pass `--output-dir`, `--request-timeout`, `--poll-timeout`, `--max-upload-attempts`, `--no-save-images`, or `--output` only when requested. Do not pass the removed local-parser options (custom base URL, backend, page ranges, formula, or table flags).

### 3. Extract Experiments

Unless `ocr-only: yes`, read the complete `<output-dir>/result.md`, read `references/experiment_prompt.md`, write one JSON object to `<output-dir>/experiments.json`, and paste that same complete JSON into the reply. Do not add `justification` fields or invent facts.

## 中文命令流程

### 1. 执行前检查

1. 检查 `AMINER_API_KEY` 是否存在，禁止回显值；缺失则停止，并引导用户前往 https://open.aminer.cn/open/board?tab=control。`OPEN_PLATFORM_TOKEN` 仅作兼容回退。
2. 检查 `requests` 和 `pypdf` 依赖。
3. 确认用户提供本地 PDF 或 HTTP(S) URL。开放接口只接受未加密、1–30 页且不超过 10 MiB 的 PDF。

### 2. 运行

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/scripts/ocr.py" --input "<input>"
```

仅按用户要求传入 `--output-dir`、`--request-timeout`、`--poll-timeout`、`--max-upload-attempts`、`--no-save-images` 或 `--output`。不要传入已移除的本地解析器参数（自定义 base URL、backend、页码、公式、表格）。

### 3. 抽取实验信息

除非 `ocr-only: yes`，读取完整 `result.md` 和 `references/experiment_prompt.md`，将一个 JSON 对象写入 `<output-dir>/experiments.json`，并在回复中原样展示完整 JSON。禁止增加 `justification` 或编造事实。

