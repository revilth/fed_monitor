#!/usr/bin/env python3
"""
Build a machine-readable SEP / dot-plot dataset from the raw text files that
collect_sep_historical.py writes to data/raw/sep/.

Outputs (data/raw/sep/dataset/):
  sep_table1.csv      one row per (meeting, variable, horizon): median (where
                      published, Sept 2015 →), central tendency low/high,
                      range low/high.  Oct 2007 → present.
  sep_dots_long.csv   one row per (meeting, horizon, rate level): number of
                      participants at that level.  Jan 2012 → present (the dot
                      plot did not exist before 2012).
  sep_dots_summary.csv one row per (meeting, horizon): n, median, mean, min,
                      max, and the modal rate — computed from the histogram.

Source precedence for Table 1: the projection-materials page (2012 →, has the
Median column from Sept 2015), falling back to the SEP addendum to the minutes
(2007 →). The addendum's Table 1 for 2007–2011 reports central tendencies and
ranges only ("2.4 to 2.5", quarter-point fractions like "2-1/4").

Run: python3 scripts/build_sep_dataset.py
"""
from __future__ import annotations

import csv
import re
import statistics
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
RAW = BASE / "data/raw/sep"
OUT = RAW / "dataset"

VAR_MAP = [
    (re.compile(r"^(change in )?real gdp( growth)?", re.I), "real_gdp"),
    (re.compile(r"^unemployment rate", re.I), "unemployment"),
    (re.compile(r"^core pce inflation", re.I), "core_pce"),
    (re.compile(r"^pce inflation", re.I), "pce"),
    (re.compile(r"^federal funds rate", re.I), "fed_funds"),
]
PRIOR_ROW = re.compile(r"^(january|march|april|june|september|october|november|december)\s+projections?$", re.I)
DASH = "–—-"


def tables(text: str):
    """Yield (title, rows) for every [TABLE] block; rows are lists of cells."""
    for m in re.finditer(r"\[TABLE\]([^\n]*)\n(.*?)\[/TABLE\]", text, re.S):
        body = m.group(2).replace("\xa0", " ")
        rows = [[c.strip() for c in ln.split("|")] for ln in body.splitlines() if ln.strip()]
        yield m.group(1).strip(), rows


def frac(s: str) -> float | None:
    """'2-1/4' → 2.25, '2.4' → 2.4, '(0.5)' → -0.5, '3/4' → 0.75."""
    s = s.strip().replace("½", "-1/2").replace("¼", "-1/4").replace("¾", "-3/4")
    neg = s.startswith("(") and s.endswith(")")
    s = s.strip("()")
    m = re.fullmatch(r"(-?\d+)(?:-(\d)/(\d))?", s)
    if m:
        v = float(m.group(1))
        if m.group(2):
            v += float(m.group(2)) / float(m.group(3))
        return -v if neg else v
    m = re.fullmatch(r"(\d)/(\d)", s)
    if m:
        return float(m.group(1)) / float(m.group(2))
    try:
        v = float(s)
        return -v if neg else v
    except ValueError:
        return None


def parse_range(cell: str):
    """'2.2–2.4' / '2.2 to 2.4' / 'about 4-3/4' / '2.0' → (low, high)."""
    c = cell.strip()
    if not c or c.lower() in {"-", "n.a.", "n/a", "na"}:
        return None, None
    c = re.sub(r"^about\s+", "", c, flags=re.I)
    if re.search(r"\sto\s", c):
        parts = re.split(r"\s+to\s+", c)
    elif re.search(r"[\u2013\u2014]", c):
        parts = re.split(r"\s*[\u2013\u2014]\s*", c)
    else:
        # plain hyphen: a separator only between two decimals ("2.2-2.4"),
        # never inside a quarter-point fraction ("2-1/4")
        if "/" in c:
            parts = [c]  # a single quarter-point fraction such as "2-1/4"
        else:
            parts = re.split(r"(?<=\d)\s*-\s*(?=\d)", c)
    parts = [p for p in parts if p]
    if len(parts) == 1:
        v = frac(parts[0])
        return v, v
    lo, hi = frac(parts[0]), frac(parts[1])
    return lo, hi


