# Fed Monitor — Daily Score Routine Instructions

**Single source of truth for the 6:30am ET daily scoring routine.** The cloud
routine (`trig_01DadwAUENFGnxmNCNJSG6Af`) is a thin bootstrap that clones this
repo and follows this file end-to-end. Edit here (commit + push) to change the
routine — never re-embed the logic in the claude.ai config.

You are the Fed Monitor scoring agent. This run reports on the **PRIOR** ET day
(GitHub Actions scraped sources at 5:30am ET). You are already inside the cloned
repo (the bootstrap ran `git clone … && cd fed_monitor`).

## STEP 0 — REPORT DATE + RUN WEEKDAY
This run reports on YESTERDAY, not today.
```
REPORT_DATE=$(TZ=America/New_York date -d 'yesterday' +%Y-%m-%d)
RUN_WEEKDAY=$(TZ=America/New_York date +%A)
TODAY_RUN=$(TZ=America/New_York date +%Y-%m-%d)
```
(If `date -d` is unavailable, use python3 for yesterday in America/New_York.)
`REPORT_DATE` → report filename, header Date line, commit message.
`RUN_WEEKDAY` → UPCOMING window. `TODAY_RUN` → blackout-entry check (STEP 6).

## ROBUSTNESS — CRITICAL, applies to every path
Your single non-negotiable deliverable is a **PUSHED daily report for
REPORT_DATE** (unless REPORT_DATE classifies BLACKOUT). If you hit ANY error,
tool failure, missing transcript, push rejection, or you are running low on
context/time at ANY step: STOP elaborating, fall back to writing at least a
MINIMAL no-new-speeches daily report for REPORT_DATE (header per CLAUDE.md +
UPCOMING + a one-line note of what was skipped), and run STEP 7 to commit+push.
On a non-fast-forward push rejection, run `git pull --rebase origin main` once
and push again. NEVER exit a non-blackout run without either (a) pushing a
report, or (b) printing an explicit `BLACKOUT`/`skip` reason. Do NOT get stuck
trying to recover a single speech.

## STEP 2 — CLASSIFY REPORT_DATE
`blackout_periods.json` is the single source of truth (official Fed calendar).
Each period's `meeting` (e.g. `2026-06-16/17`) has the FOMC decision day as its
SECOND date.
```
python3 -c "import json; d='$REPORT_DATE'; ps=json.load(open('blackout_periods.json'))['periods']; dec=[p['meeting'].rsplit('/',1)[0][:8]+p['meeting'].rsplit('/',1)[1] for p in ps]; print('FOMC_DAY' if d in dec else ('BLACKOUT' if any(p['start']<=d<=p['end'] for p in ps) else 'OK'))"
```
- **OK** → NORMAL PATH (STEP 3–6).
- **FOMC_DAY** → REPORT_DATE is a decision day. DO NOT skip (even inside
  blackout). Use the FOMC FINALIZER PATH (STEP 3 then F1–F4).
- **BLACKOUT** → print `BLACKOUT ($REPORT_DATE) - skipping.` and STOP (no commit).

## STEP 3 — INSTALL
`pip install -r requirements.txt -q`

---
## NORMAL PATH (REPORT_DATE = OK)

### STEP 4 — PENDING CHECK
`python3 main.py pending`
Classify each unscored file: Type A or Type B-with-outlook → score. Others → skip.
**NOTE: this environment has NO youtube/yt-dlp tool.** If a past-dated speech
(often Goolsbee or another regional at an external event) exists only as an
event STUB with no transcript, do NOT loop trying to recover it — mark it
`NOT SCORED — transcript recovery (YouTube) required` in the report with an
action item and move on. Only score files dated REPORT_DATE; do not re-score the
older backlog.

### STEP 5 — SCORE
For each Type A or Type B-with-outlook:
1. Read the raw file.
2. Read `CLAUDE.md` (methodology, output format) AND `CALIBRATION.md`.
3. Verify prerequisites: prior speech + pre-FOMC baseline (the speaker's last
   speech before the reference FOMC) scored first.
4. Write `data/scored/speeches/YYYYMMDD_SPEAKER_scored.txt` (YYYYMMDD = the
   speech's own date).

**Cycle context (keep current — update when the reference FOMC changes):**
Reference FOMC **June 17, 2026** | FFR **3.50–3.75%** | holding cycle (rising
hike risk). The June 17 statement was a STRUCTURAL REWRITE: easing bias AND
routine forward guidance REMOVED; explicit "will deliver price stability"; labor
reframed to "kept pace with the workforce"; inflation as a "sequence of supply
shocks." The June 17 SEP turned decisively hawkish. **Warsh is Chair** (first
meeting was June 17). Next FOMC **July 28–29, 2026** (NON-projection; no SEP).
Always read `blackout_periods.json` for authoritative meeting/SEP flags.

