"""参考文献区切分 + 文中引用定位。

切分策略（依次尝试）：
  1. 方括号标签 [n]
  2. 连续编号 1. 2. 3.（严格递增，避免把年份/页码误判为编号）
  3. 版式：悬挂缩进 / 首行缩进 / 行间距
引用定位支持：数字制 [1,3-5]、作者-年份制 (Smith et al., 2020)、叙述式 Smith et al. (2020)、中文（张三等，2020）。
"""

from __future__ import annotations

import re
from statistics import median

from .models import Citation, Paragraph, Reference
from .text_utils import ascii_fold, join_lines, split_sentences

RefLine = tuple[int, float, float, float, float, str]  # page, x0, y0, x1, y1, text

_BRACKET_START = re.compile(r"^\s*[\[［](\d{1,3})[\]］]\s*")
_NUM_START = re.compile(r"^\s*(\d{1,3})(?:[.．、)]\s*|\s+)(?=[A-Za-z一-鿿\"“'À-ɏ])")
_PURE_NUM = re.compile(r"^\s*\d{1,3}(?:\s*,\s*\d{1,3})*\s*$")
_BACKREF_TAIL = re.compile(r"(?<=[.\])])\s+\d{1,3}(?:\s*,\s*\d{1,3})*\s*$")
_AUTHOR_START = re.compile(r"^\s*(?:[A-ZÀ-Þ][A-Za-zÀ-ɏ'’\-]+,\s*[A-ZÀ-Þ]|[A-ZÀ-Þ][a-zà-ÿ]+(?:\s+[A-ZÀ-Þ]\.?)+[,.]|[A-ZÀ-Þ]\.\s|[一-鿿]{2,4}[,，、\s])")

DOI_RE = re.compile(r"\b(10\.\d{4,9}/[^\s\"<>{}]+)", re.I)
ARXIV_RE = re.compile(r"(?:arxiv(?:\s*preprint)?\s*(?:arxiv)?\s*[:/]?\s*|arxiv\.org/(?:abs|pdf)/)(\d{4}\.\d{4,5})(?:v\d+)?", re.I)
URL_RE = re.compile(r"https?://[^\s<>\"]+", re.I)
YEAR_RE = re.compile(r"(?<![\d.])(19[5-9]\d|20[0-4]\d)[a-z]?(?![\d])")


def _clean_entry(text: str) -> str:
    text = _BRACKET_START.sub("", text, count=1)
    text = _BACKREF_TAIL.sub("", text).strip()
    return re.sub(r"\s{2,}", " ", text)


def quick_fields(ref: Reference) -> Reference:
    """规则抽取 DOI / arXiv / URL / 年份（LLM 结构化前的兜底）。"""
    raw = ref.raw
    if not ref.doi:
        m = DOI_RE.search(raw.replace(" ", "") if "doi" in raw.lower() else raw)
        if m:
            ref.doi = m.group(1).rstrip(".,;)]}")
    if not ref.arxiv:
        m = ARXIV_RE.search(raw)
        if m:
            ref.arxiv = m.group(1)
    if not ref.url:
        m = URL_RE.search(raw)
        if m:
            ref.url = m.group(0).rstrip(".,;)]}")
    if ref.year is None:
        paren = re.search(r"[(（]\s*(19[5-9]\d|20[0-4]\d)[a-z]?\s*[)）]", raw)
        years = YEAR_RE.findall(raw)
        if paren:
            ref.year = int(paren.group(1))
        elif years:
            ref.year = int(years[-1])
    return ref


def _segments_by_starts(texts: list[str], starts: list[int]) -> list[str]:
    segs = []
    for k, s in enumerate(starts):
        e = starts[k + 1] if k + 1 < len(starts) else len(texts)
        segs.append(join_lines(texts[s:e]))
    return segs


def _split_bracket(texts: list[str]) -> list[tuple[str, str]] | None:
    starts = [i for i, t in enumerate(texts) if _BRACKET_START.match(t)]
    if len(starts) < 2:
        return None
    segs = _segments_by_starts(texts, starts)
    return [(f"[{_BRACKET_START.match(texts[s]).group(1)}]", seg) for s, seg in zip(starts, segs)]


def _split_numbered(texts: list[str]) -> list[tuple[str, str]] | None:
    starts, labels, expected = [], [], 1
    for i, t in enumerate(texts):
        m = _NUM_START.match(t)
        if m and int(m.group(1)) == expected:
            starts.append(i)
            labels.append(m.group(1))
            expected += 1
    if len(starts) < 3:
        return None
    segs = _segments_by_starts(texts, starts)
    out = []
    for lab, seg in zip(labels, segs):
        seg = re.sub(r"^\s*" + lab + r"(?:[.．、)]\s*|\s+)", "", seg, count=1)
        out.append((lab + ".", seg))
    return out


