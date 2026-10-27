"""Label-file readers and the scoring formulas (shared by prepare_scoring and aggregate_insight).

The label files are written by the agent, so the formats are deliberately forgiving: everything is normalized on
read, and problems come back as warnings instead of crashes.
"""

from __future__ import annotations

import json
from pathlib import Path
from statistics import mean, median, stdev

SENT_TYPES = ("context", "citation", "opinion")
SECTION_TYPES = ("descriptive", "comparative", "analytical")
DIMS = ("depth", "breadth", "height")
LEVELS = ("low", "medium", "high")

_SENT_ALIAS = {
    "context": "context", "background": "context", "背景": "context", "背景句": "context", "上下文": "context",
    "citation": "citation", "cite": "citation", "citing": "citation", "引用": "citation", "引用句": "citation",
    "opinion": "opinion", "viewpoint": "opinion", "claim": "opinion", "观点": "opinion", "观点句": "opinion",
}
_SEC_ALIAS = {
    "descriptive": "descriptive", "描述": "descriptive", "描述型": "descriptive", "描述性": "descriptive",
    "comparative": "comparative", "对比": "comparative", "比较": "comparative", "对比型": "comparative",
    "analytical": "analytical", "analysis": "analytical", "分析": "analytical", "分析型": "analytical", "分析性": "analytical",
}


# ----------------------------------------------------------------------------- reading
def read_json_files(paths: list[Path], pattern: str = "*.json") -> list[tuple[Path, object]]:
    """Files are read directly; directories are scanned recursively for `pattern`
    (so stage-1 labels and sections.json can live in the same labels/ directory)."""
    files: list[Path] = []
    for p in paths:
        p = Path(p)
        files.extend(sorted(p.rglob(pattern)) if p.is_dir() else [p])
    return [(f, json.loads(f.read_text(encoding="utf-8"))) for f in files]


def _norm(table: dict[str, str], v) -> str | None:
    return table.get(str(v).strip().lower()) if v is not None else None


def load_stage1(paths: list[Path]) -> tuple[dict[int, str], set[int], list[str]]:
    """Return (id -> type, ids covered by some label file, warnings).

    Accepted shapes:
      1. {"12": "opinion", "13": "citation", ...}                       one label per sentence (covered = ids present)
      2. {"range": [1, 40], "opinion": [3, 5], "citation": [2, 4]}     unlisted ids inside the range are `context`
      3. [{"id": 12, "type": "opinion"}, ...]
    """
    labels: dict[int, str] = {}
    covered: set[int] = set()
    warns: list[str] = []
    for f, data in read_json_files(paths, "stage1*.json"):
        if isinstance(data, list):
            for it in data:
                t = _norm(_SENT_ALIAS, it.get("type") if isinstance(it, dict) else None)
                if isinstance(it, dict) and "id" in it and t:
                    labels[int(it["id"])] = t
                    covered.add(int(it["id"]))
                else:
                    warns.append(f"{f.name}: unrecognized item {it!r}")
            continue
        if not isinstance(data, dict):
            warns.append(f"{f.name}: top level must be an object or an array")
            continue
        if "range" in data:
            lo, hi = (int(x) for x in data["range"])
            covered.update(range(lo, hi + 1))
            for i in range(lo, hi + 1):
                labels.setdefault(i, "context")
            for key, ids in data.items():
                if key == "range":
                    continue
                t = _norm(_SENT_ALIAS, key)
                if t is None or not isinstance(ids, list):
                    warns.append(f"{f.name}: unknown key {key!r}")
                    continue
                for i in ids:
                    if not lo <= int(i) <= hi:
                        warns.append(f"{f.name}: id {i} is outside range {lo}-{hi}")
                    labels[int(i)] = t
                    covered.add(int(i))
        else:
            for k, v in data.items():
                t = _norm(_SENT_ALIAS, v)
                try:
                    i = int(k)
                except ValueError:
                    warns.append(f"{f.name}: key {k!r} is not a sentence id")
                    continue
                if t is None:
                    warns.append(f"{f.name}: sentence {i} has invalid type {v!r} (use context/citation/opinion)")
                    continue
                labels[i] = t
                covered.add(i)
    return labels, covered, warns


