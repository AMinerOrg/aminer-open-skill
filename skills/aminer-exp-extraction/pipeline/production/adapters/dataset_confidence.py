"""Dataset confidence scoring — post-hoc, deterministic, no LLM.

For each dataset extracted by the LLM, computes a confidence score in [0, 1]
based on evidence from the full paper text (not the BERT-filtered subset).

Mounted after ``normalize_llm_datasets`` in Stage-B (``run_llm_stage_wf4``).

Algorithm spec: see ``pipeline/production/docs/STRATEGY_DATASET_CONFIDENCE.md``
and the handoff document "Dataset 置信度后验打分".
"""

from __future__ import annotations

import re
from copy import deepcopy
from math import log
from typing import Any

# ── Hyper-parameters (centralised for tuning) ────────────────────────────── #

FREQUENCY_C: int = 10            # log-saturation constant for frequency
USAGE_WINDOW: int = 2            # ±N sentences around a mention for usage
WEIGHT_FREQUENCY: float = 0.25
WEIGHT_USAGE: float = 0.30
WEIGHT_IDENTIFIER: float = 0.30
WEIGHT_COMPLETENESS: float = 0.15
IDENTIFIER_FLOOR: float = 0.85   # c1 floor when identifier_hit
IDENTIFIER_STRONG_USAGE_FLOOR: float = 0.95  # c2 floor when id_hit + strong usage
S1_SOFT_CAP: float = 0.35        # max confidence when no mention and no id hit
S2_FAKE_CAP: float = 0.35        # max c0 when fake_identifier
GLOBAL_CAP: float = 1.0
STRONG_USAGE_THRESHOLD: float = 0.85  # usage ≥ this counts as "strong"

# ── Usage signal word lists ──────────────────────────────────────────────── #
# Strong positive (hit → usage = 1.00)
USAGE_STRONG_PATTERNS: list[re.Pattern[str]] = [
    re.compile(p, re.IGNORECASE)
    for p in [
        r"\btrain(?:ed|ing)?\b",
        r"\bfine[\s-]?tun(?:e|ed|ing)\b",
        r"\bpre[\s-]?train(?:ed|ing)?\b",
        r"\bevaluat(?:e|ed|ing|ion)\b",
        r"\btested\s+on\b",
        r"\bwe\s+use(?:d)?\b",
        r"\busing\b",
        r"\bemployed\b",
        r"\bconducted\s+on\b",
        r"\bexperiments?\s+on\b",
        r"\bbenchmark(?:ed)?\s+on\b",
        r"\btraining\s+set\b",
        r"\btest(?:ing)?\s+set\b",
        r"\bvalidation\s+set\b",
        r"\bdev\s+set\b",
        r"\btrain/val/test\b",
        r"\bon\s+the\s+",   # "on the <name>"
        r"\bon\s+",         # "on <name>" — broad but needed
        r"\bacross\s+",
        r"\bfrom\s+",
        r"\bdataset\s+",
    ]
]

# Medium positive (no strong, has medium → usage = 0.70)
USAGE_MEDIUM_PATTERNS: list[re.Pattern[str]] = [
    re.compile(p, re.IGNORECASE)
    for p in [
        r"\bbenchmark\b",
        r"\bbaseline\b",
        r"\bcompar(?:e|ed|ing|ison)\s+on\b",
        r"\bresults?\s+on\b",
        r"\bperformance\s+on\b",
        r"\baccuracy\s+on\b",
        r"\breported\s+on\b",
        r"\bpublic\s+dataset\b",
        r"\bwidely\s+used\b",
    ]
]

# Weak / negative co-occurrence (only weak → usage = 0.30)
USAGE_WEAK_PATTERNS: list[re.Pattern[str]] = [
    re.compile(p, re.IGNORECASE)
    for p in [
        r"\bproposed\s+by\b",
        r"\bintroduced\s+by\b",
        r"\bet\s+al\.?\b",
        r"\bprior\s+work\b",
        r"\bprevious\s+work\b",
        r"\binspired\s+by\b",
        r"\bsimilar\s+to\b",
    ]
]


