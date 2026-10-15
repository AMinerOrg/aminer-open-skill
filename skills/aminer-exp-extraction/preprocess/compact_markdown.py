"""Compact Markdown for LLM input: figures, display math, OCR inline math, HTML tables."""

from __future__ import annotations

import re
from dataclasses import dataclass

FIGURE_BLOCK_PATTERN = re.compile(
    r"!\[[^\]]*\]\(images/[^)]+\)\s*"
    r"(?:\n\s*((?:Fig\.|Figure)\s*(\d+)\s*:\s*(.*?))(?=\n|$))?",
    re.IGNORECASE,
)
STANDALONE_FIG_CAPTION_PATTERN = re.compile(
    r"\{fig\.\}\s*\n\s*((?:Fig\.|Figure)\s*(\d+)\s*:\s*(.*?)(?=\n|$))",
    re.IGNORECASE,
)
METRIC_IN_CAPTION_PATTERN = re.compile(
    r"\d+\.?\d*\s*%|mIoU|AUROC|F1|FPR\d*|accuracy|Accuracy|precision|recall",
    re.IGNORECASE,
)
FIGURE_CAPTION_LINE_PATTERN = re.compile(r"^(?:Fig\.|Figure)\s*(\d+)\s*:", re.IGNORECASE)
FIG_PLACEHOLDER_KEY_PATTERN = re.compile(r"^\{fig\.\s*(\d+)")
TABLE_PLACEHOLDER_KEY_PATTERN = re.compile(r"^\{table\s+(\d+)")
TABLE_PLACEHOLDER_ON_LINE_PATTERN = re.compile(r"\{table\s+(\d+)", re.IGNORECASE)
FIG_PLACEHOLDER_ON_LINE_PATTERN = re.compile(r"\{fig\.\s*(\d+)", re.IGNORECASE)
DISPLAY_MATH_PATTERN = re.compile(r"\$\$(.*?)\$\$", re.DOTALL)
INLINE_MATH_PATTERN = re.compile(r"(?<!\$)\$(?!\$)(.+?)(?<!\$)\$(?!\$)", re.DOTALL)
TABLE_PATTERN = re.compile(r"<table\b[^>]*>.*?</table>", re.DOTALL | re.IGNORECASE)
TRUNCATED_TABLE_PATTERN = re.compile(
    r"<table\b[^>]*>.*?(?=\n## |\nTABLE |\nTable |\nFig\. |\nFigure |\Z)",
    re.DOTALL | re.IGNORECASE,
)
ORPHAN_TR_PATTERN = re.compile(r"^\s*<tr\b[^>]*>.*?</tr>\s*$", re.MULTILINE | re.DOTALL | re.IGNORECASE)
CAPTION_LINE_PATTERN = re.compile(
    r"^(?:TABLE|Table|Tab\.)\s*(\d+)\s*:?\s*(.*)$",
    re.IGNORECASE,
)
FIRST_TR_PATTERN = re.compile(r"<tr\b[^>]*>(.*?)</tr>", re.DOTALL | re.IGNORECASE)
TAG_PATTERN = re.compile(r"<[^>]+>")

OCR_SPACED_PATTERN = re.compile(
    r"\d\s+\d|\d\s+\.|\.\s+\d|\\\%\s|\s\\%|\\\times\s+|\s+\\\times\s+|\s+x\s+\d|\d\s+x\s+",
)
DIMENSION_PATTERN = re.compile(r"\\(?:mathrm|mathbf)\{[^}]+\}")
SKIP_SYMBOLIC_PATTERN = re.compile(r"\\mathbb|\\sum|\\log|\\mathcal")
SUBSCRIPT_PATTERN = re.compile(r"[a-zA-Z]\s*_\s*\{|_\{")
SYMBOLIC_OCR_SPACE_PATTERN = re.compile(r"_\s+\{|\^\s+\{|\{\s+|\s+\}")
LATEX_EXPLICIT_SPACE_PLACEHOLDER = "\x00LATEXSPACE\x00"
LATEX_ENV_PATTERN = re.compile(r"\\begin\{|\\end\{")


@dataclass(frozen=True)
class CompactMarkdownResult:
    text: str
    original_char_count: int
    compressed_char_count: int
    tables_replaced: int
    display_equations_replaced: int
    inline_math_normalized: int
    figures_replaced: int
    figure_captions_compacted: int = 0
    placeholders_deduped: int = 0
    redundant_captions_stripped: int = 0
    symbolic_latex_compacted: int = 0
    symbolic_latex_skipped: int = 0