def _columns(lines: list[RefLine]) -> list[list[RefLine]]:
    """按页、按栏分组（保持阅读顺序）。"""
    groups: list[list[RefLine]] = []
    by_page: dict[int, list[RefLine]] = {}
    for ln in lines:
        by_page.setdefault(ln[0], []).append(ln)
    for page in sorted(by_page):
        pl = by_page[page]
        xs = sorted(l[1] for l in pl)
        if xs[-1] - xs[0] > 150:
            mid = (xs[0] + xs[-1]) / 2
            left = [l for l in pl if l[1] < mid]
            right = [l for l in pl if l[1] >= mid]
            groups.extend(g for g in (left, right) if g)
        else:
            groups.append(pl)
    return groups


def _split_layout(lines: list[RefLine]) -> list[tuple[str, str]]:
    entries: list[list[str]] = []
    for col in _columns(lines):
        col_min = min(l[1] for l in col)
        flush = [l[1] <= col_min + 2.0 for l in col]
        ind_frac = 1 - sum(flush) / len(col)

        def score(start_flags: list[bool]) -> float:
            hits = total = 0
            for i, (l, st) in enumerate(zip(col, start_flags)):
                if st and i > 0:
                    total += 1
                    hits += bool(_AUTHOR_START.match(l[5])) + (col[i - 1][5].rstrip().endswith((".", "。")) * 0.5)
            return hits / total if total else 0.0

        starts: list[bool] | None = None
        if 0.1 < ind_frac < 0.9:
            hanging = flush
            first_line = [not f for f in flush]
            starts = hanging if score(hanging) >= score(first_line) else first_line
        if starts is None or score(starts) < 0.5:
            gaps = [col[i][2] - col[i - 1][4] for i in range(1, len(col))]
            if gaps:
                g = median(gaps)
                gap_starts = [True] + [gp > g + 1.5 and gp > 0 for gp in gaps]
                if sum(gap_starts) >= 2 and (starts is None or score(gap_starts) > score(starts)):
                    starts = gap_starts
        if starts is None or sum(starts) < 2:
            starts = [i == 0 or (_AUTHOR_START.match(l[5]) is not None and col[i - 1][5].rstrip().endswith("."))
                      for i, l in enumerate(col)]
        for l, st in zip(col, starts):
            if st or not entries:
                entries.append([l[5]])
            else:
                entries[-1].append(l[5])
    return [("", join_lines(e)) for e in entries]


def _finalize(pairs: list[tuple[str, str]]) -> list[Reference]:
    refs: list[Reference] = []
    numeric_labels = all(re.match(r"^\[?\d+[\].]?$", lab) for lab, _ in pairs if lab) and any(lab for lab, _ in pairs)
    for i, (lab, seg) in enumerate(pairs, 1):
        text = _clean_entry(seg)
        if len(text) < 15:
            continue
        rid = int(re.sub(r"\D", "", lab)) if numeric_labels and lab else len(refs) + 1
        refs.append(quick_fields(Reference(id=rid, raw=text[:1200], label=lab)))
    # 去重 id（编号异常时退化为顺序号）
    if len({r.id for r in refs}) != len(refs):
        for i, r in enumerate(refs, 1):
            r.id = i
    return refs


def split_references(lines: list[RefLine]) -> list[Reference]:
    lines = [l for l in lines if l[5].strip() and not _PURE_NUM.match(l[5])]
    if not lines:
        return []
    texts = [l[5] for l in lines]
    pairs = _split_bracket(texts) or _split_numbered(texts) or _split_layout(lines)
    return _finalize(pairs)


def split_references_from_text(text: str) -> list[Reference]:
    raw_lines = [ln for ln in text.replace("\r\n", "\n").split("\n")]
    texts = [ln for ln in raw_lines if ln.strip() and not _PURE_NUM.match(ln)]
    if not texts:
        return []
    pairs = _split_bracket(texts) or _split_numbered(texts)
    if pairs is None:
        blocks = [b for b in re.split(r"\n\s*\n", text) if b.strip()]
        if len(blocks) >= 2:
            pairs = [("", join_lines(b.split("\n"))) for b in blocks]
        else:
            pairs = [("", t) for t in texts]
    return _finalize(pairs)


