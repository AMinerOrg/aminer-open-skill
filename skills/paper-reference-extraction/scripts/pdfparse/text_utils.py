"""文本归一化、语言判断、分句、行拼接。"""

from __future__ import annotations

import re
import unicodedata

_LIGATURES = {"ﬀ": "ff", "ﬁ": "fi", "ﬂ": "fl", "ﬃ": "ffi", "ﬄ": "ffl", "ﬅ": "st", "ﬆ": "st"}
# LaTeX 生成的 PDF 常把重音拆成“间距修饰符 + 字母”，如 Universit´e
_SPACING_ACCENTS = {
    "´": "́", "¨": "̈", "ˆ": "̂", "˜": "̃", "¸": "̧",
    "ˇ": "̌", "˘": "̆", "˚": "̊", "¯": "̄", "˝": "̋", "ˋ": "̀",
}
_ACCENT_RE = re.compile("([" + "".join(_SPACING_ACCENTS) + r"])\s?([A-Za-zıȷ])")
_CJK_RE = re.compile(r"[一-鿿㐀-䶿]")
_WS_RE = re.compile(r"[ \t  -​　]+")


def normalize_text(s: str) -> str:
    for k, v in _LIGATURES.items():
        s = s.replace(k, v)
    s = _ACCENT_RE.sub(lambda m: unicodedata.normalize("NFC", m.group(2).replace("ı", "i") + _SPACING_ACCENTS[m.group(1)]), s)
    s = s.replace("­", "")  # 软连字符
    s = _WS_RE.sub(" ", s)
    return s


def is_cjk(ch: str) -> bool:
    return bool(_CJK_RE.match(ch))


def cjk_ratio(s: str) -> float:
    letters = [c for c in s if c.isalpha()]
    if not letters:
        return 0.0
    return sum(1 for c in letters if is_cjk(c)) / len(letters)


def detect_lang(s: str) -> str:
    return "zh" if cjk_ratio(s[:20000]) > 0.25 else "en"


def join_lines(lines: list[str]) -> str:
    """拼接 PDF 行：处理英文断词连字符、中英文空格。"""
    out = ""
    for raw in lines:
        line = raw.strip()
        if not line:
            continue
        if not out:
            out = line
            continue
        prev = out[-1]
        first = line[0]
        if prev == "-" and len(out) >= 2 and out[-2].isalpha() and first.islower():
            out = out[:-1] + line  # 断词：ac- cess → access
        elif _needs_space(prev, first):
            out += " " + line
        else:
            out += line
    return re.sub(r"\s{2,}", " ", out).strip()


def _needs_space(prev: str, first: str) -> bool:
    if is_cjk(prev) or is_cjk(first):
        return False
    if prev in "（(“‘[【/" or first in "，。；：！？、）)”’]】,.;:!?/":
        return False
    return True


def ends_paragraph(s: str) -> bool:
    """段落是否可能在此结束（不含冒号/分号）。"""
    s = s.rstrip().rstrip("\"'”’)]）】")
    return bool(s) and s[-1] in ".!?。！？…"


def ends_sentence(s: str) -> bool:
    s = s.rstrip().rstrip("\"'”’)]）】")
    return bool(s) and s[-1] in ".!?。！？:：;；"


# ----------------------------------------------------------------- 分句
_EN_ABBR = [
    "et al.", "e.g.", "i.e.", "etc.", "Fig.", "Figs.", "Eq.", "Eqs.", "Sec.", "Secs.", "Tab.", "Tabs.",
    "vs.", "cf.", "Ref.", "Refs.", "No.", "Nos.", "Vol.", "pp.", "Dr.", "Mr.", "Ms.", "Mrs.", "Prof.",
    "approx.", "resp.", "w.r.t.", "a.k.a.", "Ch.", "Thm.", "Def.", "Alg.", "Appx.", "St.", "Jr.", "Inc.",
]
_PH = "․"  # one dot leader 作为占位
_ABBR_RE = re.compile("|".join(re.escape(a) for a in sorted(_EN_ABBR, key=len, reverse=True)), re.I)
_INITIAL_RE = re.compile(r"\b([A-Z])\.(?=\s*[A-Z])")
_EN_SPLIT = re.compile(r"(?<=[.!?])[\"”’)\]]*\s+(?=[\"“(\[]?[A-Z0-9])")
_ZH_SPLIT = re.compile(r"(?<=[。！？；!?])[”’」』）)]*")


def split_sentences(text: str, lang: str = "en") -> list[str]:
    text = text.strip()
    if not text:
        return []
    if lang == "zh":
        parts: list[str] = []
        last = 0
        for m in _ZH_SPLIT.finditer(text):
            end = m.end()
            if end > last:
                parts.append(text[last:end])
                last = end
        if last < len(text):
            parts.append(text[last:])
        sents = [p.strip() for p in parts if p.strip()]
        # 中文段落里的英文句也要拆
        out: list[str] = []
        for s in sents:
            out.extend(_split_en(s) if cjk_ratio(s) < 0.2 else [s])
        return _merge_tiny(out, min_len=3)
    return _merge_tiny(_split_en(text))


def _split_en(text: str) -> list[str]:
    protected = _ABBR_RE.sub(lambda m: m.group(0).replace(".", _PH), text)
    protected = _INITIAL_RE.sub(lambda m: m.group(1) + _PH, protected)
    parts = _EN_SPLIT.split(protected)
    return [p.replace(_PH, ".").strip() for p in parts if p.strip()]


def _merge_tiny(sents: list[str], min_len: int = 6) -> list[str]:
    """把过短的碎片（如孤立的“[3].”）并回前一句；中英文分别用不同的连接方式。"""
    out: list[str] = []
    for s in sents:
        if out and len(s) < min_len:
            out[-1] = join_lines([out[-1], s])
        else:
            out.append(s)
    return out


def word_count(text: str, lang: str) -> int:
    if lang == "zh":
        return len(_CJK_RE.findall(text)) + len(re.findall(r"[A-Za-z]+", text))
    return len(re.findall(r"[A-Za-z0-9]+(?:[-'][A-Za-z0-9]+)*", text))


def norm_title(s: str) -> str:
    """标题比对用的归一化：去重音、小写、去标点。"""
    s = unicodedata.normalize("NFKD", s or "")
    s = "".join(c for c in s if not unicodedata.combining(c))
    s = s.lower()
    s = re.sub(r"<[^>]+>", " ", s)  # 去掉 Crossref 里的 <i> 等标签
    s = re.sub(r"[^\w一-鿿]+", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def ascii_fold(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "")
    return "".join(c for c in s if not unicodedata.combining(c))
