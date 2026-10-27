"""解析结果数据结构（全部可 JSON 序列化）。"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass
class Paragraph:
    id: int
    page: int  # 1-based
    section: str
    text: str
    kind: str = "body"  # body | abstract | caption

    @property
    def chars(self) -> int:
        return len(self.text)


@dataclass
class Reference:
    id: int  # 文献表中的序号（数字制即 [n] 的 n；作者-年份制为出现顺序）
    raw: str
    label: str = ""  # 原始标签，如 "[12]"、"12."；作者-年份制为空
    # 结构化字段（由 LLM / 规则 / BibTeX 填充）
    title: str = ""
    authors: list[str] = field(default_factory=list)
    year: int | None = None
    venue: str = ""
    doi: str = ""
    arxiv: str = ""
    url: str = ""
    kind: str = ""  # journal | conference | preprint | book | thesis | web | software | dataset | other


@dataclass
class Citation:
    """文中一处引用句。"""

    id: int
    paragraph_id: int
    page: int
    section: str
    sentence: str
    context: str
    markers: list[str]
    ref_ids: list[int]


@dataclass
class Section:
    title: str
    level: int
    page: int


@dataclass
class ParsedDocument:
    title: str = ""
    lang: str = "en"  # en | zh
    pages: int = 0
    source: str = "pdf"  # pdf | text | bib
    citation_style: str = "unknown"  # numeric | author-year | superscript | unknown
    paragraphs: list[Paragraph] = field(default_factory=list)
    sections: list[Section] = field(default_factory=list)
    references: list[Reference] = field(default_factory=list)
    citations: list[Citation] = field(default_factory=list)
    references_text: str = ""  # 参考文献区原文（规则切分失败时交给 LLM）
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "ParsedDocument":
        doc = cls(**{k: v for k, v in d.items() if k not in ("paragraphs", "sections", "references", "citations")})
        doc.paragraphs = [Paragraph(**p) for p in d.get("paragraphs", [])]
        doc.sections = [Section(**s) for s in d.get("sections", [])]
        doc.references = [Reference(**r) for r in d.get("references", [])]
        doc.citations = [Citation(**c) for c in d.get("citations", [])]
        return doc

    @property
    def body_chars(self) -> int:
        return sum(len(p.text) for p in self.paragraphs if p.kind != "caption")

    def stats(self) -> dict[str, Any]:
        body = " ".join(p.text for p in self.paragraphs if p.kind != "caption")
        if self.lang == "zh":
            words = sum(1 for ch in body if "一" <= ch <= "鿿")
        else:
            words = len(body.split())
        return {
            "pages": self.pages,
            "paragraphs": len(self.paragraphs),
            "references": len(self.references),
            "citations": len(self.citations),
            "words": words,
            "chars": len(body),
            "sections": len([s for s in self.sections if s.level == 1]),
        }
