#!/usr/bin/env python3
"""Render one evidence-ledger figure to a PNG. A sibling tool to aminer_open.py.

Called directly by the host (never spawned by evidence.py, which stays a pure
offline ledger). It reads a figure's `data` / `chart_type` / `code_path` from
the ledger, renders a PNG, and prints a JSON result the host records back with
`evidence.py figure mark-rendered`.

Two render paths, sharing one source of truth — the figure's registered `data`:

- **A — template** (deterministic, no LLM, no arbitrary code): a fixed
  matplotlib template per `chart_type` (bar / hbar / line / pie / heatmap).
  This is the fallback and the only path when no `code_path` is set.
- **B — script** (the host-written `.py` at `code_path`): run sandboxed. The
  script reads `data` on stdin and writes the PNG to the path in `$CHART_OUT`.
  On crash / timeout / forbidden-token / missing output it falls back to A.

Strategy:
- `auto` (default): B if `code_path` is set, else A; B failure falls back to A.
- `script`: force B; failure is an error (no fallback).
- `template` (or `--fallback`): force A.

The sandbox is best-effort, not a hard boundary — a true jail (e2b/seccomp) is
out of scope for a local stdlib-adjacent tool. What it does do: scrub the env of
proxy/key vars, lock cwd to the figures dir, set a timeout, pass data via stdin
(not as code), and refuse to run a script containing forbidden tokens
(`os.system`, `subprocess`, `socket`, `urllib`, `requests`, `shutil`, `eval`,
`exec`, `__import__`). The figure's numbers still come from the ledger, so even
a misbehaving B script cannot fabricate data — `check` verifies the registered
`data` against its sources regardless of which path rendered it.

    python3 "${CLAUDE_SKILL_DIR}/scripts/chartrender.py" \
      --ledger "$DR_LEDGER" --id f1 --out figures/f1.png
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any


FIGURE_TYPES = ("bar", "hbar", "line", "pie", "heatmap", "timeline")

# A curated, harmonious palette — not matplotlib's default cycle. Distinct
# enough to separate adjacent bars/series, muted enough to read as a report,
# not a slideshow. Cycled for any number of categories/series.
PALETTE = [
    "#2E86AB", "#A23B72", "#F18F01", "#3B8B8B", "#6A4C93",
    "#1982C4", "#8AC926", "#FFCA3A", "#FF595E", "#6A994E",
    "#BC4749", "#386641", "#9C6644", "#B5838D", "#5B6CFF",
]

# Greys for chrome (spines, ticks, grid, secondary text).
_INK = "#222222"
_SOFT = "#888888"
_GRID = "#E4E4E4"


def _style_axes(ax, *, grid_axis: str = "y") -> None:
    """Report-style axes: drop top/right spines, mute the rest, add light grid."""
    for sp in ("top", "right"):
        ax.spines[sp].set_visible(False)
    for sp in ("left", "bottom"):
        ax.spines[sp].set_color(_SOFT)
        ax.spines[sp].set_linewidth(0.8)
    ax.tick_params(colors=_INK, labelsize=9, length=3)
    ax.grid(axis=grid_axis, color=_GRID, linewidth=0.8, zorder=0)
    ax.set_axisbelow(True)


def _title(ax, title: str) -> None:
    ax.set_title(title, fontsize=14, color=_INK, pad=12, loc="left", weight="bold")


# Tokens a B script must not contain. A static scan, not a real sandbox — it
# catches the obvious "phone home / shell out / wipe disk" moves, which is all
# a local tool can honestly promise without an external jail. The figure data
# is still ledger-verified, so the worst a slipped-through script can do is
# render the wrong picture (and `check`'s data↔source gate still holds).
FORBIDDEN_TOKENS = (
    "os.system", "subprocess", "socket", "urllib", "requests",
    "shutil", "eval(", "exec(", "__import__", "pty", "ctypes",
)

SCRIPT_TIMEOUT_SEC = 30


class RenderError(ValueError):
    """User-facing render error."""


# --------------------------------------------------------------------------- ledger


def _load_figures(ledger_path: Path) -> dict[str, dict[str, Any]]:
    if not ledger_path.exists():
        raise RenderError(f"Ledger not found: {ledger_path}")
    try:
        state = json.loads(ledger_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RenderError(f"Ledger is not valid JSON: {exc.msg}") from None
    figures = state.get("figures") or []
    by_id = {f["id"]: f for f in figures if isinstance(f, dict) and f.get("id")}
    return by_id


# --------------------------------------------------------------------------- A: templates


def _import_pyplot():
    """Import matplotlib lazily and force the headless Agg backend.

    Done inside a function so a missing matplotlib degrades this one tool, not
    every ledger command: evidence.py never imports this module, so a bare
    `python3 evidence.py check` works on a box without matplotlib.
    """
    try:
        import matplotlib
        matplotlib.use("Agg")  # no display; must precede pyplot import
        import matplotlib.pyplot as plt
    except ImportError as exc:
        raise RenderError(
            "matplotlib is not installed; install it (pip install matplotlib) "
            "or render figures on a machine that has it. The ledger still "
            "tracks the figure — record it with `evidence.py figure mark-rendered` "
            "once rendered elsewhere."
        ) from None
    # A CJK-capable font first, else non-ASCII labels render as tofu. SimHei/
    # Microsoft YaHei cover Linux/Windows; PingFang SC / Heiti SC / STHeiti
    # cover macOS; Arial Unicode MS is the old Office fallback. DejaVu Sans is
    # the last resort (Latin only). matplotlib picks the first installed.
    plt.rcParams["font.sans-serif"] = [
        "SimHei", "Microsoft YaHei", "PingFang SC", "Heiti SC", "STHeiti",
        "Arial Unicode MS", "DejaVu Sans",
    ]
    plt.rcParams["axes.unicode_minus"] = False
    return plt


def _label_value(ax, bar, v: float, horizontal: bool) -> None:
    """Place a value label just past the end of a bar."""
    s = f"{v:g}"
    if horizontal:
        ax.text(v, bar.get_y() + bar.get_height() / 2, " " + s,
                ha="left", va="center", fontsize=8.5, color=_INK)
    else:
        ax.text(bar.get_x() + bar.get_width() / 2, v, s,
                ha="center", va="bottom", fontsize=8.5, color=_INK)


def _barish(plt, data: Any, horizontal: bool, title: str, out: Path) -> None:
    import numpy as np

    grouped = isinstance(data, dict) and isinstance(data.get("items"), list)
    if grouped:
        # data = {"series": [name, ...], "items": [{"label", "values": [...]}]}
        series = [str(s) for s in (data.get("series") or [])]
        items = data["items"]
        labels = [str(it.get("label", "")) for it in items]
        rows = [[float(v) for v in it.get("values", [])] for it in items]
        ngroups = len(labels)
        nseries = max((len(r) for r in rows), default=0)
        nseries = max(nseries, len(series), 1)
        fig, ax = plt.subplots(figsize=(max(6.4, ngroups * 1.7), 4.8))
        x = np.arange(ngroups)
        w = 0.78 / nseries
        for s in range(nseries):
            vals = [r[s] if s < len(r) else 0.0 for r in rows]
            offs = (s - (nseries - 1) / 2.0) * w
            bars = ax.bar(x + offs, vals, w,
                          label=series[s] if s < len(series) else f"系列{s + 1}",
                          color=PALETTE[s % len(PALETTE)], zorder=3,
                          edgecolor="white", linewidth=0.6)
            for b, v in zip(bars, vals):
                _label_value(ax, b, v, horizontal=False)
        ax.set_xticks(x)
        ax.set_xticklabels(labels)
        ax.tick_params(axis="x", labelrotation=0)
        ymax = max((v for r in rows for v in r), default=1.0)
        ax.set_ylim(0, ymax * 1.18)
        _style_axes(ax, grid_axis="y")
        ax.legend(frameon=False, fontsize=9, loc="best")
    else:
        labels = [str(d.get("label", "")) for d in data]
        values = [float(d.get("value", 0)) for d in data]
        n = len(labels)
        fig, ax = plt.subplots(figsize=(max(6.4, n * (1.05 if horizontal else 0.95)), 4.8))
        colors = [PALETTE[i % len(PALETTE)] for i in range(n)]
        if horizontal:
            bars = ax.barh(labels, values, color=colors, zorder=3,
                            edgecolor="white", linewidth=0.6)
            ax.invert_yaxis()
            for b, v in zip(bars, values):
                _label_value(ax, b, v, horizontal=True)
            _style_axes(ax, grid_axis="x")
            xmax = max(values) if values else 1
            ax.set_xlim(0, xmax * 1.16)
        else:
            bars = ax.bar(labels, values, color=colors, zorder=3,
                           edgecolor="white", linewidth=0.6)
            ax.tick_params(axis="x", labelrotation=30 if n > 4 else 0)
            for b, v in zip(bars, values):
                _label_value(ax, b, v, horizontal=False)
            _style_axes(ax, grid_axis="y")
            ymax = max(values) if values else 1
            ax.set_ylim(0, ymax * 1.16)
    _title(ax, title)
    fig.tight_layout()
    fig.savefig(out, dpi=200, bbox_inches="tight")
    plt.close(fig)


def _line(plt, data: Any, title: str, out: Path) -> None:
    # data is one series {"series": name, "points": [{"x","y"}]} OR a list of them.
    series_list = data if isinstance(data, list) else [data]
    fig, ax = plt.subplots(figsize=(7.2, 4.6))
    for idx, s in enumerate(series_list):
        points = s.get("points", []) if isinstance(s, dict) else []
        xs = [p.get("x") for p in points]
        ys = [float(p.get("y", 0)) for p in points]
        name = str(s.get("series", "")) if isinstance(s, dict) else ""
        ax.plot(xs, ys, marker="o", linewidth=2.0, markersize=6,
                color=PALETTE[idx % len(PALETTE)],
                markeredgecolor="white", markeredgewidth=1.0, label=name)
    _style_axes(ax, grid_axis="y")
    _title(ax, title)
    if any(isinstance(s, dict) and s.get("series") for s in series_list):
        ax.legend(frameon=False, fontsize=9)
    fig.tight_layout()
    fig.savefig(out, dpi=200, bbox_inches="tight")
    plt.close(fig)


def _pie(plt, data: list[dict[str, Any]], title: str, out: Path) -> None:
    labels = [str(d.get("label", "")) for d in data]
    values = [float(d.get("value", 0)) for d in data]
    colors = [PALETTE[i % len(PALETTE)] for i in range(len(values))]
    fig, ax = plt.subplots(figsize=(6.4, 5.0))
    wedges, _texts, autotexts = ax.pie(
        values, labels=labels, autopct="%1.1f%%", startangle=90,
        colors=colors, wedgeprops=dict(edgecolor="white", linewidth=1.4),
        textprops=dict(fontsize=9, color=_INK),
    )
    for at in autotexts:
        at.set_color("white")
        at.set_fontsize(8.5)
        at.set_weight("bold")
    _title(ax, title)
    ax.axis("equal")
    fig.tight_layout()
    fig.savefig(out, dpi=200, bbox_inches="tight")
    plt.close(fig)


def _heatmap(plt, data: dict[str, Any], title: str, out: Path) -> None:
    rows = [str(r) for r in data.get("rows", [])]
    cols = [str(c) for c in data.get("cols", [])]
    cells = data.get("cells", [])
    fig, ax = plt.subplots(figsize=(max(6, len(cols) * 0.8), max(4, len(rows) * 0.6)))
    im = ax.imshow(cells, aspect="auto", cmap="viridis")
    if cols:
        ax.set_xticks(range(len(cols)))
        ax.set_xticklabels(cols, rotation=30, ha="right")
    if rows:
        ax.set_yticks(range(len(rows)))
        ax.set_yticklabels(rows)
    _title(ax, title)
    fig.colorbar(im, ax=ax)
    fig.tight_layout()
    fig.savefig(out, dpi=200, bbox_inches="tight")
    plt.close(fig)


def _timeline(plt, data: list[dict[str, Any]], title: str, out: Path) -> None:
    """A horizontal timeline of dated events, grouped into rows by `group`.

    The structural figure for an industry report whose evidence is rich in
    entities and dates but thin on market-share percentages: model releases,
    funding rounds, policy milestones. `date` is a 4-digit year or `YYYY-MM`;
    years are skipped by the ledger's number-provenance check, and small counts
    are too, so this figure type leans on dates and labels rather than stats
    the ledger must source — though any 3-plus-digit figure inside an event
    label is still checked the same as in prose. Each `group` becomes its own
    row, coloured from the palette so the reader can tell model releases from
    regulations at a glance.
    """
    import math

    if not isinstance(data, list) or not data:
        raise RenderError("timeline needs a non-empty list of {date,event[,group]}")

    def to_year(d: Any) -> float:
        s = str(d).strip()
        if not s:
            raise RenderError("timeline: an event is missing its date")
        if "-" in s:
            parts = s.split("-")
            try:
                y, m = int(parts[0]), int(parts[1])
            except ValueError as exc:
                raise RenderError(f"timeline: unparseable date '{d}'") from exc
            return float(y) + (m - 1) / 12.0
        try:
            return float(s)
        except ValueError as exc:
            raise RenderError(f"timeline: unparseable date '{d}'") from exc

    rows: dict[str, list[tuple[float, str]]] = {}
    for ev in data:
        if not isinstance(ev, dict):
            raise RenderError("timeline: each event must be an object")
        group = str(ev.get("group") or "").strip() or "事件"
        rows.setdefault(group, []).append((to_year(ev.get("date")), str(ev.get("event", ""))))

    groups = list(rows.keys())
    ng = len(groups)
    fig_h = max(3.4, ng * 1.7 + 0.6)
    fig, ax = plt.subplots(figsize=(max(9.0, len(data) * 0.9), fig_h))

    all_years = [yr for items in rows.values() for yr, _ in items]
    xmin, xmax = min(all_years) - 0.3, max(all_years) + 0.3
    ax.set_xlim(xmin, xmax)
    y0, y1 = int(math.floor(xmin)), int(math.ceil(xmax))
    ax.set_xticks([float(t) for t in range(y0, y1 + 1)])
    ax.set_xticklabels([str(t) for t in range(y0, y1 + 1)], fontsize=9)

    for gi, group in enumerate(groups):
        items = sorted(rows[group], key=lambda it: it[0])
        y = gi
        ax.hlines(y, xmin, xmax, color=_GRID, linewidth=1.0, zorder=1)
        color = PALETTE[gi % len(PALETTE)]
        for i, (yr, event) in enumerate(items):
            ax.plot(yr, y, "o", color=color, markersize=10, zorder=4,
                    markeredgecolor="white", markeredgewidth=1.3)
            above = (i % 2 == 0)
            ax.annotate(
                event, (yr, y),
                xytext=(0, 13 if above else -13),
                textcoords="offset points", fontsize=8.2, color=_INK,
                ha="center", va="bottom" if above else "top",
                bbox=dict(boxstyle="round,pad=0.28", fc="white",
                          ec=color, lw=0.8, alpha=0.96),
            )

    ax.set_yticks(range(ng))
    ax.set_yticklabels(groups, fontsize=9.5, color=_INK)
    for sp in ("top", "right", "left"):
        ax.spines[sp].set_visible(False)
    ax.spines["bottom"].set_color(_SOFT)
    ax.tick_params(axis="x", colors=_INK, length=3)
    ax.tick_params(axis="y", length=0)
    ax.grid(axis="x", color=_GRID, linewidth=0.8, zorder=0)
    ax.set_axisbelow(True)
    _title(ax, title)
    fig.tight_layout()
    fig.savefig(out, dpi=200, bbox_inches="tight")
    plt.close(fig)


def render_template(chart_type: str, data: Any, title: str, out: Path) -> None:
    plt = _import_pyplot()
    if chart_type in ("bar", "hbar"):
        grouped = isinstance(data, dict) and isinstance(data.get("items"), list)
        if not isinstance(data, list) and not grouped:
            raise RenderError(
                f"{chart_type} needs a list of {{label,value}} or a grouped "
                f"{{series, items:[{{label, values}}]}}")
        _barish(plt, data, horizontal=(chart_type == "hbar"), title=title, out=out)
    elif chart_type == "line":
        _line(plt, data, title=title, out=out)
    elif chart_type == "pie":
        if not isinstance(data, list):
            raise RenderError("pie needs a list of {label,value}")
        _pie(plt, data, title=title, out=out)
    elif chart_type == "heatmap":
        if not isinstance(data, dict):
            raise RenderError("heatmap needs {rows,cols,cells}")
        _heatmap(plt, data, title=title, out=out)
    elif chart_type == "timeline":
        if not isinstance(data, list):
            raise RenderError("timeline needs a list of {date,event[,group]}")
        _timeline(plt, data, title=title, out=out)
    else:
        raise RenderError(
            f"No template for chart_type '{chart_type}'. Supported: "
            f"{', '.join(FIGURE_TYPES)}. For other chart shapes, supply a B script."
        )


# --------------------------------------------------------------------------- B: script


def _forbidden_in(script_text: str) -> list[str]:
    """Static scan for tokens a local best-effort sandbox refuses to run."""
    return [tok for tok in FORBIDDEN_TOKENS if tok in script_text]


def _scrub_env(env: dict[str, str]) -> dict[str, str]:
    """Drop anything that looks like a credential or proxy, so a B script
    cannot phone home even if it slips past the token scan."""
    return {k: v for k, v in env.items()
            if not re.search(r"(KEY|TOKEN|SECRET|PASS|PROXY|AUTH)", k, re.IGNORECASE)}


def render_script(code_path: Path, data: Any, title: str, out: Path, cwd: Path) -> None:
    """Run the host-written chart script in a best-effort sandbox.

    Contract the script must follow: read the figure `data` as JSON on stdin,
    write the PNG to the path in `$CHART_OUT` (title in `$CHART_TITLE`), exit 0.
    """
    if not code_path.exists():
        raise RenderError(f"B script not found: {code_path}")
    script_text = code_path.read_text(encoding="utf-8")
    forbidden = _forbidden_in(script_text)
    if forbidden:
        raise RenderError(
            f"B script contains forbidden token(s): {', '.join(forbidden)}. "
            f"A local sandbox cannot safely run this; fall back to the template."
        )
    out.parent.mkdir(parents=True, exist_ok=True)
    env = _scrub_env(dict(os.environ))
    # Absolute paths: the subprocess cwd is locked to the figures dir, so a
    # relative CHART_OUT would resolve under that cwd and miss. Resolve both.
    env["CHART_OUT"] = str(out.resolve())
    env["CHART_TITLE"] = title
    try:
        subprocess.run(
            [sys.executable, str(code_path)],
            input=json.dumps(data, ensure_ascii=False),
            cwd=str(cwd.resolve()),
            env=env,
            timeout=SCRIPT_TIMEOUT_SEC,
            capture_output=True,
            text=True,
            check=True,
        )
    except subprocess.TimeoutExpired as exc:
        raise RenderError(f"B script timed out after {SCRIPT_TIMEOUT_SEC}s") from exc
    except subprocess.CalledProcessError as exc:
        stderr = (exc.stderr or "").strip().splitlines()
        tail = stderr[-3:] if stderr else ["(no stderr)"]
        raise RenderError(f"B script failed (exit {exc.returncode}): {' | '.join(tail)}") from exc
    if not out.exists():
        raise RenderError(f"B script exited 0 but wrote no PNG to {out}")


# --------------------------------------------------------------------------- driver


def render_figure(figure: dict[str, Any], out: Path, strategy: str, cwd: Path) -> dict[str, Any]:
    chart_type = str(figure.get("chart_type") or "")
    data = figure.get("data")
    title = str(figure.get("title") or figure.get("id") or "figure")
    code_path = figure.get("code_path")
    code_path = Path(code_path) if code_path else None

    use_script = strategy == "script" or (strategy == "auto" and code_path is not None)
    if strategy == "script" and code_path is None:
        raise RenderError("strategy=script but the figure has no code_path")

    fallback_reason: str | None = None
    rendered_by = "template"

    if use_script and code_path is not None:
        try:
            render_script(code_path, data, title, out, cwd)
            rendered_by = "script"
        except RenderError as exc:
            if strategy == "script":
                raise  # forced B: failure is fatal, no fallback
            fallback_reason = str(exc)
            render_template(chart_type, data, title, out)
            rendered_by = "template"
    else:
        render_template(chart_type, data, title, out)

    return {
        "ok": True,
        "id": figure.get("id"),
        "path": out.as_posix(),
        "rendered_by": rendered_by,
        "strategy": strategy,
        "fallback_reason": fallback_reason,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Render one evidence-ledger figure to PNG")
    parser.add_argument("--ledger", required=True, help="Path to evidence-ledger.json")
    parser.add_argument("--id", required=True, help="Figure id (e.g. f1)")
    parser.add_argument("--out", required=True, help="Output PNG path")
    parser.add_argument("--strategy", choices=("auto", "script", "template"), default="auto",
                        help="auto (default): B then fallback A; script: force B; template: force A")
    parser.add_argument("--fallback", action="store_true",
                        help="Shorthand for --strategy template")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    strategy = "template" if args.fallback else args.strategy
    try:
        figures = _load_figures(Path(args.ledger))
        figure = figures.get(args.id)
        if figure is None:
            raise RenderError(f"Unknown figure id '{args.id}'. Known: {', '.join(figures) or 'none'}")
        out = Path(args.out)
        # Lock B scripts into the --out directory (where the PNG lands), so a
        # script cannot reach for the repo root. The skill assumes no figures
        # path; the caller's --out decides the working directory.
        cwd = out.parent
        cwd.mkdir(parents=True, exist_ok=True)
        result = render_figure(figure, out, strategy, cwd)
    except RenderError as exc:
        print(json.dumps({"ok": False, "error": "render_failed", "message": str(exc)},
                         ensure_ascii=False, indent=2))
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