# ── Text utilities ───────────────────────────────────────────────────────── #

def _normalize_text(text: str) -> str:
    """Lowercase, collapse whitespace, strip."""
    return re.sub(r"\s+", " ", text.lower().strip())


def _dedup_sentences(text: str) -> str:
    """Remove duplicate sentences/paragraphs to avoid inflating frequency."""
    # Split on sentence-ending punctuation + whitespace
    parts = re.split(r"(?<=[.!?])\s+", text)
    seen: set[str] = set()
    out: list[str] = []
    for part in parts:
        norm = re.sub(r"\s+", " ", part.strip().lower())
        if norm and norm not in seen:
            seen.add(norm)
            out.append(part.strip())
    return " ".join(out)


def _split_sentences_for_scoring(text: str) -> list[str]:
    """Split text into sentences for usage window analysis.

    Unlike the BERT-oriented ``split_sentences`` (which drops len<=15),
    this keeps short sentences because usage signals can appear in brief
    contexts like "We use X." or "Trained on Y."
    """
    parts = re.split(r"(?<=[.!?])\s+", text)
    result: list[str] = []
    for part in parts:
        s = part.strip()
        if s:
            result.append(s)
    return result


# ── Identifier normalisation ─────────────────────────────────────────────── #

def _normalize_url(url: str) -> str:
    """Normalise a URL for matching: lowercase, strip trailing /, http↔https, no www."""
    u = url.lower().strip()
    u = u.rstrip("/")
    u = re.sub(r"^https?://(www\.)?", "", u)
    return u


def _normalize_doi(doi: str) -> str:
    """Normalise DOI: strip prefix, lowercase.

    Makes ``doi.org/10.xxx`` and bare ``10.xxx`` equivalent.
    """
    d = doi.lower().strip()
    d = re.sub(r"^(https?://)?doi\.org/", "", d)
    d = re.sub(r"^doi:", "", d)
    return d.strip()


def _normalize_identifier(raw: str, kind: str) -> str:
    """Normalise an identifier based on its kind (urls/github_urls/doi_list/cstr_list)."""
    if kind in ("urls", "github_urls"):
        return _normalize_url(raw)
    if kind in ("doi_list",):
        return _normalize_doi(raw)
    # cstr_list and others: just lowercase + strip
    return raw.lower().strip()


# ── Lexicon building ─────────────────────────────────────────────────────── #

def _build_lexicon(
    name: str,
    aliases: list[str],
    text_lower: str,
) -> list[tuple[str, bool]]:
    """Build (pattern, needs_word_boundary) list from name + aliases.

    An alias is only included if it occurs ≥1 time in the normalised text.
    Short tokens (<4 chars) always use word-boundary matching.
    """
    lexicon: list[tuple[str, bool]] = []

    # Name always included
    name_norm = name.strip().lower()
    if name_norm:
        needs_wb = len(name_norm.split()[0]) < 4 if " " in name_norm else len(name_norm) < 4
        lexicon.append((name_norm, needs_wb))

    # Aliases: only if they appear in the text
    for alias in (aliases or []):
        a = alias.strip().lower()
        if not a or a == name_norm:
            continue
        # Check presence in text (simple substring; word boundary checked later)
        if a not in text_lower:
            continue
        needs_wb = len(a.split()[0]) < 4 if " " in a else len(a) < 4
        lexicon.append((a, needs_wb))

    return lexicon


def _count_mentions(
    lexicon: list[tuple[str, bool]],
    text_lower: str,
    sentences: list[str],
) -> tuple[int, list[int]]:
    """Count raw mentions and return (raw_count, hit_sentence_indices).

    Short tokens (<4 chars → needs_wb=True) require word-boundary matching.
    Hit positions are returned as sentence indices.
    """
    raw_count = 0
    hit_positions: set[int] = set()

    for token, needs_wb in lexicon:
        if needs_wb:
            pattern = re.compile(r"\b" + re.escape(token) + r"\b", re.IGNORECASE)
        else:
            pattern = re.compile(re.escape(token), re.IGNORECASE)

        # Count in full text
        raw_count += len(pattern.findall(text_lower))

        # Find which sentences contain the mention
        for idx, sent in enumerate(sentences):
            if pattern.search(sent):
                hit_positions.add(idx)

    return raw_count, sorted(hit_positions)


