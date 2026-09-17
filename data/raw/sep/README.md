# SEP / dot-plot archive

Every Summary of Economic Projections release, October 2007 → present, collected
by `collect_sep_historical.py` (re-run it after each projection meeting; existing
files are skipped).

| File | Content | Coverage |
|------|---------|----------|
| `YYYYMMDD_SEP_projections.txt` | Public projection materials (Table 1 medians / central tendencies / ranges, dot-plot histogram, distribution histograms, uncertainty diffusion indexes) as table-aware text | Apr 2011 → (2011 from PDF text; HTML from Jan 2012) |
| `YYYYMMDD_SEP_minutes_addendum.txt` | SEP narrative addendum to the minutes (Table 1 + participants' discussion of the outlook, risks, uncertainty) | Oct 2007 → Sept 2020. From Dec 2020 the same text is embedded in `data/raw/minutes/` |
| `YYYYMMDD_SEP_minutes_addendum_figures.txt` | Accessible figure data companion to the addendum | where published (mostly 2007–2014) |
| `dataset/sep_table1.csv` | One row per meeting × variable × horizon: `median` (published from Sept 2015), `ct_low/ct_high`, `range_low/range_high` | Oct 2007 → |
| `dataset/sep_dots_long.csv` | One row per meeting × horizon × rate level: participants at that level | Jan 2012 → (no dot plot before 2012) |
| `dataset/sep_dots_summary.csv` | One row per meeting × horizon: `n`, `median`, `mean`, `min`, `max`, `mode` computed from the histogram | Jan 2012 → |

Rebuild the CSVs with `python3 scripts/build_sep_dataset.py`.

Not in git (too large, under `data/historical/raw/sep/`, synced via Drive only):
`projtabl/fomcprojtabl*.pdf` — the original releases with the dot-plot figure
(Apr 2011 →); `individual/FOMC*SEPcompilation.pdf|.txt` + `FOMC*SEPkey.pdf` —
each participant's actual submitted projections, released with the five-year-lag
transcripts (Oct 2007 → Dec 2020).

Notes for analysis
- Dots are quarter-point levels through 2015 and 1/8-point midpoints of the
  target range afterwards; Dec 2012 was published as quarter-point bins and is
  mapped to the bin's quarter-point level.
- Table 1 medians are rounded to 0.1; `sep_dots_summary.csv` medians are exact
  (e.g. June 2026: table 3.8, exact 3.75).
- Participant count varies (15 in 2018, 16–19 otherwise); 2020-03 had no SEP.