def horizon_label(h: str) -> str:
    h = h.strip()
    if re.match(r"longer[\s-]*run", h, re.I):
        return "longer_run"
    m = re.search(r"(20\d\d)", h)
    return m.group(1) if m else h


# ── Table 1 ────────────────────────────────────────────────────────────────────
def parse_table1_modern(rows):
    """Projection-materials / post-2011 addendum layout.

    Header row 1: Variable | Median | Central Tendency | Range   (Median optional)
    Header row 2: 2026 | 2027 | ... | Longer run | (repeated per block)
    """
    if len(rows) < 3:
        return None
    h1 = [c.lower() for c in rows[0]]
    blocks = []
    for name in ("median", "central tendency", "range"):
        if any(x.startswith(name) for x in h1):
            blocks.append(name)
    if not blocks:
        return None
    hz = [horizon_label(c) for c in rows[1] if c and re.search(r"(20\d\d|longer)", c, re.I)]
    per = len(hz) // len(blocks)
    if per == 0 or len(hz) % len(blocks):
        return None
    horizons = hz[:per]
    out = []
    for r in rows[2:]:
        if not r or PRIOR_ROW.match(r[0]) or r[0].lower().startswith("memo"):
            continue
        var = next((v for rx, v in VAR_MAP if rx.match(r[0])), None)
        if not var:
            continue
        cells = r[1:]
        if len(cells) < per * len(blocks):
            cells += [""] * (per * len(blocks) - len(cells))
        for i, h in enumerate(horizons):
            rec = {"variable": var, "horizon": h, "median": None,
                   "ct_low": None, "ct_high": None, "range_low": None, "range_high": None}
            for b, name in enumerate(blocks):
                cell = cells[b * per + i]
                if name == "median":
                    rec["median"] = frac(cell) if cell else None
                elif name == "central tendency":
                    rec["ct_low"], rec["ct_high"] = parse_range(cell)
                else:
                    rec["range_low"], rec["range_high"] = parse_range(cell)
            if any(v is not None for k, v in rec.items() if k not in ("variable", "horizon")):
                out.append(rec)
    return out or None


def parse_table1_legacy(rows):
    """2007–2011 addendum layout: a 'Central Tendencies' block then a 'Ranges'
    block, each with variable rows; header row holds the horizons."""
    if not rows:
        return None
    hz = [horizon_label(c) for c in rows[0][1:] if c]
    if not hz:
        return None
    recs = {}
    block = None
    for r in rows[1:]:
        # block markers sit in the first cell (2007) or, in 2008–2009, in the
        # second cell after an empty label cell
        key = next((c for c in r if c), "").strip().lower().rstrip(":")
        if key.startswith("central tendenc"):
            block = "ct"
            continue
        if key.startswith("range"):
            block = "range"
            continue
        if PRIOR_ROW.match(r[0]) or block is None:
            continue
        var = next((v for rx, v in VAR_MAP if rx.match(r[0])), None)
        if not var:
            continue
        for i, h in enumerate(hz):
            cell = r[1 + i] if 1 + i < len(r) else ""
            lo, hi = parse_range(cell)
            rec = recs.setdefault((var, h), {"variable": var, "horizon": h, "median": None,
                                             "ct_low": None, "ct_high": None,
                                             "range_low": None, "range_high": None})
            if block == "ct":
                rec["ct_low"], rec["ct_high"] = lo, hi
            else:
                rec["range_low"], rec["range_high"] = lo, hi
    return list(recs.values()) or None


def parse_table1(text):
    for title, rows in tables(text):
        if not re.match(r"(table 1|economic projections)", title, re.I) and not (
            rows and rows[0] and rows[0][0].lower() == "variable"
        ):
            continue
        res = parse_table1_modern(rows) or parse_table1_legacy(rows)
        if res:
            return res
    # projtabl pages 2012–2014 carry Table 1 without a caption: try every table
    for title, rows in tables(text):
        res = parse_table1_modern(rows)
        if res:
            return res
    return None