# ── Usage scoring ────────────────────────────────────────────────────────── #

def _score_usage(
    hit_positions: list[int],
    sentences: list[str],
) -> float:
    """Score usage based on signal words in windows around name mentions.

    For each hit position, examine the window [pos-2, pos+2].
    Strong positive → 1.00; medium → 0.70; weak → 0.30; none → 0.0.
    Return the max usage across all windows.
    """
    if not hit_positions:
        return 0.0

    best_usage = 0.0
    n = len(sentences)

    for pos in hit_positions:
        start = max(0, pos - USAGE_WINDOW)
        end = min(n, pos + USAGE_WINDOW + 1)
        window_text = " ".join(sentences[start:end])

        has_strong = any(p.search(window_text) for p in USAGE_STRONG_PATTERNS)
        has_medium = any(p.search(window_text) for p in USAGE_MEDIUM_PATTERNS)
        has_weak = any(p.search(window_text) for p in USAGE_WEAK_PATTERNS)

        if has_strong:
            usage = 1.00
        elif has_medium:
            usage = 0.70
        elif has_weak:
            usage = 0.30
        else:
            usage = 0.0

        best_usage = max(best_usage, usage)

    return best_usage


# ── Identifier verification ──────────────────────────────────────────────── #

_IDENTIFIER_FIELDS = ("urls", "github_urls", "doi_list", "cstr_list")

# Path extensions that are almost never dataset landing pages (OCR/asset junk).
_URL_EXTENSION_DENYLIST: frozenset[str] = frozenset({
    "png", "jpg", "jpeg", "gif", "webp", "bmp", "svg",
    "pdf", "eps", "ps",
    "zip", "tar", "gz", "tgz", "rar", "7z",
    "mp4", "avi", "mov",
    "csv",
})

_VERSION_SUFFIX_RE = re.compile(r"[\s\-_/]*v?\d+(?:\.\d+)*$", re.IGNORECASE)
_NON_ALNUM_RE = re.compile(r"[^a-z0-9]+")


def _url_path_extension(url: str) -> str:
    """Return the lowercase file extension of a URL path (no leading dot), or ''."""
    u = url.strip()
    # Drop scheme for path parsing; keep host/path.
    u = re.sub(r"^https?://", "", u, flags=re.IGNORECASE)
    path = u.split("?", 1)[0].split("#", 1)[0].rstrip("/")
    if not path:
        return ""
    last = path.rsplit("/", 1)[-1]
    if "." not in last:
        return ""
    return last.rsplit(".", 1)[-1].lower()


def _url_compact(url: str) -> str:
    """Compact host+path for name-coverage: normalised URL with non-alnum removed."""
    return _NON_ALNUM_RE.sub("", _normalize_url(url))


def _name_to_slug(label: str) -> str:
    """Normalise a dataset name/alias to an alphanumeric slug (version stripped)."""
    s = (label or "").strip().lower()
    if not s:
        return ""
    s = _VERSION_SUFFIX_RE.sub("", s).strip()
    return _NON_ALNUM_RE.sub("", s)


def _dataset_name_slugs(name: str, aliases: list[str] | None) -> list[str]:
    """Unique compact slugs from name + aliases (empty strings dropped)."""
    seen: set[str] = set()
    out: list[str] = []
    for label in [name, *(aliases or [])]:
        slug = _name_to_slug(label)
        if slug and slug not in seen:
            seen.add(slug)
            out.append(slug)
    return out


