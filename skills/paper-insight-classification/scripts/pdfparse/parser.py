"""PDF / 纯文本 → ParsedDocument。

基于 PyMuPDF 的版面信息（字号、粗体、坐标、上标标志）重建：
  标题 → 章节 → 段落（跨栏/跨页合并、断词修复、去页眉页脚/脚注/侧边水印）
  → 参考文献区 → 文中引用句。
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import pymupdf

from .models import Paragraph, ParsedDocument, Section
from .references import extract_citations, split_references, split_references_from_text
from .text_utils import cjk_ratio, detect_lang, ends_paragraph, ends_sentence, join_lines, normalize_text

_SUP_OPEN, _SUP_CLOSE = "\x02", "\x03"
_SUP_RE = re.compile(_SUP_OPEN + r"([^" + _SUP_CLOSE + r"]*)" + _SUP_CLOSE)
_SUP_CITE_RE = re.compile(r"^\s*\[?\d{1,3}(?:\s*[,，\-–—]\s*\d{1,3})*\]?\s*$")

_NUMBERING = re.compile(
    r"^\s*(?:(\d{1,2}(?:\.\d{1,2}){0,3})\.?|([IVX]{1,5})\.|([A-H])\.|([一二三四五六七八九十]{1,3})[、.．]|第[一二三四五六七八九十\d]{1,3}[章节])\s*\S"
)
_SECTION_NO = re.compile(r"^\s*(?:\d{1,2}(?:\.\d{1,2}){0,3}\.?\s+|[一二三四五六七八九十]{1,3}[、.．]\s*|第[一二三四五六七八九十\d]{1,3}[章节]\s*)(?=[^\d\s.])")
_KEYWORDS_EN = re.compile(
    r"^\s*(?:\d{1,2}(?:\.\d{1,2})*\.?\s*|[IVX]{1,5}\.\s*|[A-H]\.\s*)?"
    r"(abstract|introduction|related works?|background|preliminar(?:y|ies)|method(?:s|ology)?|approach|"
    r"proposed method|framework|model|experiments?|experimental (?:setup|results)|evaluation|results?(?: and discussion)?|"
    r"discussions?|analysis|ablation stud(?:y|ies)|case stud(?:y|ies)|conclusions?(?: and future work)?|future work|"
    r"limitations?|acknowledge?ments?|references|bibliography|appendix|appendices|ethics statement|broader impact|"
    r"literature review|data(?:set)?s?|implementation details)\s*$",
    re.I,
)
_KEYWORDS_ZH = re.compile(
    r"^\s*(?:[一二三四五六七八九十\d.．、]+\s*)?(摘\s*要|引\s*言|绪\s*论|前\s*言|相关(?:研究|工作)|文献综述|研究方法|方\s*法|"
    r"实\s*验.{0,6}|结\s*果.{0,6}|讨\s*论|结\s*论.{0,6}|总\s*结.{0,6}|致\s*谢|参\s*考\s*文\s*献|附\s*录)\s*$"
)
_RULER_NUM = re.compile(r"^\d{1,4}$")
# 标题末尾允许跟一个行号（review 模板的行号若没被识别剔除，会并进标题，如 “References 765”）
_REF_HEAD = re.compile(r"^\s*(?:\d{1,2}\.?\s*|[IVX]{1,5}\.\s*)?(references?|bibliography|literature cited|works cited|参\s*考\s*文\s*献|引用文献)\s*[:：]?\s*(?:\d{1,4})?\s*$", re.I)
_FIG_CAPTION = re.compile(r"^\s*(?:fig(?:ure)?\.?|table|tab\.|图|表)\s*\d+\s*[.:：|]", re.I)
_END_REF_HEAD = re.compile(r"^\s*(?:[A-Z]\.?\s*|\d{1,2}\.?\s*)?(appendix|appendices|supplementary|附\s*录|checklist|NeurIPS Paper Checklist)\b", re.I)
_ABSTRACT_HEAD = re.compile(r"^\s*(abstract|摘\s*要)\s*[:：.—-]?\s*$", re.I)
_ABSTRACT_INLINE = re.compile(r"^\s*(abstract|摘\s*要)\s*[:：.—–-]\s*", re.I)
_CAPTION = re.compile(r"^\s*(fig(?:ure)?\.?|table|tab\.|algorithm|图|表|算法)\s*[\dA-Z]+(?:[.:：\-]\d+)?\s*[.:：|]?", re.I)
_PAGE_NUM = re.compile(r"^\s*(?:page\s*)?[-–—]?\s*\d{1,4}\s*[-–—]?\s*(?:of\s*\d+)?\s*$|^\s*第\s*\d+\s*页", re.I)


@dataclass
class _Line:
    text: str
    x0: float
    y0: float
    x1: float
    y1: float
    size: float


@dataclass
class _Block:
    page: int
    x0: float
    y0: float
    x1: float
    y1: float
    lines: list[_Line] = field(default_factory=list)
    size: float = 0.0
    bold_ratio: float = 0.0
    page_h: float = 792.0
    page_w: float = 612.0

    @property
    def text(self) -> str:
        return join_lines([ln.text for ln in self.lines])


def _is_bold(span: dict) -> bool:
    font = span.get("font", "")
    return bool(span.get("flags", 0) & 16) or bool(re.search(r"bold|black|heavy|semibold|medi|-B\b|\.B\b|CMBX", font, re.I))


def _ruler_lines(raw_lines: list[dict], page_w: float, known_sides: set[int]) -> set[tuple]:
    """投稿模板（ACL / EMNLP review 版等）印在左右页边的逐行行号，返回这些行的 bbox。

    判据：落在页边条内的纯数字行，按 y 排序后数值基本逐行递增。某一侧在任一页出现过完整的行号列后，
    其余页同侧只要有 3 行以上就认定（图表页的行号可能很少）。
    """
    sides: dict[int, list[tuple[float, int, tuple]]] = {0: [], 1: []}
    for ln in raw_lines:
        x0, y0, x1, _ = ln["bbox"]
        text = "".join(sp.get("text", "") for sp in ln.get("spans", [])).strip()
        if not _RULER_NUM.match(text):
            continue
        if x1 < page_w * 0.1:
            sides[0].append((y0, int(text), tuple(ln["bbox"])))
        elif x0 > page_w * 0.9:
            sides[1].append((y0, int(text), tuple(ln["bbox"])))
    found: set[tuple] = set()
    for side, items in sides.items():
        if len(items) < (3 if side in known_sides else 8):
            continue
        items.sort()
        steps = [b[1] - a[1] for a, b in zip(items, items[1:])]
        if sum(1 <= s <= 2 for s in steps) >= 0.7 * len(steps):
            found.update(it[2] for it in items)
            known_sides.add(side)
    return found


def _extract_blocks(doc: pymupdf.Document) -> tuple[list[_Block], float]:
    blocks: list[_Block] = []
    size_counter: Counter[float] = Counter()
    ruler_sides: set[int] = set()
    for pno, page in enumerate(doc):
        pw, ph = page.rect.width, page.rect.height
        d = page.get_text("dict", flags=pymupdf.TEXT_MEDIABOX_CLIP)
        text_blocks = [b for b in d.get("blocks", []) if b.get("type") == 0]
        ruler = _ruler_lines([ln for b in text_blocks for ln in b.get("lines", [])], pw, ruler_sides)
        for b in text_blocks:
            blk = _Block(pno + 1, *b["bbox"], page_h=ph, page_w=pw)
            bold_chars = total_chars = 0
            sizes: Counter[float] = Counter()
            for ln in b.get("lines", []):
                if tuple(ln["bbox"]) in ruler:
                    continue
                dx, dy = ln.get("dir", (1, 0))
                if abs(dy) > 0.2 or dx < 0:  # 竖排/旋转文字（arXiv 侧边水印等）
                    continue
                parts: list[str] = []
                spans = ln.get("spans", [])
                base_size = max((s["size"] for s in spans if s.get("text", "").strip()), default=0)
                for sp in spans:
                    t = normalize_text(sp.get("text", ""))
                    if not t:
                        continue
                    is_sup = bool(sp.get("flags", 0) & 1) or (
                        base_size and sp["size"] < base_size * 0.78 and sp["bbox"][3] < ln["bbox"][3] - sp["size"] * 0.25
                    )
                    if is_sup and t.strip():
                        parts.append(_SUP_OPEN + t.strip() + _SUP_CLOSE)
                        continue
                    parts.append(t)
                    n = len(t.strip())
                    total_chars += n
                    if _is_bold(sp):
                        bold_chars += n
                    # 按字形宽度加权（一个汉字约等于两个拉丁字母宽）：否则英文参考文献的字符数会压过中文正文
                    sizes[round(sp["size"] * 2) / 2] += max(sp["bbox"][2] - sp["bbox"][0], 0.0)
                text = "".join(parts).strip()
                if not text:
                    continue
                lsize = sizes.most_common(1)[0][0] if sizes else base_size
                blk.lines.append(_Line(text, *ln["bbox"], size=lsize))
            if not blk.lines or total_chars == 0:
                continue
            if ruler:  # 行号被剔除后，块外框要按剩余行重算，否则块仍被撑到页边
                blk.x0, blk.y0 = min(ln.x0 for ln in blk.lines), min(ln.y0 for ln in blk.lines)
                blk.x1, blk.y1 = max(ln.x1 for ln in blk.lines), max(ln.y1 for ln in blk.lines)
            blk.size = sizes.most_common(1)[0][0]
            blk.bold_ratio = bold_chars / max(total_chars, 1)
            size_counter.update(sizes)
            blocks.append(blk)
    body_size = size_counter.most_common(1)[0][0] if size_counter else 10.0
    return blocks, body_size


def _plain(text: str) -> str:
    return _SUP_RE.sub("", text)


def _reference_lines(blocks: list[_Block]) -> list[tuple[int, float, float, float, float, str]]:
    """参考文献区的行。浮动体（图/表）常夹在参考文献页里，其文字必须剔除：
    字号明显小于文献正文、整块加粗的标签、Figure/Table 题注。"""
    if not blocks:
        return []
    weight: Counter[float] = Counter()
    for b in blocks:
        weight[b.size] += sum(ln.x1 - ln.x0 for ln in b.lines)
    ref_size = weight.most_common(1)[0][0]
    lines = []
    for b in blocks:
        if b.size < ref_size - 0.6 or b.bold_ratio >= 0.6 or _FIG_CAPTION.match(_plain(b.text)):
            continue
        lines.extend((b.page, ln.x0, ln.y0, ln.x1, ln.y1, _plain(ln.text)) for ln in _merge_fragments(b.lines))
    return lines


def _merge_fragments(lines: list[_Line]) -> list[_Line]:
    """PyMuPDF 会把同一视觉行里换了字体（如斜体刊名）的部分拆成多个“行”；分栏按行首 x 判断时，
    靠右的片段会被误分到右栏。这里只在同一个块内把同一视觉行的片段并回去（两端对齐的行，片段间距可达十几 pt）。"""
    out: list[_Line] = []
    for ln in lines:
        if out:
            p = out[-1]
            overlap = min(p.y1, ln.y1) - max(p.y0, ln.y0)
            if overlap > 0.5 * min(p.y1 - p.y0, ln.y1 - ln.y0) and 0 <= ln.x0 - p.x1 <= p.size * 2.5:
                sep = "" if cjk_ratio(p.text[-1:]) > 0.5 else " "
                out[-1] = _Line(p.text + sep + ln.text, p.x0, min(p.y0, ln.y0), ln.x1, max(p.y1, ln.y1), p.size)
                continue
        out.append(ln)
    return out


def _repeated_margin_texts(blocks: list[_Block], n_pages: int) -> set[str]:
    counter: Counter[str] = Counter()
    for b in blocks:
        if b.y1 < b.page_h * 0.09 or b.y0 > b.page_h * 0.91:
            key = re.sub(r"\d+", "#", _plain(b.text).lower()).strip()
            if key:
                counter[key] += 1
    threshold = max(2, int(n_pages * 0.3))
    return {k for k, v in counter.items() if v >= threshold}


def _column_edges(blocks: list[_Block], body_size: float) -> dict[tuple[int, int], tuple[float, float]]:
    """每页每栏正文行的左/右边界（10%/90% 分位），用于判断续行与首行缩进。"""
    acc: dict[tuple[int, int], tuple[list[float], list[float]]] = defaultdict(lambda: ([], []))
    for b in blocks:
        if abs(b.size - body_size) > 0.6:
            continue
        for ln in b.lines:
            xs0, xs1 = acc[(b.page, _col(b, ln.x0))]
            xs0.append(ln.x0)
            xs1.append(ln.x1)
    out = {}
    for k, (xs0, xs1) in acc.items():
        xs0.sort()
        xs1.sort()
        out[k] = (xs0[int(len(xs0) * 0.1)], xs1[min(len(xs1) - 1, int(len(xs1) * 0.9))])
    return out


def _col(b: _Block, x0: float) -> int:
    return 0 if x0 < b.page_w * 0.45 else 1


def _heading_level(text: str) -> int:
    m = _NUMBERING.match(text)
    if m and m.group(1):
        return m.group(1).count(".") + 1
    return 1


def _is_heading(b: _Block, body_size: float) -> bool:
    text = _plain(b.text).strip()
    if not text or len(text) > 120 or len(b.lines) > 3 or _CAPTION.match(text):
        return False
    if text.endswith((",", ";", "，", "；")):
        return False
    compact = text.replace(" ", "")
    if sum(c.isalpha() for c in compact) < len(compact) * 0.5:  # 表格数字行
        return False
    if _REF_HEAD.match(text) or _ABSTRACT_HEAD.match(text):
        return True
    styled = b.bold_ratio >= 0.6 or b.size >= body_size + 0.9
    kw = bool(_KEYWORDS_EN.match(text) or _KEYWORDS_ZH.match(text))
    if kw and len(text) <= 60:
        return True
    if not styled:
        # 无粗体/放大的编号标题（中文回退字体常没有粗体字形）：单行、短、带章节编号、内部无标点
        return bool(
            _SECTION_NO.match(text) and len(text) <= 40 and len(b.lines) == 1 and b.size >= body_size - 0.2
            and not re.search(r"[，,。；;：:！？!?、]", text[4:]) and not ends_sentence(text)
        )
    words = len(text.split()) if not re.search(r"[一-鿿]", text) else len(text) // 2
    if _NUMBERING.match(text) and words <= 14 and not ends_sentence(text.rstrip(".")):
        return True
    return words <= 10 and not ends_sentence(text) and b.size >= body_size + 0.9


def _split_block_paragraphs(b: _Block, body_size: float) -> list[str]:
    """块内按首行缩进/短行切分段落。"""
    if len(b.lines) <= 1:
        return [b.text]
    left = min(ln.x0 for ln in b.lines)
    right = max(ln.x1 for ln in b.lines)
    indent = body_size * 0.8
    paras: list[list[str]] = [[]]
    for i, ln in enumerate(b.lines):
        if i > 0 and paras[-1]:
            prev = b.lines[i - 1]
            prev_text = _plain(prev.text)
            indented = ln.x0 > left + indent and ln.x0 < left + body_size * 4
            short_prev = prev.x1 < right - body_size * 2.5
            if ends_paragraph(prev_text) and (indented or short_prev):
                paras.append([])
        paras[-1].append(ln.text)
    return [join_lines(p) for p in paras if p]


def _resolve_superscripts(paragraphs: list[Paragraph]) -> str:
    """判断上标数字是否为引用：方括号引用很少而上标数字很多时，视为上标引用制。"""
    body = "\n".join(p.text for p in paragraphs)
    n_bracket = len(re.findall(r"\[\d{1,3}(?:\s*[,\-–]\s*\d{1,3})*\]", _plain(body)))
    sup_tokens = _SUP_RE.findall(body)
    n_sup_cite = sum(1 for t in sup_tokens if _SUP_CITE_RE.match(t))
    as_cite = n_bracket < 5 and n_sup_cite >= 6

    def repl(m: re.Match) -> str:
        t = m.group(1).strip()
        if as_cite and _SUP_CITE_RE.match(t):
            inner = t.strip("[]").replace("，", ",")
            return f"[{inner}]"
        if _SUP_CITE_RE.match(t) and t.startswith("["):  # 上标形式的方括号引用（中文期刊常见）
            return t
        return ""

    for p in paragraphs:
        p.text = re.sub(r"\s{2,}", " ", _SUP_RE.sub(repl, p.text)).strip()
    return "superscript" if as_cite else ""


def parse_pdf(path: str | Path) -> ParsedDocument:
    doc = pymupdf.open(str(path))
    try:
        return _parse(doc)
    finally:
        doc.close()


def _parse(doc: pymupdf.Document) -> ParsedDocument:
    out = ParsedDocument(pages=len(doc), source="pdf")
    blocks, body_size = _extract_blocks(doc)
    if not blocks:
        out.warnings.append("PDF 中没有可提取的文字（可能是扫描件，需要 OCR）")
        return out
    margin_texts = _repeated_margin_texts(blocks, len(doc))

    # ---- 标题 ----
    meta_title = (doc.metadata or {}).get("title", "") or ""
    if 8 < len(meta_title) < 300 and not re.search(r"^microsoft word|\.(docx?|pdf|dvi|tex)$|^untitled", meta_title, re.I):
        out.title = normalize_text(meta_title).strip()
    def _sectionish(b: _Block) -> bool:
        t = _plain(b.text).strip()
        return bool(_REF_HEAD.match(t) or _ABSTRACT_HEAD.match(t) or _KEYWORDS_EN.match(t) or _KEYWORDS_ZH.match(t)
                    or _SECTION_NO.match(t))

    first_page = [b for b in blocks if b.page == 1 and b.y0 < b.page_h * 0.45 and not _sectionish(b)]
    title_block = max(first_page, key=lambda b: (b.size, -b.y0), default=None)
    if title_block is not None and title_block.size <= body_size + 1:
        title_block = None  # 没有明显大于正文的字号：不存在标题块（不能把正文当标题跳过）
    if not out.title and title_block is not None:
        out.title = _plain(title_block.text)[:300]

    section = "Front"
    in_refs = False
    ref_blocks: list[_Block] = []
    paragraphs: list[Paragraph] = []
    open_para: Paragraph | None = None  # 可与下一块合并的段落
    open_geom: tuple[int, int, float, float] | None = None  # (页, 栏, 末行 x1, 块底 y1)
    seen_heading = False
    pid = 0
    edges = _column_edges(blocks, body_size)

    def is_continuation(b: _Block, text: str) -> bool:
        """新块的首行是否接续上一段：几何续行（同栏紧邻、上一行写满、本行顶格）或跨栏/跨页的文本续接。"""
        prev = _plain(open_para.text) if open_para else ""
        first_ln = b.lines[0]
        col = _col(b, first_ln.x0)
        left, right = edges.get((b.page, col), (first_ln.x0, b.x1))
        flush = first_ln.x0 <= left + max(2.5, body_size * 0.3)
        if not flush:
            return False  # 首行缩进 = 新段落
        if open_geom is not None:
            pg, pcol, last_x1, y1 = open_geom
            p_right = edges.get((pg, pcol), (0, last_x1))[1]
            if pg == b.page and pcol == col and 0 <= b.y0 - y1 <= body_size * 1.0:
                return last_x1 >= p_right - body_size * 1.2  # 上一行写满才是续行
        first = _plain(text)[:1]
        if ends_paragraph(prev):
            return False
        zh = cjk_ratio(prev[-40:]) > 0.3
        return first.islower() or first in ",;)]，；）、" or bool(re.match(r"[一-鿿]", first or "")) or (zh and first.isalnum())

    def add_para(text: str, page: int, kind: str, b: _Block | None = None, first_piece: bool = False) -> None:
        nonlocal pid, open_para
        text = text.strip()
        if not text:
            return
        if open_para is not None and kind == open_para.kind and open_para.section == section and first_piece                 and b is not None and is_continuation(b, text):
            prev = _plain(open_para.text)
            first = _plain(text)[:1]
            if prev.endswith("-") and len(prev) > 1 and prev[-2].isalpha() and first.islower():
                open_para.text = open_para.text[:-1] + text
            else:
                open_para.text = join_lines([open_para.text, text])
            return
        pid += 1
        open_para = Paragraph(pid, page, section, text, kind)
        paragraphs.append(open_para)

    for b in blocks:
        text = b.text
        plain = _plain(text).strip()
        if not plain:
            continue
        margin = b.y1 < b.page_h * 0.09 or b.y0 > b.page_h * 0.91
        if margin and (re.sub(r"\d+", "#", plain.lower()) in margin_texts or _PAGE_NUM.match(plain)):
            continue
        if _PAGE_NUM.match(plain) and len(plain) < 12:
            continue

        if title_block is not None and b is title_block:
            continue
        # 第一页标题区（作者、单位、邮箱）：位于标题下方、首个章节标题之前
        if not seen_heading and b.page == 1 and title_block is not None \
                and b.y0 < title_block.y1 + b.page_h * 0.2 and len(plain) < 400 \
                and not (_ABSTRACT_HEAD.match(plain) or _ABSTRACT_INLINE.match(plain)
                         or _KEYWORDS_EN.match(plain) or _KEYWORDS_ZH.match(plain)):
            continue

        is_head = _is_heading(b, body_size)
        if in_refs:
            # 参考文献区在附录/补充材料标题处结束；整块加粗且不含年份的短行也视为新章节
            ends_refs = is_head and (
                _END_REF_HEAD.match(plain)
                or (b.bold_ratio >= 0.6 and not re.search(r"(19|20)\d{2}|^\s*\[\d+\]", plain))
            )
            if not ends_refs:
                ref_blocks.append(b)
                continue
            in_refs = False

        if is_head:
            if _REF_HEAD.match(plain):
                in_refs = True
                section = "References"
                open_para = None
                continue
            section = re.sub(r"\s+", " ", plain)
            seen_heading = True
            out.sections.append(Section(section, _heading_level(plain), b.page))
            open_para = None
            continue

        if _CAPTION.match(plain) or (plain.startswith("(a)") and re.search(r"\b(Figure|Fig\.|Table)\s*\d+[.:]", plain)):
            add_para(text, b.page, "caption")
            open_para = None
            continue
        # 脚注 / 表格 / 图中文字：字号明显小于正文
        if b.size < body_size - 1.2:
            continue
        if b.size < body_size - 0.6 and b.y0 > b.page_h * 0.7:
            continue
        letters = sum(c.isalpha() for c in plain)
        if (letters < len(plain) * 0.45 or len(plain) < 3) and not (open_para is not None and is_continuation(b, text)):
            continue  # 公式、表格数字（但“段[10]。”这类续行要保留）

        kind = "abstract" if section.lower().startswith("abstract") or re.match(r"摘\s*要", section) else "body"
        for k, piece in enumerate(_split_block_paragraphs(b, body_size)):
            m = _ABSTRACT_INLINE.match(_plain(piece))
            if m and not seen_heading:
                section = "Abstract"
                seen_heading = True
                out.sections.append(Section(section, 1, b.page))
                piece = _plain(piece)[m.end():]
                add_para(piece, b.page, "abstract")
                continue
            add_para(piece, b.page, kind, b, first_piece=(k == 0))
        last = b.lines[-1]
        open_geom = (b.page, _col(b, last.x0), last.x1, b.y1)

    ref_lines = _reference_lines(ref_blocks)
    style_hint = _resolve_superscripts(paragraphs)
    # 过滤过短段落（标题残片、孤立公式）
    min_len = 12
    kept = [p for p in paragraphs if len(p.text) >= min_len]
    for i, p in enumerate(kept, 1):
        p.id = i
    out.paragraphs = kept

    body_text = " ".join(p.text for p in kept)
    out.lang = detect_lang(body_text or " ".join(t for *_, t in ref_lines))
    out.references_text = "\n".join(t for *_, t in ref_lines)
    out.references = split_references(ref_lines)
    out.citations, style = extract_citations(out.paragraphs, out.references, out.lang)
    out.citation_style = style_hint or style
    if not out.references:
        out.warnings.append("未能定位参考文献区")
    if not out.title and kept:
        out.title = kept[0].text[:80]
    return out


def parse_text(text: str, title: str = "") -> ParsedDocument:
    """粘贴文本 → ParsedDocument（空行分段；若含“参考文献/References”标题则切分文献）。"""
    text = text.replace("\r\n", "\n").strip()
    out = ParsedDocument(pages=1, source="text", title=title)
    lines = text.split("\n")
    ref_start = next((i for i, ln in enumerate(lines) if _REF_HEAD.match(ln.strip())), None)
    body_lines = lines if ref_start is None else lines[:ref_start]
    ref_text = "" if ref_start is None else "\n".join(lines[ref_start + 1:])

    body = "\n".join(body_lines)
    chunks = re.split(r"\n\s*\n", body) if re.search(r"\n\s*\n", body) else body.split("\n")
    section = "正文"
    pid = 0
    for ch in chunks:
        ch = ch.strip()
        if not ch:
            continue
        one_line = " ".join(ch.split("\n")) if not re.search(r"[一-鿿]", ch) else "".join(x.strip() for x in ch.split("\n"))
        if len(one_line) < 60 and (_KEYWORDS_EN.match(one_line) or _KEYWORDS_ZH.match(one_line) or _NUMBERING.match(one_line)) \
                and not ends_sentence(one_line):
            section = one_line
            out.sections.append(Section(section, _heading_level(one_line), 1))
            continue
        pid += 1
        out.paragraphs.append(Paragraph(pid, 1, section, normalize_text(one_line), "body"))
    out.lang = detect_lang(" ".join(p.text for p in out.paragraphs))
    if not out.title and out.paragraphs:
        first = out.paragraphs[0].text
        out.title = first[:40] + ("…" if len(first) > 40 else "")
    out.references_text = ref_text
    out.references = split_references_from_text(ref_text) if ref_text else []
    out.citations, out.citation_style = extract_citations(out.paragraphs, out.references, out.lang)
    return out