def _build_figure_placeholder(fig_num: str, caption: str) -> str:
    caption = caption.strip()
    if caption and METRIC_IN_CAPTION_PATTERN.search(caption):
        return f"{{fig. {fig_num}: {caption[:120]}}}"
    return f"{{fig. {fig_num}}}"


def _replace_figures(text: str) -> tuple[str, int]:
    count = 0

    def replacer(match: re.Match[str]) -> str:
        nonlocal count
        count += 1
        fig_num = match.group(2)
        if fig_num:
            caption = (match.group(3) or "").strip()
            return _build_figure_placeholder(fig_num, caption) + "\n"
        return "{fig.}\n"

    if not FIGURE_BLOCK_PATTERN.search(text):
        return text, 0
    return FIGURE_BLOCK_PATTERN.sub(replacer, text), count


def _compact_standalone_figure_captions(text: str) -> tuple[str, int]:
    count = 0

    def replacer(match: re.Match[str]) -> str:
        nonlocal count
        count += 1
        fig_num = match.group(2)
        caption = (match.group(3) or "").strip()
        return _build_figure_placeholder(fig_num, caption)

    return STANDALONE_FIG_CAPTION_PATTERN.sub(replacer, text), count


def _neighbor_has_table_placeholder(lines: list[str], index: int, table_num: str) -> bool:
    for offset in range(-2, 3):
        if offset == 0:
            continue
        neighbor_index = index + offset
        if 0 <= neighbor_index < len(lines):
            neighbor = lines[neighbor_index].strip()
            if not neighbor:
                continue
            match = TABLE_PLACEHOLDER_ON_LINE_PATTERN.search(neighbor)
            if match and match.group(1) == table_num:
                return True
    return False


def _neighbor_has_fig_placeholder(lines: list[str], index: int, fig_num: str) -> bool:
    for offset in range(-2, 3):
        if offset == 0:
            continue
        neighbor_index = index + offset
        if 0 <= neighbor_index < len(lines):
            neighbor = lines[neighbor_index].strip()
            if not neighbor:
                continue
            match = FIG_PLACEHOLDER_ON_LINE_PATTERN.search(neighbor)
            if match and match.group(1) == fig_num:
                return True
    return False


def _strip_redundant_captions(text: str) -> tuple[str, int]:
    lines = text.splitlines()
    kept: list[str] = []
    stripped_count = 0
    for index, line in enumerate(lines):
        stripped = line.strip()
        table_match = CAPTION_LINE_PATTERN.match(stripped)
        if table_match and _neighbor_has_table_placeholder(lines, index, table_match.group(1)):
            stripped_count += 1
            continue
        fig_match = FIGURE_CAPTION_LINE_PATTERN.match(stripped)
        if fig_match and _neighbor_has_fig_placeholder(lines, index, fig_match.group(1)):
            stripped_count += 1
            continue
        kept.append(line)
    return "\n".join(kept), stripped_count


def _dedupe_placeholders_globally(text: str) -> tuple[str, int]:
    lines = text.splitlines()
    deduped: list[str] = []
    seen_fig: set[str] = set()
    seen_table: set[str] = set()
    deduped_count = 0
    for line in lines:
        stripped = line.strip()
        fig_match = FIG_PLACEHOLDER_KEY_PATTERN.match(stripped)
        if fig_match:
            key = fig_match.group(1)
            if key in seen_fig:
                deduped_count += 1
                continue
            seen_fig.add(key)
        table_match = TABLE_PLACEHOLDER_KEY_PATTERN.match(stripped)
        if table_match:
            key = table_match.group(1)
            if key in seen_table:
                deduped_count += 1
                continue
            seen_table.add(key)
        deduped.append(line)
    return "\n".join(deduped), deduped_count


def _replace_display_math(text: str) -> tuple[str, int]:
    counter = 0

    def replacer(_match: re.Match[str]) -> str:
        nonlocal counter
        counter += 1
        return f"{{eq.{counter}}}"

    return DISPLAY_MATH_PATTERN.sub(replacer, text), counter


def _should_normalize_inline(content: str) -> bool:
    if "^" in content or "_" in content:
        return False
    has_ocr = bool(OCR_SPACED_PATTERN.search(content))
    has_dimension = bool(DIMENSION_PATTERN.search(content))
    if not has_ocr and not has_dimension:
        return False
    if SKIP_SYMBOLIC_PATTERN.search(content) and not has_ocr:
        return False
    if SUBSCRIPT_PATTERN.search(content) and not has_ocr:
        return False
    return True