def _passes_url_name_coverage(
    url: str,
    name: str,
    aliases: list[str] | None,
) -> bool:
    """Scheme A: a name/alias slug (len>=3) must be a contiguous substring of URL compact.

    If every slug is shorter than 3 characters, skip the name gate (return True).
    """
    slugs = _dataset_name_slugs(name, aliases)
    usable = [s for s in slugs if len(s) >= 3]
    if not usable:
        return True
    compact = _url_compact(url)
    if not compact:
        return False
    return any(slug in compact for slug in usable)


def _is_code_host(url: str) -> bool:
    """True if normalised host looks like GitHub or GitLab."""
    host = _normalize_url(url).split("/", 1)[0]
    return (
        "github.com" in host
        or "gitlab.com" in host
        or host.startswith("gitlab.")
        or ".gitlab." in host
    )


def _passes_url_quality_gates(
    raw_url: str,
    field: str,
    name: str,
    aliases: list[str] | None,
) -> bool:
    """Extension denylist + (for github_urls) code-host + name coverage A."""
    if field == "github_urls" and not _is_code_host(raw_url):
        return False
    ext = _url_path_extension(raw_url)
    if ext in _URL_EXTENSION_DENYLIST:
        return False
    return _passes_url_name_coverage(raw_url, name, aliases)


def _verify_identifiers(
    d: dict[str, Any],
    text_lower: str,
) -> tuple[float, bool, bool, dict[str, Any]]:
    """Check if any identifier in the dataset hits in the full text.

    Returns (identifier_score, identifier_hit, fake_identifier, modified_dataset).
    If an identifier is non-empty but fails to match in the paper, it is cleared
    (set to []) and fake_identifier=True.

    For ``urls`` / ``github_urls``, after a verbatim hit, also require:
    - path extension not in the asset/document denylist;
    - ``github_urls`` host contains github.com or gitlab;
    - scheme-A name coverage (normalised name/alias slug ⊆ URL host+path),
      skipped when all slugs are shorter than 3 chars.

    ``doi_list`` / ``cstr_list`` keep verbatim-only checks. Empty lists are allowed.

    The dataset is shallow-copied before any mutation.
    """
    identifier_hit = False
    fake_identifier = False
    any_id_present = False
    d = dict(d)  # shallow copy
    name = (d.get("name") or "").strip()
    aliases = d.get("aliases") or []

    for field in _IDENTIFIER_FIELDS:
        raw_list: list[str] = d.get(field, []) or []
        if not raw_list:
            continue

        kept: list[str] = []
        for raw_val in raw_list:
            norm = _normalize_identifier(raw_val, field)
            if not norm:
                continue
            any_id_present = True

            if norm not in text_lower:
                # Identifier claimed but not found in paper → fake, clear it
                fake_identifier = True
                continue

            if field in ("urls", "github_urls"):
                if not _passes_url_quality_gates(raw_val, field, name, aliases):
                    fake_identifier = True
                    continue

            identifier_hit = True
            kept.append(raw_val)

        d[field] = kept

    if identifier_hit:
        identifier_score = 1.0
    elif any_id_present:
        # All identifiers were fake
        identifier_score = 0.0
    else:
        # No identifier fields present at all
        identifier_score = 0.0

    return identifier_score, identifier_hit, fake_identifier, d


# ── Completeness ─────────────────────────────────────────────────────────── #

def _score_completeness(d: dict[str, Any]) -> float:
    """Average of 7 binary slots."""
    slots = [
        bool(d.get("dataset_type")),
        bool(d.get("description")),
        d.get("sample_size") is not None,
        d.get("is_public") is not None,
        d.get("is_self_collected") is not None,
        bool(d.get("aliases")),
        any(
            bool(d.get(field))
            for field in _IDENTIFIER_FIELDS
        ),
    ]
    return sum(slots) / len(slots)


# ── Main API ─────────────────────────────────────────────────────────────── #