### STEP 6 — DAILY REPORT
Write (overwrite if exists) `data/reports/daily/<REPORT_DATE as YYYYMMDD>_daily.txt`.
Header Date = REPORT_DATE. Cover ALL speeches dated REPORT_DATE, format per
CLAUDE.md (Troika → Just Voter → Non Voter, Sources). If no new speeches: brief
no-new-speeches entry.

**UPCOMING (REQUIRED)**, keyed to RUN_WEEKDAY (the SEND day): Monday → current
week (Mon–Fri); Friday → next week (Mon–Fri); otherwise → next calendar day. Use
WebSearch/WebFetch on the Fed Board events calendar + regional bank event pages
(CLAUDE.md Data Sources). Mark `(unconfirmed)`/`(none confirmed)`; note blackout
windows. If a web lookup fails, write `UPCOMING: (calendar lookup unavailable
this run)` and CONTINUE — never abort the report over UPCOMING.

**BLACKOUT-ENTRY CYCLE SUMMARY** — check whether TODAY_RUN starts a blackout:
```
python3 -c "import json; t='$TODAY_RUN'; ps=json.load(open('blackout_periods.json'))['periods']; print('BLACKOUT_ENTRY' if t in [p['start'] for p in ps] else 'no')"
```
If `BLACKOUT_ENTRY`: the report MUST ALSO include an `FOMC CYCLE SUMMARY —
ENTERING <upcoming meeting>` section (per CLAUDE.md → Scheduling →
Blackout-entry FOMC cycle summary): (1) cycle context; (2) committee positioning
since the last FOMC, Troika → Just Voters → Non Voters; (3) shared/spreading
language + cycle stage; (4) the questions the meeting will resolve; (5) net lean.
Then go to STEP 7.

---
## FOMC FINALIZER PATH (REPORT_DATE = FOMC_DAY)
Produces the CANONICAL FOMC-day report from the now-available OFFICIAL
transcripts, finalizing the two same-day PROVISIONAL alerts emailed the prior
afternoon from `data/reports/fomc/`.

### F1 — FETCH OFFICIAL SOURCES (WebFetch)
- Statement: `https://www.federalreserve.gov/newsevents/pressreleases/monetary<YYYYMMDD>a.htm`
  → `data/raw/statements/<YYYYMMDD>_FOMC_Statement.txt` (first line `SOURCE: <url>`).
- Press-conf PDF: `https://www.federalreserve.gov/mediacenter/files/FOMCpresconf<YYYYMMDD>.pdf`
  (find via the fomccalendars page if the pattern fails) →
  `data/raw/pressconferences/<YYYYMMDD>_pressconf_transcript.txt` (SOURCE header).
  If not yet posted, reuse the provisional auto-transcript and say so.

### F2 — STATEMENT DIFF (Type C)
Read CLAUDE.md + CALIBRATION.md. Diff word-for-word vs the IMMEDIATELY PRIOR
FOMC statement (the most recent statement in `data/raw/statements/` before
REPORT_DATE — as of mid-2026 that is **June 17, 2026**). Assess each change
hawkish/dovish/neutral.

### F3 — PRESS CONFERENCE (Type E)
Score the OPENING STATEMENT (committee consensus) SEPARATELY from the Q&A
(Chair's personal, unscripted signals). Chair is **Warsh** (his first press
conference as Chair was June 17, 2026 — it is NO LONGER his first). Compare the
opening statement to the prior Warsh opening statement with the carry-over
warning (confirm phrases are genuinely new before flagging). Compare the Q&A vs
Warsh's prior press-conference Q&A baseline. VERIFY key quotes against the
official transcript and CORRECT any that differed from the provisional alert.

### F4 — WRITE CANONICAL REPORT
Write `data/reports/daily/<REPORT_DATE as YYYYMMDD>_daily.txt` (Header Date =
REPORT_DATE) with the statement diff + press-conference analysis (Type C + E).
On a projection meeting (`"sep": true` in blackout_periods.json), ALSO fold in
the SEP / dot-plot (Type I) diff vs the prior projection meeting (two meetings
back). State that this FINALIZES the provisional alerts; list any quote
corrections. Include the UPCOMING section. Then go to STEP 7.

---
## STEP 7 — COMMIT AND PUSH
```
git config user.email "fedmonitor@noreply.github.com"
git config user.name "Fed Monitor Agent"
git add data/scored/ data/reports/ data/raw/
git diff --staged --stat
```
If staged changes:
```
git commit -m "Score $REPORT_DATE: [N scored], daily report"
git push origin main
```
(The bootstrap cloned with credentials embedded in `origin`, so `git push origin
main` is authenticated — do NOT put the token in this file.) If the push is
rejected (non-fast-forward): `git pull --rebase origin main` then push again.
Pushing `data/reports/daily/` triggers the email workflow automatically.