# ----------------------------------------------------------------- 文中引用
_NUM_CITE = re.compile(r"[\[［]\s*(\d{1,3}(?:\s*[,，;；\-–—~]\s*\d{1,3})*)\s*[\]］]")
_NAME = r"[A-ZÀ-Þ][A-Za-zÀ-ɏ'’\-]+(?:\s+(?:van|von|de|der|da|di|la|le)\s+[A-Z][A-Za-zÀ-ɏ'’\-]+)?"
_AY_ITEM = re.compile(
    r"(" + _NAME + r")(?:\s+et\s+al\.?|\s+(?:and|&)\s+" + _NAME + r"|,\s+" + _NAME + r",?\s+(?:and|&)\s+" + _NAME + r")?"
    r",?\s*((?:19|20)\d{2})([a-z])?"
)
_AY_PAREN = re.compile(r"[(（]([^()（）]{4,400}?(?:19|20)\d{2}[a-z]?[^()（）]{0,40})[)）]")
_AY_NARRATIVE = re.compile(
    r"(" + _NAME + r")(?:\s+et\s+al\.?|\s+(?:and|&)\s+" + _NAME + r")?\s*[(（]((?:19|20)\d{2})([a-z])?(?:[,;，；][^)）]*)?[)）]"
)
_ZH_AY = re.compile(r"([一-鿿]{2,4})(?:等|等人)?[,，]\s*((?:19|20)\d{2})([a-z])?")


def _expand_numbers(spec: str) -> list[int]:
    nums: list[int] = []
    for part in re.split(r"[,，;；]", spec):
        part = part.strip()
        if not part:
            continue
        rng = re.split(r"\s*[\-–—~]\s*", part)
        try:
            if len(rng) == 2:
                a, b = int(rng[0]), int(rng[1])
                if 0 < a <= b and b - a <= 60:
                    nums.extend(range(a, b + 1))
            else:
                nums.append(int(part))
        except ValueError:
            continue
    return nums


class _AuthorYearIndex:
    def __init__(self, refs: list[Reference]):
        self.items = []
        for r in refs:
            head = ascii_fold(r.raw[:160]).lower()
            years = {int(y) for y in YEAR_RE.findall(r.raw)}
            self.items.append((r.id, head, years))

    def lookup(self, surname: str, year: int, suffix: str | None) -> int | None:
        s = ascii_fold(surname).lower()
        cands = [(head.find(s), rid) for rid, head, years in self.items if year in years and s in head]
        if not cands:
            return None
        cands.sort()
        if suffix and len(cands) > 1:  # 2020a / 2020b：按出现顺序取第 n 个
            idx = ord(suffix) - ord("a")
            same = sorted(rid for pos, rid in cands if pos == cands[0][0])
            if 0 <= idx < len(same):
                return same[idx]
        return cands[0][1]


def extract_citations(paragraphs: list[Paragraph], refs: list[Reference], lang: str) -> tuple[list[Citation], str]:
    ref_ids = {r.id for r in refs}
    ay_index = _AuthorYearIndex(refs) if refs else None
    citations: list[Citation] = []
    n_numeric = n_ay = 0

    for p in paragraphs:
        if p.kind not in ("body", "caption", "abstract"):
            continue
        sents = split_sentences(p.text, lang)
        for si, sent in enumerate(sents):
            markers: list[str] = []
            ids: list[int] = []
            for m in _NUM_CITE.finditer(sent):
                nums = _expand_numbers(m.group(1))
                if not nums or 0 in nums:
                    continue
                if ref_ids:
                    nums = [n for n in nums if n in ref_ids]
                    if not nums:
                        continue
                markers.append(m.group(0))
                ids.extend(nums)
                n_numeric += 1
            if ay_index is not None:
                spans: list[tuple[int, int]] = []
                for m in _AY_PAREN.finditer(sent):
                    found = False
                    for part in re.split(r"[;；]", m.group(1)):
                        for im in list(_AY_ITEM.finditer(part)) + list(_ZH_AY.finditer(part)):
                            rid = ay_index.lookup(im.group(1), int(im.group(2)), im.group(3))
                            if rid is not None:
                                ids.append(rid)
                                found = True
                    if found:
                        markers.append(m.group(0))
                        spans.append(m.span())
                        n_ay += 1
                for m in _AY_NARRATIVE.finditer(sent):
                    if any(a <= m.start(2) <= b for a, b in spans):
                        continue
                    rid = ay_index.lookup(m.group(1), int(m.group(2)), m.group(3))
                    if rid is not None:
                        ids.append(rid)
                        markers.append(m.group(0))
                        n_ay += 1
            if not ids:
                continue
            uniq = list(dict.fromkeys(ids))
            context = (sents[si - 1] + " " + sent) if si > 0 else sent
            citations.append(Citation(
                id=len(citations) + 1, paragraph_id=p.id, page=p.page, section=p.section,
                sentence=sent, context=context, markers=list(dict.fromkeys(markers)), ref_ids=uniq,
            ))
    style = "numeric" if n_numeric >= n_ay and n_numeric > 0 else ("author-year" if n_ay > 0 else "unknown")
    return citations, style