def score_datasets_confidence(
    datasets: list[dict[str, Any]],
    full_text: str,
    *,
    sort: bool = True,
) -> list[dict[str, Any]]:
    """Score each dataset with a confidence value in [0, 1].

    - Does NOT delete any entries.
    - Writes ``confidence`` and ``confidence_breakdown`` into each dataset dict.
    - If sort=True, returns datasets sorted by confidence descending (stable).
    - Pure function: no IO, no LLM, deterministic.
    """
    if not datasets or not full_text:
        # No datasets or no text to score against — return as-is with low scores
        out = []
        for d in datasets:
            d = dict(d)  # shallow copy
            d["confidence"] = 0.0
            d["confidence_breakdown"] = {
                "frequency": 0.0,
                "usage": 0.0,
                "identifier": 0.0,
                "completeness": _score_completeness(d) if full_text else 0.0,
                "c0": 0.0,
                "mention_matched": False,
                "identifier_hit": False,
                "fake_identifier": False,
                "raw_count": 0,
            }
            out.append(d)
        return out

    # Preprocess full text
    text_deduped = _dedup_sentences(full_text)
    text_lower = _normalize_text(text_deduped)
    sentences = _split_sentences_for_scoring(text_deduped)
    sentences_lower = [_normalize_text(s) for s in sentences]

    out: list[dict[str, Any]] = []

    for d in datasets:
        d = dict(d)  # shallow copy to avoid mutating caller's data

        name = d.get("name", "").strip()
        if not name:
            # Should not happen (normalize drops empty names), but be safe
            out.append(d)
            continue

        aliases = d.get("aliases") or []

        # Build lexicon and count mentions
        lexicon = _build_lexicon(name, aliases, text_lower)
        raw_count, hit_positions = _count_mentions(lexicon, text_lower, sentences_lower)
        mention_matched = raw_count > 0

        # Frequency (log-saturated, scheme B)
        frequency = min(1.0, log(1 + raw_count) / log(1 + FREQUENCY_C))

        # Usage
        usage = _score_usage(hit_positions, sentences_lower)

        # Identifier verification (may mutate identifier lists)
        identifier_score, identifier_hit, fake_identifier, d = _verify_identifiers(d, text_lower)

        # Completeness
        completeness = _score_completeness(d)

        # Composite
        c0 = (
            WEIGHT_FREQUENCY * frequency
            + WEIGHT_USAGE * usage
            + WEIGHT_IDENTIFIER * identifier_score
            + WEIGHT_COMPLETENESS * completeness
        )

        # S2: fake_identifier is recorded in breakdown but does NOT cap c0.
        # The scoring penalty is already reflected: identifier_score=0 (no hit)
        # and the fake URL/DOI is cleared from the dataset. An additional
        # hard cap was found to eliminate all score differentiation since
        # LLM-generated identifiers are almost universally absent from paper text.

        # Identifier floor
        c1 = max(c0, IDENTIFIER_FLOOR) if identifier_hit else c0

        # Identifier + strong usage floor
        c2 = max(c1, IDENTIFIER_STRONG_USAGE_FLOOR) if (identifier_hit and usage >= STRONG_USAGE_THRESHOLD) else c1

        # S1: no mention and no identifier → soft cap
        if not mention_matched and not identifier_hit:
            c2 = min(c2, S1_SOFT_CAP)

        # Global cap
        confidence = min(GLOBAL_CAP, c2)

        # Write fields
        d["confidence"] = round(confidence, 6)
        d["confidence_breakdown"] = {
            "frequency": round(frequency, 6),
            "usage": round(usage, 6),
            "identifier": round(identifier_score, 6),
            "completeness": round(completeness, 6),
            "c0": round(c0, 6),
            "mention_matched": mention_matched,
            "identifier_hit": identifier_hit,
            "fake_identifier": fake_identifier,
            "raw_count": raw_count,
        }

        out.append(d)

    if sort:
        # Stable sort: confidence desc, then usage → frequency → identifier_hit → completeness
        out.sort(
            key=lambda x: (
                -x.get("confidence", 0),
                -x.get("confidence_breakdown", {}).get("usage", 0),
                -x.get("confidence_breakdown", {}).get("frequency", 0),
                -int(x.get("confidence_breakdown", {}).get("identifier_hit", False)),
                -x.get("confidence_breakdown", {}).get("completeness", 0),
            )
        )

    return out