# ── Dot plot ───────────────────────────────────────────────────────────────────
DOT_HEAD = re.compile(r"(target federal funds rate|midpoint of target range|target level)", re.I)


def parse_dots(text):
    for _title, rows in tables(text):
        if not rows or not DOT_HEAD.search(rows[0][0]):
            continue
        horizons = [horizon_label(c) for c in rows[0][1:]]
        out = []
        for r in rows[1:]:
            rate = frac(r[0])
            if rate is None:
                # Dec 2012 layout: quarter-point bins ("0.38 - 0.62") — map the
                # bin to its quarter-point level
                lo, hi = parse_range(r[0])
                if lo is None or hi is None:
                    continue
                rate = round((lo + hi) / 2 * 4) / 4
            if rate is None:
                continue
            for i, h in enumerate(horizons):
                cell = r[1 + i] if 1 + i < len(r) else ""
                if cell.strip().isdigit():
                    out.append({"horizon": h, "rate": rate, "n": int(cell)})
        if out:
            return out
    return None


def summarize_dots(dots):
    by_h = {}
    for d in dots:
        by_h.setdefault(d["horizon"], []).extend([d["rate"]] * d["n"])
    out = []
    for h, vals in by_h.items():
        vals.sort()
        mode = max(set(vals), key=lambda v: (vals.count(v), -v))
        out.append({"horizon": h, "n": len(vals), "median": statistics.median(vals),
                    "mean": round(statistics.fmean(vals), 3), "min": vals[0], "max": vals[-1],
                    "mode": mode})
    return out


# ── Driver ─────────────────────────────────────────────────────────────────────
def main():
    OUT.mkdir(parents=True, exist_ok=True)
    dates = sorted({p.name[:8] for p in RAW.glob("2*_SEP_*.txt")})
    t1_rows, dot_rows, sum_rows = [], [], []
    missing_t1, missing_dots = [], []
    for d in dates:
        proj = RAW / f"{d}_SEP_projections.txt"
        add = RAW / f"{d}_SEP_minutes_addendum.txt"
        t1 = src = None
        for p in (proj, add):
            if p.exists():
                t1 = parse_table1(p.read_text(encoding="utf-8", errors="replace"))
                if t1:
                    src = p.name
                    break
        if t1:
            for r in t1:
                t1_rows.append({"date": d, "source_file": src, **r})
        else:
            missing_t1.append(d)

        figs = RAW / f"{d}_SEP_minutes_addendum_figures.txt"
        dots = None
        for p in (proj, add, figs):
            if p.exists():
                dots = parse_dots(p.read_text(encoding="utf-8", errors="replace"))
                if dots:
                    break
        if dots:
            for r in dots:
                dot_rows.append({"date": d, **r})
            for r in summarize_dots(dots):
                sum_rows.append({"date": d, **r})
        elif d >= "20120125":
            missing_dots.append(d)

    def write(name, rows, fields):
        with open(OUT / name, "w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            w.writerows(rows)

    write("sep_table1.csv", t1_rows,
          ["date", "variable", "horizon", "median", "ct_low", "ct_high", "range_low", "range_high", "source_file"])
    write("sep_dots_long.csv", dot_rows, ["date", "horizon", "rate", "n"])
    write("sep_dots_summary.csv", sum_rows, ["date", "horizon", "n", "median", "mean", "min", "max", "mode"])

    print(f"meetings: {len(dates)}")
    print(f"table1 rows: {len(t1_rows)}  (meetings parsed: {len({r['date'] for r in t1_rows})})")
    print(f"dot rows: {len(dot_rows)}  (meetings parsed: {len({r['date'] for r in dot_rows})})")
    if missing_t1:
        print("TABLE 1 NOT PARSED:", " ".join(missing_t1))
    if missing_dots:
        print("DOTS NOT PARSED:", " ".join(missing_dots))


if __name__ == "__main__":
    main()