def _normalize_inline_content(content: str) -> str:
    normalized = content
    normalized = normalized.replace(r"\%", "%")
    normalized = normalized.replace(r"\times", "×")
    normalized = re.sub(r"\\(?:mathrm|mathbf)\{([^}]+)\}", r"\1", normalized)
    normalized = re.sub(r"\\([a-zA-Z]+)", r"\1", normalized)
    normalized = normalized.replace("{", "").replace("}", "")
    normalized = re.sub(r"\s*\.\s*", ".", normalized)
    while re.search(r"\d\s+\d", normalized):
        normalized = re.sub(r"(\d)\s+(?=\d)", r"\1", normalized)
    normalized = re.sub(r"(\d)\s+%", r"\1%", normalized)
    normalized = re.sub(r"\s*×\s*", "×", normalized)
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized


def _normalize_inline_ocr_math(text: str) -> tuple[str, int]:
    count = 0

    def replacer(match: re.Match[str]) -> str:
        nonlocal count
        content = match.group(1)
        if not _should_normalize_inline(content):
            return match.group(0)
        count += 1
        return _normalize_inline_content(content)

    return INLINE_MATH_PATTERN.sub(replacer, text), count


def _is_brace_balanced(content: str) -> bool:
    depth = 0
    index = 0
    length = len(content)
    while index < length:
        char = content[index]
        if char == "\\" and index + 1 < length:
            index += 2
            continue
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth < 0:
                return False
        index += 1
    return depth == 0


def _has_interior_dollar(content: str) -> bool:
    index = 0
    length = len(content)
    while index < length:
        char = content[index]
        if char == "\\" and index + 1 < length:
            index += 2
            continue
        if char == "$":
            return True
        index += 1
    return False


def _is_symbolic_latex_candidate(content: str) -> bool:
    if _should_normalize_inline(content):
        return False
    if "\\" in content:
        return True
    return bool(SYMBOLIC_OCR_SPACE_PATTERN.search(content))


def _should_compact_symbolic_latex(content: str) -> bool:
    if not _is_symbolic_latex_candidate(content):
        return False
    if _has_interior_dollar(content):
        return False
    if not _is_brace_balanced(content):
        return False
    if LATEX_ENV_PATTERN.search(content):
        return False
    return True


def _collapse_brace_interior_spaces(content: str) -> str:
    result = content
    previous = None
    while previous != result:
        previous = result
        result = re.sub(
            r"\{([^{}]*)\}",
            lambda match: "{" + re.sub(r"\s+", "", match.group(1)) + "}",
            result,
        )
    return result


def _unwrap_redundant_group_before_script(content: str) -> str:
    result = content
    previous = None
    pattern = re.compile(
        r"\{\s*(\\[a-zA-Z]+\*?(?:\{[^{}]*\})*)\s*\}\s*(?=[_^])",
    )
    while previous != result:
        previous = result
        result = pattern.sub(r"\1", result, count=1)
    return result


def _compact_latex_whitespace_passes(content: str) -> str:
    result = content.strip()
    result = re.sub(r"(\\[a-zA-Z]+\*?)\s+\{", r"\1{", result)
    result = re.sub(r"_\s+\{", "_{", result)
    result = re.sub(r"\^\s+\{", "^{", result)
    result = re.sub(r"\}\s+_\s+\{", "}_{", result)
    result = re.sub(r"\}\s+\^\s+\{", "}^{", result)
    result = _collapse_brace_interior_spaces(result)
    result = re.sub(r"\{\s+", "{", result)
    result = re.sub(r"\s+\}", "}", result)
    result = re.sub(r"\}\s+(?=[\\a-zA-Z0-9])", "}", result)
    result = re.sub(r"\s+_", "_", result)
    result = re.sub(r"\s+\^", "^", result)
    result = _unwrap_redundant_group_before_script(result)
    return result.strip()


def _compact_latex_whitespace(content: str) -> str:
    protected = content.replace(r"\ ", LATEX_EXPLICIT_SPACE_PLACEHOLDER)
    try:
        result = _compact_latex_whitespace_passes(protected)
        if not _is_brace_balanced(result):
            return content
        return result.replace(LATEX_EXPLICIT_SPACE_PLACEHOLDER, r"\ ")
    except re.error:
        return content


