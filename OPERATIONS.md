# Fed Monitor — Operations Reference

The durable, machine-independent record of how the automated pipeline runs.
Methodology lives in `CLAUDE.md`; this file documents the *infrastructure*
(schedules, triggers, workflows, maintenance). Last updated: 2026-06-11.

The cloud "routines" (CCR triggers) are NOT stored in this repo — they live in
claude.ai and are managed via the RemoteTrigger API / the `/schedule` skill.
This file is the canonical inventory of them, since they are otherwise invisible
in the codebase. Manage/view at https://claude.ai/code/routines.

---

## Daily pipeline (morning, reports on the PRIOR day)

All times ET. The pipeline runs as a morning batch covering the previous day:

| Time (ET) | Component | Type | What it does |
|---|---|---|---|
| 5:30am | `.github/workflows/collect.yml` | GitHub Action (cron `30 9 * * *`) | Scrape all sources → commit `data/raw/` → push. Blackout-aware (reads `blackout_periods.json`). |
| 6:30am | **Daily score routine** `trig_01DadwAUENFGnxmNCNJSG6Af` | CCR (cron `30 10 * * *`) | Score new speeches, write the daily report dated for **yesterday (ET)**, push. Branches on blackout / FOMC-day (see below). |
| on push | `.github/workflows/email.yml` | GitHub Action (push → `data/reports/daily/`) | SMTP-emails the daily report (matches **yesterday-ET** date). |
| 7:30am | `com.fedmonitor.sync` | local launchd (`~/Library/LaunchAgents/`) | `git pull` → syncs to Google Drive. |

**Report dating:** the report is dated for the prior day (REPORT_DATE = yesterday ET),
since the run happens the morning after. Scored-speech filenames use the speech's own date.

**UPCOMING section** (keyed to the SEND/run-day weekday): Monday → current week
(Mon–Fri); Friday → next week; Tue–Thu + weekends → next calendar day. Routine has
web access to read the Fed Board calendar + regional event pages.

**Blackout-entry cycle summary:** on the Saturday that STARTS a blackout (run day ==
a `start` date in `blackout_periods.json`), the report MUST include an `FOMC CYCLE
SUMMARY — ENTERING <meeting>` section (last report before the blackout silence).

---

## FOMC decision-day fast path

The statement + Chair press conference land on the meeting's day 2 (a Wednesday),
INSIDE blackout. Handled by three pieces:

| Time (ET) | Component | Type | What it does |
|---|---|---|---|
| 2:05pm Wed | **FOMC statement alert** `trig_011raxPgWfnTqPWhGGT5ZsvG` | CCR (cron `5 18 * * 3`) | Self-checks decision day; statement diff (Type C) → `data/reports/fomc/` → push. **On a projection meeting, also pull the SEP / dot plot and write the Type I diff (see below).** |
| 2:05pm Wed (projection meetings only) | **SEP / dot plot (Type I)** | CCR (same run as the statement alert) | Fires only when the meeting has `"sep": true` in `blackout_periods.json` (SEP is released **every other meeting** — 4 of 8/yr). Pull the projection table (`fomcprojtabl<date>.htm`) + dot distribution, diff vs. the PRIOR SEP (two meetings back), evaluate against inter-meeting speeches → `data/scored/sep/` + `data/reports/fomc/` → push (emailed). |
| 5:00pm Wed | **FOMC press-conf alert** `trig_01CnKcJgS7KJQ5bXjqe3akh7` | CCR (cron `0 21 * * 3`) | Self-checks decision day; PROVISIONAL press conf (Type E) from YouTube auto-caption → push. |
| next 6:30am | Daily score routine (FOMC-day branch) | CCR | Detects REPORT_DATE = decision day (doesn't skip despite blackout); writes CANONICAL report from the OFFICIAL transcript, finalizing/correcting the provisional alert. **Folds in the SEP section on projection meetings.** |
| on push | `.github/workflows/fomc_email.yml` | GitHub Action (push → `data/reports/fomc/` or `data/reports/beige_book/`) | SMTP-emails each pushed alert immediately. |

Decision day = 2nd date of each `meeting` in `blackout_periods.json` (always a Wednesday).
The two alert triggers fire every Wednesday and self-check; they no-op on non-meeting Wednesdays.
The SEP fires only on **projection meetings** — flagged `"sep": true` in
`blackout_periods.json` (released every other meeting, 4 of 8/yr). The prior-SEP
comparison is always two meetings back (June diffs vs. March, not the intervening April).
Projection-table URL pattern: `https://www.federalreserve.gov/monetarypolicy/fomcprojtabl<YYYYMMDD>.htm`.

---

## Beige Book (Type H)

| Time (ET) | Component | Type | What it does |
|---|---|---|---|
| 2:15pm weekdays | **Beige Book** `trig_0174dZXe1XkG11Dd2UNMkYr5` | CCR (cron `15 18 * * 1-5`) | Self-checks `beige_book_dates.json`; on a release day, national-summary diff vs prior (Type H) → `data/reports/beige_book/` → push → emailed via `fomc_email.yml`. |

Release weekday VARIES (e.g. 2026-01-14 was a Tuesday) — dates are explicit in
`beige_book_dates.json`, never assumed.

---

## Single sources of truth (repo data files)

- `blackout_periods.json` — FOMC blackout windows + meeting dates. Source: the official
  Fed blackout PDF (`_source` field). Read by collect.yml + the score routine.
- `beige_book_dates.json` — Beige Book release dates. Source: the Fed Beige Book page.
- **Do not hardcode any of these dates anywhere else.**

---

## Email

- All email is sent by **GitHub Actions via Gmail SMTP** (`email.yml`, `fomc_email.yml`),
  using the `GMAIL_APP_PASSWORD` repo secret. From `revilresearch@gmail.com` → To
  `thiago_teixeiraferreira@vanguard.com`.
- **Verification:** sends are confirmable via the claude.ai **Gmail connector** (it's on
  the sender account — search `SENT`); workflow runs/failures via **`gh`** (installed at
  `~/.local/bin/gh`, authenticated as `revilth`): `gh run list`, `gh run view <id> --log`.

---

## DST maintenance (TWICE A YEAR)

All CCR/Action crons are in UTC and must shift to hold their ET times:
**Nov 1, 2026 (EDT→EST): +1h.  Mar 8, 2027 (EST→EDT): −1h.**

| Cron | EDT (now) | EST (after Nov 1) |
|---|---|---|
| collect.yml | `30 9 * * *` | `30 10 * * *` |
| score routine | `30 10 * * *` | `30 11 * * *` |
| FOMC statement | `5 18 * * 3` | `5 19 * * 3` |
| FOMC press conf | `0 21 * * 3` | `0 22 * * 3` |
| Beige Book | `15 18 * * 1-5` | `15 19 * * 1-5` |

A one-time reminder is scheduled: `trig_01KM4ycwQB3ahW3AUfvuzUom` (fires Fri Oct 30, 2026,
emails this checklist). The local `com.fedmonitor.sync` job uses wall-clock local time, so
it auto-adjusts — no change needed there.

---

## Annual maintenance (each January)

1. Refresh `blackout_periods.json` from the official Fed blackout PDF (add the new year).
2. Refresh `beige_book_dates.json` from the Fed Beige Book schedule page.
3. Update the 2026→2027 voter list and the reference FOMC date in `CLAUDE.md`.
4. Confirm the DST cron values match the season.