def _score_items(data) -> list:
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        if isinstance(data.get("scores"), list):
            return data["scores"]
        return [dict(v, id=k) for k, v in data.items() if isinstance(v, dict)]  # {"57": {"depth": 3, ...}}
    return []


def load_scores(paths: list[Path]) -> tuple[dict[int, dict], list[str]]:
    """Each item: {"id", "depth", "breadth", "height", "confidence"?, "rationale"?}; the last item per id wins."""
    scores: dict[int, dict] = {}
    warns: list[str] = []
    for f, data in read_json_files(paths):
        for it in _score_items(data):
            try:
                i = int(it["id"])
                vals = {}
                for d in DIMS:
                    x = float(it[d])
                    if x != int(x):
                        warns.append(f"{f.name}: sentence {i} {d}={x} is not an integer, rounded")
                    x = int(round(x))
                    if not 1 <= x <= 5:
                        raise ValueError(f"{d}={x} is outside 1-5")
                    vals[d] = x
            except (KeyError, TypeError, ValueError) as exc:
                warns.append(f"{f.name}: invalid score item {it!r} ({exc})")
                continue
            conf = str(it.get("confidence") or "").lower()
            scores[i] = {"id": i, **vals, "confidence": conf if conf in ("low", "medium", "high") else "",
                         "rationale": str(it.get("rationale") or "").strip()}
    return scores, warns


def load_section_types(paths: list[Path], sections: list[dict]) -> tuple[dict[int, str], list[str]]:
    """Section types: {"0": "analytical"} / {"Introduction": "descriptive"} / [{"idx": 0, "type": "..."}]."""
    by_title = {s["title"]: s["idx"] for s in sections}
    valid = {s["idx"] for s in sections}
    out: dict[int, str] = {}
    warns: list[str] = []
    for f, data in read_json_files(paths):
        pairs = []
        if isinstance(data, list):
            pairs = [(it.get("idx", it.get("title")), it.get("type")) for it in data if isinstance(it, dict)]
        elif isinstance(data, dict):
            pairs = list(data.items())
        for key, val in pairs:
            t = _norm(_SEC_ALIAS, val)
            idx = int(key) if str(key).isdigit() else by_title.get(str(key))
            if t is None or idx is None or idx not in valid:
                warns.append(f"{f.name}: unrecognized section label {key!r}: {val!r}")
                continue
            out[idx] = t
    return out, warns


# ----------------------------------------------------------------------------- formulas
def parse_weights(s: str) -> tuple[float, float, float]:
    w = tuple(float(x) for x in s.split(","))
    if len(w) != 3 or min(w) < 0 or sum(w) == 0:
        raise ValueError("--weights needs three non-negative numbers, e.g. 1,1,1")
    return w  # type: ignore[return-value]


def composite(sc: dict, weights: tuple[float, float, float] = (1, 1, 1)) -> float:
    """S = (a*depth + b*breadth + g*height) / (a+b+g): the weighted sum of Eq. (1), divided by the weight total to stay on 1-5."""
    a, b, g = weights
    return (a * sc["depth"] + b * sc["breadth"] + g * sc["height"]) / (a + b + g)


def level_of(x: float, low: float = 2.5, high: float = 3.5) -> str:
    return "low" if x < low else "high" if x >= high else "medium"


def dominant(sc: dict) -> str:
    """Most prominent dimension: all scores <= 2 -> none; tie for the top score -> mixed; otherwise the top dimension."""
    top = max(sc[d] for d in DIMS)
    if top <= 2:
        return "none"
    best = [d for d in DIMS if sc[d] == top]
    return best[0] if len(best) == 1 else "mixed"


def describe(values: list[float]) -> dict:
    if not values:
        return {"n": 0, "mean": None, "median": None, "std": None, "min": None, "max": None}
    return {"n": len(values), "mean": round(mean(values), 3), "median": round(median(values), 3),
            "std": round(stdev(values), 3) if len(values) > 1 else 0.0, "min": min(values), "max": max(values)}