def _compact_symbolic_latex_whitespace(text: str) -> tuple[str, int, int]:
    compacted_count = 0
    skipped_count = 0

    def replacer(match: re.Match[str]) -> str:
        nonlocal compacted_count, skipped_count
        content = match.group(1)
        if not _is_symbolic_latex_candidate(content):
            return match.group(0)
        if not _should_compact_symbolic_latex(content):
            skipped_count += 1
            return match.group(0)
        compacted = _compact_latex_whitespace(content)
        if compacted == content:
            return match.group(0)
        compacted_count += 1
        return f"${compacted}$"

    return INLINE_MATH_PATTERN.sub(replacer, text), compacted_count, skipped_count


def _extract_table_summary(table_html: str) -> str:
    first_tr = FIRST_TR_PATTERN.search(table_html)
    if not first_tr:
        return ""
    visible = TAG_PATTERN.sub(" ", first_tr.group(1))
    visible = re.sub(r"\s+", " ", visible).strip()
    if not visible:
        return ""
    return visible[:80]


def _find_table_caption(text: str, start: int) -> tuple[int | None, str]:
    prefix = text[:start]
    lines = prefix.splitlines()
    for line in reversed(lines[-3:]):
        stripped = line.strip()
        if not stripped:
            continue
        match = CAPTION_LINE_PATTERN.match(stripped)
        if match:
            return int(match.group(1)), match.group(2).strip()
    return None, ""


def _table_placeholder(text: str, start: int, end: int, table_html: str) -> str:
    table_num, caption_text = _find_table_caption(text, start)
    summary = _extract_table_summary(table_html)
    if table_num is not None:
        caption_part = caption_text[:120] if caption_text else ""
        placeholder = f"{{table {table_num}: {caption_part}}}" if caption_part else f"{{table {table_num}}}"
    else:
        placeholder = "{table}"
    if summary:
        placeholder = f"{placeholder} | {summary}"
    return placeholder


def _replace_tables(text: str) -> tuple[str, int]:
    count = 0
    replacements: list[tuple[int, int, str]] = []

    for match in TABLE_PATTERN.finditer(text):
        count += 1
        placeholder = _table_placeholder(text, match.start(), match.end(), match.group(0))
        replacements.append((match.start(), match.end(), placeholder))

    if replacements:
        parts: list[str] = []
        last = 0
        for start, end, placeholder in replacements:
            parts.append(text[last:start])
            parts.append(placeholder)
            last = end
        parts.append(text[last:])
        text = "".join(parts)

    while "<table" in text.lower():
        match = TRUNCATED_TABLE_PATTERN.search(text)
        if not match:
            break
        count += 1
        placeholder = _table_placeholder(text, match.start(), match.end(), match.group(0))
        text = text[: match.start()] + placeholder + text[match.end() :]

    text = ORPHAN_TR_PATTERN.sub("", text)
    return text, count


def compact_markdown(md_text: str) -> CompactMarkdownResult:
    """Apply figure, display-math, inline-OCR, and table compaction in fixed order."""
    original_char_count = len(md_text)
    text = md_text
    figures_replaced = 0
    figure_captions_compacted = 0
    display_equations_replaced = 0
    inline_math_normalized = 0
    tables_replaced = 0

    placeholders_deduped = 0
    redundant_captions_stripped = 0
    symbolic_latex_compacted = 0
    symbolic_latex_skipped = 0

    text, figures_replaced = _replace_figures(text)
    text, figure_captions_compacted = _compact_standalone_figure_captions(text)
    text, display_equations_replaced = _replace_display_math(text)
    text, inline_math_normalized = _normalize_inline_ocr_math(text)
    text, symbolic_latex_compacted, symbolic_latex_skipped = _compact_symbolic_latex_whitespace(text)
    text, tables_replaced = _replace_tables(text)
    text, redundant_captions_stripped = _strip_redundant_captions(text)
    text, placeholders_deduped = _dedupe_placeholders_globally(text)

    return CompactMarkdownResult(
        text=text,
        original_char_count=original_char_count,
        compressed_char_count=len(text),
        tables_replaced=tables_replaced,
        display_equations_replaced=display_equations_replaced,
        inline_math_normalized=inline_math_normalized,
        figures_replaced=figures_replaced,
        figure_captions_compacted=figure_captions_compacted,
        placeholders_deduped=placeholders_deduped,
        redundant_captions_stripped=redundant_captions_stripped,
        symbolic_latex_compacted=symbolic_latex_compacted,
        symbolic_latex_skipped=symbolic_latex_skipped,
    )
