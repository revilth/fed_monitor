# Fed Communication Monitor — Agent Instructions

## Purpose

This agent monitors, collects, and analyzes communications from Federal Open Market Committee (FOMC) members to support monetary policy forecasting. Outputs are designed for portfolio managers who need concrete, actionable intelligence — not vague sentiment scores.

The core analytical goal is to forecast what the Fed will do next by tracking how the language and emphasis of individual officials changes over time, identifying coordinated messaging across officials, and detecting which sentences get amplified by financial media.

---

## Immediate Task (on first run)

Download all speeches from FOMC members since January 1 of the current year.

Sources to check in order:
1. Federal Reserve Board website: https://www.federalreserve.gov/newsevents/speeches.htm
2. Individual regional Fed websites (list below)
3. ALFRED (Federal Reserve archival data): https://alfred.stlouisfed.org

Save all raw speech text to Google Drive in the folder structure defined below.

---

## Data Sources

### Primary sources (check in this order)
- **Fed Board speeches**: https://www.federalreserve.gov/newsevents/2026-speeches.htm ← use year-specific URL
- **Fed statements and minutes**: https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm
- **FOMC press conference transcripts**: same URL above
- **Congressional testimony**: https://www.federalreserve.gov/newsevents/testimony.htm

**Important:** The Fed Board website only posts speeches by Board Governors (Powell, Jefferson, Bowman, Waller, Cook, Kugler, Barr, Miran). Regional Fed presidents post exclusively on their own bank's website.

### Regional Fed websites — verified working URLs and scraper status (tested 2026-04)

| Bank | President | URL | Status |
|------|-----------|-----|--------|
| Boston | Susan Collins | https://www.bostonfed.org/news-and-events/speeches.aspx | ✓ Works; speeches are PDFs, auto-extracted |
| New York | John Williams | https://www.newyorkfed.org/newsevents/speeches | ✓ Works; Williams-only via slug prefix "wil"; URL pattern: `/newsevents/speeches/YYYY/wilYYMMDD` |
| Philadelphia | Anna Paulson | https://www.philadelphiafed.org/the-economy/speeches-anna-paulson | ✓ Works; speech links follow `/the-economy/[topic]/YYMMDD-slug` pattern |
| Cleveland | Beth Hammack | https://www.clevelandfed.org/collections/speeches | ⚠ JS-rendered; only 1 speech visible statically |
| Richmond | Thomas Barkin | https://www.richmondfed.org/press_room/speeches | ✓ Works; `div.data__row`; individual URL pattern: `/press_room/speeches/thomas_i_barkin/YYYY/barkin_speech_YYYYMMDD` |
| Atlanta | (interim) | https://www.atlantafed.org/news-and-events/speeches | ⚠ Bostic retired Feb 2026; no new speeches yet; links go to external media |
| Chicago | Austan Goolsbee | https://www.chicagofed.org/utilities/about-us/office-of-the-president/office-of-the-president-speaking | ✓ Works; `div.cyan-publication`; individual URL pattern: `/publications/speeches/YYYY/mon-dd-slug`; speeches often PDFs, auto-extracted |
| St. Louis | Alberto Musalem | https://www.stlouisfed.org/from-the-president/remarks | ⚠ SXA API works but index only through Nov 2024 |
| Minneapolis | Neel Kashkari | https://www.minneapolisfed.org/people/neel-kashkari | ⚠ Links only, no transcripts (panel discussions) |
| Kansas City | Jeff Schmid | https://www.kansascityfed.org/speeches | ⚠ 620KB page; stream required; CDN can be slow |
| Dallas | Lorie Logan | https://www.dallasfed.org/news/speeches/logan | ✓ Works; individual URL pattern: `/news/speeches/logan/YYYY/lklYYMMDD` |
| San Francisco | Mary Daly | https://www.frbsf.org/news-and-media/speeches/mary-c-daly | ✓ Works; `li.wp-block-post` |

### YouTube (for video speeches without transcripts)
Use yt-dlp to extract auto-generated transcripts. Search across two tiers:

**Tier 1 — Official and institutional channels** (check regularly):
- Fed official YouTube channel: https://www.youtube.com/@FederalReserve
- Brookings Institution: https://www.youtube.com/@BrookingsInstitution
- Council on Foreign Relations: https://www.youtube.com/@CFR_org
- Peterson Institute: https://www.youtube.com/@PIIE_org

**Tier 2 — Media channels** (search by speaker name + date when official site shows no record):
- CNBC Television: https://www.youtube.com/@CNBCtelevision
- Bloomberg Television: https://www.youtube.com/@BloombergTelevision
- Wall Street Journal: https://www.youtube.com/@WSJ

**When to search YouTube proactively:**
- Any official bank website shows an event listing stub with no transcript
- The official website shows no record of a known appearance (e.g., Powell spoke at Harvard Mar 30, 2026 — not posted on federalreserve.gov, only on CNBC's YouTube channel)
- Goolsbee, Kashkari, or any official whose appearances are predominantly external events

**Search method for a known appearance:**
```
yt-dlp --dump-json --flat-playlist --playlist-end 10 \
  "ytsearch10:[Speaker Name] Federal Reserve [Month] [Year]"
```
Then fetch the specific video:
```
python3 main.py youtube <youtube_url>
```

Apply a light cleanup pass for Fed-specific jargon errors in auto-transcripts before saving. Save source URL as the first line of the raw file (`SOURCE: <youtube_url>`).

**Important:** YouTube is the primary fallback for Atlanta (external media only), Cleveland, St. Louis, and any official whose bank website serves only event descriptions without transcripts. Goolsbee (Chicago) frequently appears at external events (NABE, Detroit Economic Club, Semafor, Milken, Hoover) with no Chicago Fed transcript — YouTube is the primary source for his post-March 2026 speeches.

### Media monitoring
- Bloomberg API (institutional license — use for systematic media pickup tracking)
- GDELT (free, use as fallback): https://www.gdeltproject.org

---

## Storage

**Google Drive is handled automatically** — the project folder (`/Users/revilth/Documents/Research_Claude/Monitoring_Fed/`) is already linked to Google Drive via the desktop sync client. No API needed. All files saved locally are automatically synced.

Local folder structure (mirrors to Drive):
```
data/
  raw/
    speeches/
      YYYY/
        SPEAKER_NAME/
          YYYYMMDD_speech_title.txt
    statements/
      YYYYMMDD_fomc_statement.txt
    minutes/
      YYYYMMDD_fomc_minutes.txt
    testimony/
      YYYYMMDD_speaker_testimony.txt
    pressconferences/
      YYYYMMDD_pressconf_transcript.txt
  scored/
    speeches/
      YYYYMMDD_SPEAKER_scored.txt
    statements/
    minutes/
  reports/
    daily/
      YYYYMMDD_SPEAKER_daily.txt
    weekly/
      YYYYMMDD_weekly_report.txt
    alerts/
```

**Important — source URL tracking:** The source URL for each speech must be saved as the first line of every raw file in the format `SOURCE: <url>`. This is required because the analyst verifies speeches at source. The scraper should write this header before the speech text. For already-saved files without a URL header, the URL can be reconstructed from the known patterns above or verified via the scraper.

---

## Speaker Classification

### Troika — Core (highest weight)
These officials not only express personal views but informally aggregate views across the committee. Their language shifts are the most meaningful leading indicators. The Troika is also where statement language originates or gets ratified before appearing in committee documents.
- Chair (currently Jerome Powell)
- Vice Chair (currently Philip Jefferson)
- NY Fed President (currently John Williams)

**Succession (2026):** Kevin Warsh cleared the Senate Banking Committee on April 29, 2026 (announced by Powell at the press conference). Powell's term as Chair ends May 15, 2026; he will remain as a governor for a period to be determined. Once Warsh is sworn in as Chair, treat him as Troika immediately — his pre-confirmation public statements are already trackable. Powell as governor: "low profile," will not act as shadow chair, committed to working with Warsh.

### Just Voters — FOMC Voters (2026 rotation)
Check the current year's voter list at https://www.federalreserve.gov/monetarypolicy/fomc.htm

**2026 voter list** (confirmed from April 29, 2026 FOMC dissent record):
- Jerome Powell, Philip Jefferson, John Williams (Troika, always vote)
- Michelle Bowman (Vice Chair for Supervision)
- Michael Barr, Lisa Cook, Christopher Waller (Board Governors)
- Stephen Miran (Board Governor — confirmed 2026)
- Anna Paulson (Philadelphia — rotating; replaced Patrick Harker as president)
- Beth Hammack (Cleveland — rotating)
- Neel Kashkari (Minneapolis — rotating)
- Lorie Logan (Dallas — rotating)

**Note on Adriana Kugler:** Kugler appears to have departed the Board before April 29, 2026 — her name was absent from the voter record. Do not count her in voter tallies without confirmation.

**Median voter (2026):** Anna Paulson (Philadelphia) was assessed as the committee's median voter before the correct voter list was confirmed. With Logan (hawkish dissenter on April 29) now confirmed as a voter, the committee's effective median may have shifted slightly hawkish. Paulson remains the best single anchor — her inflation-first bar is more restrictive than Jefferson's symmetric framing and less extreme than Logan's dissent position. Reassess if Logan gives an economic outlook speech.

**Roster changes as of 2026:**
- Anna Paulson replaced Patrick Harker as Philadelphia Fed president (transition occurred before 2026)
- Raphael Bostic (Atlanta) retired February 2026; interim president in place, not yet posting speeches
- Stephen Miran is a new Board Governor appointed in 2026
- Kugler: appears to have left the Board between March 18 and April 29, 2026 — absent from April 29 vote
- **April 29, 2026 dissents:** Miran dissented preferring a cut; Hammack, Kashkari, and Logan dissented opposing the easing bias language — three hawkish regional dissenters simultaneously

**IMPORTANT — previous voter list error:** Before April 29, 2026, CLAUDE.md incorrectly listed Collins (Boston), Goolsbee (Chicago), and Musalem (St. Louis) as Just Voters, and Logan (Dallas), Kashkari (Minneapolis), Hammack (Cleveland) as Non Voters. This was reversed. All reports written before April 29 that classify these officials should be read with this correction in mind. Logan's speeches are particularly affected — her hawkish framing was correct as an analytical matter, but her vote weight was understated.

### Non Voters — FOMC Non-Voters
Regional presidents who are not currently voting members. Track for information value and as leading indicators of future voter sentiment.

**Non Voters for 2026:**
- Susan Collins (Boston) — rotating non-voter; high analytical quality
- Austan Goolsbee (Chicago) — rotating non-voter; YouTube is primary source; dissented against Dec 2025 cut; inflation-first framing in 2026
- Alberto Musalem (St. Louis) — rotating non-voter; low transcript availability
- Thomas Barkin (Richmond) — neutral; strong on-the-ground business intelligence on pricing and consumer behavior
- Mary Daly (San Francisco) — available via speaker page scraper

---

## Communication Type Classification

Classify every document into one of the following types before scoring.

### Type A: Economic Outlook Speech
The most important type for policy forecasting. Typically has three sections (though not always in this order and sometimes combined):
1. **Labor markets / Growth** — assessment of employment conditions and economic activity
2. **Inflation** — current inflation dynamics and outlook
3. **Monetary policy implications** — what the above means for rate decisions

When processing: identify which section each paragraph belongs to. Sometimes labor and growth are separate; sometimes combined. Flag this in metadata.

### Type B: Special Topic Speech
Covers issues not directly about the current economic outlook (AI, financial regulation, payment systems, international finance, etc.)

Important nuance: many special topic speeches also contain an economic outlook section, either at the beginning or at the end. When found, extract and score that section using Type A methodology. Flag the speech as Type B with embedded outlook.

### Type C: FOMC Statement
Post-meeting statement. Compare word-for-word against the prior statement. Semantic changes in specific phrases are the primary signal.

### Type D: FOMC Minutes
Released ~3 weeks after the meeting. Contains information not in the statement. Score independently and compare to the corresponding statement for divergence signals.

### Type E: Press Conference (Chair only)
Transcript of post-meeting Q&A. Particularly important because unscripted responses reveal reasoning behind decisions.

### Type F: Congressional Testimony (Chair only)
Semi-annual Humphrey-Hawkins testimony. Treat as a high-signal document; the Chair speaks more candidly to Congress than in public speeches.

### Type G: Jackson Hole Speech (Chair only)
Annual speech at the Kansas City Fed's Jackson Hole symposium. Historically used to signal major policy shifts. Treat as highest-priority document.

---

## Analytical Framework

### The Language Cycle

Understanding the direction language travels is as important as the language itself. There are two directions:

**Bottom-up (dispersed → consolidated):**
1. Individual officials use different language to describe the same issue
2. Some formulations start appearing across multiple speakers
3. The shared language eventually appears in the FOMC statement

When you see a phrase spreading from one official to two or three others but not yet in the statement, it is a potential leading indicator of where the next statement will move.

**Top-down (statement → speeches):**
The committee is sometimes forced into a compromise formulation before any individual speech has prepared the ground — the statement language appears first, then officials start echoing it in subsequent speeches.

When a speaker uses language that appears verbatim or near-verbatim in the most recent FOMC statement, treat it as signaling committee consensus — not as a personal signal. The speaker's own additions and modifications around that boilerplate are the actual signal.

**Practical implication:** Always distinguish between (a) FOMC statement language being echoed — which tells you where the consensus already is — and (b) the speaker's own language — which tells you where they personally are and potentially where the committee is heading.

### Per-Topic Analysis Structure

For every Type A speech, analyze separately by topic: **Growth**, **Labor Market**, **Inflation**, **Monetary Policy** — in that order. Within each topic:

1. **FOMC statement language echoed** — quote the relevant statement phrase, then show how the speaker renders it. Paraphrasing the statement signals consensus; departing from it signals personal view.

2. **Speaker's own language** — the characterization, qualifier, or framing the speaker adds beyond the statement. Often found in the topic sentence or conclusion of a paragraph. This is the primary signal.

3. **Shift vs. prior speech** — how this topic changed from the speaker's immediately preceding speech. Note direction: hawkish / dovish / unchanged.

4. **Shift vs. pre-FOMC speech** — how this topic changed from the speaker's last speech before the reference FOMC meeting. This shows the full post-meeting trajectory.

**Growth section guidance:** Growth and labor market often go together, but in the current cycle they are diverging — growth has remained resilient while labor market fragility has become the primary concern. Always include a GROWTH section, but keep it brief (2-3 sentences) when policymakers make only passing reference to it. Give it fuller treatment only when growth is itself a policy concern or when a speaker flags a compositional concern (e.g., spending concentrated in high-income households, narrow AI investment base) that could affect the outlook.

**Scenario framing — precision matters:** When a speaker presents risk scenarios, note whether the framing is (a) **explicit and named** — the speaker labels it as a scenario and specifies a policy response (e.g., Waller Apr 17: "BENIGN / ADVERSE" with named outcomes), or (b) **descriptive** — the speaker mentions a risk or possibility without pre-committing to a policy response (e.g., Williams Apr 16: "could also result in a large supply shock..."). Explicit scenario framing is a stronger signal of pre-commitment than descriptive risk language. Note this distinction in the scored file and daily report.

**Pre-FOMC baseline requirement:** Before writing a post-FOMC speech's scored file, verify that the speaker's pre-FOMC baseline speech is also scored. If it is not, score it first. The "vs. pre-FOMC" comparison is only meaningful when the baseline is a scored document with exact quotes, not a recalled summary.

**Language change verification — CRITICAL:** Before flagging any phrase or formulation as "new," "added," or "first use," verify it did not appear in the speaker's immediately prior speech or press conference. For press conferences in particular: the opening statement is largely recycled across meetings, so any phrase labeled as an addition must be confirmed absent from the prior opening statement. Failure to verify produces false directional signals — incorrectly labeling unchanged language as a shift is a serious analytical error. The rule: if you cannot point to the prior document and confirm the phrase is absent, do not claim it is new.

**Comparison claims must be grounded in quotes:** When writing "vs. PREVIOUS PRESS CONFERENCE" or "vs. PRIOR SPEECH" comparisons, every directional claim (hawkish / dovish / unchanged) must be supported by the actual language from both documents — not a summary or recollection. If the prior document was not read in this session, read it before making the comparison. Vague claims like "more explicit than March" or "moved from implicit to explicit" require verification against the March transcript before they can be written.

**Subsector vs. whole-sector attribution — CRITICAL:** When a speaker structures a topic section with separate paragraphs for subsections (e.g., hard data vs. soft data within labor markets), the concluding sentence of a paragraph applies to that subsection only — not to the topic as a whole. Before characterizing a phrase as the speaker's overall verdict on growth / labor / inflation, verify it is not the closing line of a subsection paragraph. The speaker's overall characterization is typically in the topic's opening sentence or the explicit summary. Misattributing a subsector conclusion as an overall verdict produces incorrect directional assessments.

**No comparative editorial judgments about analytical quality:** Do not describe one speaker's reasoning as "most analytically sophisticated," "most intellectually rigorous," or equivalent comparative terms relative to other officials. These are subjective assessments with no objective grounding in the text. Describe each speaker's framing precisely using their own language and methodology — the analyst draws comparative quality assessments, not the scoring agent.

**Label inferences explicitly:** When a conclusion is not directly stated by the speaker but inferred from the combination of their language, their dissent behavior, or their implicit reasoning, label it as such in the text — e.g., "[Inference: ...]" or "Implied by X and Y, though not stated directly." Do not present inferences as if they were the speaker's own characterizations. The analyst needs to know what is grounded in the text and what is a reading between the lines.

### Key signals to look for

**Hawkish signals:**
- Emphasis that inflation remains too high or above target; references to duration ("five years above 2%")
- Language suggesting patience before cutting ("further progress needed," "not yet confident")
- Acknowledgment of strong labor market as a reason not to rush easing
- Explicit resistance to market pricing of rate cuts
- Characterizing rates as near-neutral (removes mechanical justification for cuts)
- "Sequence of transitory shocks" framing (raises the bar for looking through inflation)
- References to upside inflation risks or fragile inflation expectations

**Dovish signals:**
- Acknowledgment that inflation is moving sustainably toward target
- Emphasis on labor market softening or cooling; soft data diverging from hard data
- Forward guidance language suggesting cuts are approaching ("in coming months")
- Reference to risks becoming more balanced or tilted to the downside
- Mentions of real rate being restrictive or well above neutral
- Explicit cut signal language ("further reductions will eventually be warranted")

**Neutral / informational:**
- Pure data recitation without directional framing
- Historical context with no current implication
- FOMC statement language echoed without modification

### Boilerplate to ignore
- Standard data citations without framing ("CPI rose X%")
- Ritual phrases ("our dual mandate," "data dependent," "meeting by meeting")
- "Well positioned to respond to a range of outcomes" — this is the committee's stable holding formula; only flag if it disappears or changes
- Introductory and closing pleasantries

**Important:** The same phrase can mean different things in different cycle contexts. Always note the current cycle regime in scoring context.

---

## Output Format

### Per-speech scored file (save to /scored/speeches/)

The reference FOMC date must always be stated. All shifts are measured against (a) the speaker's immediately prior speech and (b) their last pre-FOMC speech.

```
══════════════════════════════════════════════════════════
PER-SPEECH ANALYSIS
══════════════════════════════════════════════════════════
[DATE] | [SPEAKER] | [ROLE] | [Troika / Just Voter / Non Voter]
"[TITLE]"
[EVENT]
SOURCE: [verified URL]

REFERENCE FOMC:    [date]
PRE-FOMC BASELINE: [date]  "[title]"
POST-FOMC PRIOR:   [date]  "[title]"  (or N/A if this is first post-FOMC speech)
──────────────────────────────────────────────────────────

GROWTH
──────────────────────────────────────────────────────────
[Keep brief (2-3 sentences) if growth is not a primary concern. Fuller
treatment when speaker flags compositional concerns or demand risks.]

FOMC statement language echoed: [if any]
  → Speaker version: "[how speaker renders it]"

Own language:
  "[exact quote]" — [interpretation]

Shift vs. prior speech:   [unchanged / hawkish lean / dovish lean] — [1 sentence]
Shift vs. pre-FOMC:       [unchanged / hawkish lean / dovish lean] — [1 sentence]

──────────────────────────────────────────────────────────
LABOR MARKET
──────────────────────────────────────────────────────────
FOMC statement language echoed:
  "[exact statement phrase]" [stmt date]
  → Speaker version: "[how speaker renders it]"

Own verdict:
  "[exact quote]" — [1-line interpretation]

Own qualifier / addition:
  "[exact quote]" — [interpretation; note if hawkish/dovish lean]

Shift vs. prior speech:   [unchanged / hawkish lean / dovish lean] — [1 sentence]
Shift vs. pre-FOMC:       [unchanged / hawkish lean / dovish lean] — [1 sentence]

──────────────────────────────────────────────────────────
INFLATION
──────────────────────────────────────────────────────────
FOMC statement language echoed:
  "[exact statement phrase]"
  → Speaker version: "[how speaker renders it]"

Own language — KEY:
  "[exact quote]" — [interpretation]

Shift vs. prior speech:   [unchanged / hawkish lean / dovish lean] — [1 sentence]
Shift vs. pre-FOMC:       [unchanged / hawkish lean / dovish lean] — [1 sentence]

──────────────────────────────────────────────────────────
MONETARY POLICY
──────────────────────────────────────────────────────────
FOMC statement language echoed:
  "[exact statement phrase]"
  → Speaker version: "[how speaker renders it]"

Own language:
  "[exact quote]" — [interpretation]

[If Troika: track cut/hike signal explicitly]
  Cut signal status: [present / absent / retracted on DATE]

Shift vs. prior speech:   [unchanged / hawkish lean / dovish lean] — [1 sentence]
Shift vs. pre-FOMC:       [unchanged / hawkish lean / dovish lean] — [1 sentence]

──────────────────────────────────────────────────────────
SUMMARY
──────────────────────────────────────────────────────────
Net signal:    [unchanged / hawkish lean / dovish lean]
               [2-3 sentence overall interpretation]

Language watch:
  • "[phrase]" — [note on potential to spread; language cycle stage]
  • ...

Analyst flag:  [YES / NO]
  → [reason if YES — specific question for analyst to assess]
══════════════════════════════════════════════════════════
```

### Daily report (save to /reports/daily/)

**One file per calendar date**, named `YYYYMMDD_daily.txt`. Contains ALL speeches from that date in Troika → Just Voter → Non Voter order. Always generated immediately after scoring — never deferred.

If a speech on that date has no transcript (panel discussion, stub), include it in the header with status "NOT SCORED" and an action item for transcript recovery (YouTube search, etc.). Do not silently omit it.

```
FED MONITOR — DAILY UPDATE
════════════════════════════════════════════════════════════════
Date: [Month Day, Year]
Reference FOMC: [date]  |  Cycle: [regime]  |  FFR: [target range]
════════════════════════════════════════════════════════════════
SPEECHES TODAY
  1. [Speaker]  |  [Role]  |  [Troika / Just Voter / Non Voter]
     "[Title]"
     [Event], [Location]
     SOURCE: [verified URL]
  2. [Speaker...]  (STATUS: NOT SCORED — [reason] if applicable)
════════════════════════════════════════════════════════════════

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[N].  [SPEAKER]  |  [Role]  |  [Classification]
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

GROWTH
  [Brief (2-3 sentences) unless growth is a policy concern. Note any
  compositional concerns or demand risks the speaker flags.]
  Direction: [neutral / hawkish lean / dovish lean]

LABOR MARKET
  [2-3 sentences: verdict, key language, whether it shifted]
  Direction: [neutral / hawkish lean / dovish lean]

INFLATION
  [2-3 sentences: key language, FOMC anchor vs. personal addition]
  Direction: [neutral / hawkish lean / dovish lean]

MONETARY POLICY
  [2-3 sentences: stance language, cut/hike signal status, scenario
  framing if present — note whether explicit+named or descriptive]
  Direction: [neutral / hawkish lean / dovish lean]

NET SIGNAL: [unchanged / hawkish lean / dovish lean] — [1-line summary]

vs. PRIOR SPEECH ([date]):              [unchanged / hawkish / dovish] — [1 line]
vs. PRE-FOMC SPEECH ([date]):           [unchanged / hawkish / dovish] — [1 line]
vs. COMMITTEE SINCE FOMC:              [where this speaker sits relative to peers]

For press conferences (Type E), replace the last three comparison lines with:

vs. PREVIOUS PRESS CONFERENCE ([date]): [compare statement language changes on
  growth, labor, inflation, and policy; note every word change that signals a
  directional shift; note any dissent changes]
vs. CHAIR'S PREVIOUS SPEECH ([date]):   [how the Chair's unscripted Q&A language
  compares to their most recent public speech; flag any new personal signals]
vs. COMMITTEE SINCE PREVIOUS FOMC:     [what speeches between the two meetings
  anticipated or diverged from the statement language]

Press conference structure: Score the OPENING STATEMENT separately from the Q&A.
Statement language = committee consensus (approved by all voters). Q&A responses =
Chair's personal signals (unscripted; often more revealing). Flag when Q&A language
goes beyond the statement.

**Sources placement:** Sources appear only in the SOURCES section at the end of the
report. Do not include SOURCE URLs in the report header — keep the header clean
(date, decision, dissenters, comparison references only).

**Press conference opening statement — carry-over warning:** The opening statement
recycles large portions verbatim from the prior press conference. Before flagging
any phrase as "new" or "added," confirm it was absent from the prior opening
statement. In practice: read the prior opening statement before writing the "vs.
PREVIOUS PRESS CONFERENCE" section. Carry-over language is neutral; only genuine
additions or deletions are directional signals.

**Press conference report length:** The analyst watches the press conference live.
The Q&A section is an analytical summary of key unscripted signals — not a
transcription and not a question-by-question log. Aim for 4-6 bullets covering
only the moments where Powell's Q&A language materially diverged from or added to
the opening statement. Total report length should be comparable to a scored Type A
speech (roughly the same as the March 18 press conference report).

LANGUAGE TO WATCH:
  • "[phrase]" — [language cycle stage; spread risk]

ANALYST FLAG: [YES / NO — specific question if yes]

════════════════════════════════════════════════════════════════
SOURCES
────────────────────────────────────────────────────────────────
Speeches this date:
  [Speaker] [date]:  [verified URL]
  ...

Prior speech (vs. PRIOR SPEECH):
  [Speaker] [date]:  [verified URL]

Pre-FOMC baseline (vs. PRE-FOMC SPEECH):
  [Speaker] [date]:  [verified URL]
════════════════════════════════════════════════════════════════
```

If multiple speakers appear, add a CROSS-SPEAKER NOTE before the SOURCES section when their language on the same day is worth comparing.

### Weekly report (save to /reports/weekly/)

Structure:
1. **Header**: week dates, reference FOMC date, cycle regime, median voter, any institutional context (succession, dissents)
2. **Week in Brief**: 3-5 bullets on what happened this week; net directional signal
3. **Since Last FOMC**: directional summary across all speakers since reference date
4. **Troika** — one subsection per member; includes before/after FOMC comparison table
5. **Just Voters** — median voter (Paulson) first, then remaining voters by analytical priority; condensed format
6. **Non Voters** — brief; flag Goolsbee and Collins for analytical quality
7. **Shared Language Since Last FOMC** — phrases appearing in 3+ officials; note language cycle stage (dispersed / emerging / committee-wide / in-statement)
8. **Upcoming** — next FOMC date, coverage gaps to fill, speeches expected

---

## Key Analytical Tasks

### Task 1: Speaker trajectory
For each speaker, maintain a chronological log of their policy-relevant language by topic (growth / labor / inflation / monetary policy). When a new speech arrives:
- Extract key sentences by topic
- Flag any sentence that represents a meaningful shift from the same speaker's prior speech
- Note whether the shift is hawkish or dovish
- Compare to their pre-FOMC baseline
- Human review: flag shifts for the analyst to validate before treating as confirmed

### Task 2: Statement / minutes diff
When a new FOMC statement arrives:
- Compare against the prior statement sentence by sentence
- Identify every word or phrase change
- For each change, assess whether it represents a hawkish shift, dovish shift, or neutral edit
- Produce a clean diff report with your interpretation of each change

When minutes arrive:
- Score the minutes independently
- Compare tone and topics against the corresponding statement
- Flag any divergence: topics discussed in the meeting that did not appear in the statement are high-signal

### Task 3: Cross-official language tracking
On a weekly basis (or after any cluster of speeches in a short window):
- Extract key sentences from speeches in the past 30 days, organized by topic
- Identify phrases that are semantically similar across different speakers
- Tag each phrase with its language cycle stage: dispersed / emerging shared / committee-wide / in-statement
- Ranked by: number of officials using similar language × speaker weight

### Task 4: Media pickup detection
After each Troika speech:
- Search Bloomberg for references to the speech within 48 hours
- Identify which specific sentences or phrases were quoted or paraphrased
- Flag sentences that received disproportionate media amplification relative to their prominence in the speech

---

## Implementation Notes

### How scoring works
Scoring is performed interactively by Claude Code — **not** via API calls. The Python scripts handle data collection only. To score:
1. Run `python3 main.py collect` and `python3 main.py youtube` to populate `data/raw/`
2. Ask Claude Code to read the raw files and write scored output to `data/scored/speeches/`
3. Claude Code reads PDFs natively and can also fetch them via `requests` + `pdfminer`

This approach has no API cost beyond the Claude Code subscription.

### PDF handling
Many Fed banks (Boston, Chicago, Philadelphia) serve speech transcripts as PDFs rather than HTML. The scraper automatically detects thin HTML pages (<3000 chars) and fetches the linked PDF instead, using `pdfminer.six` for text extraction. No manual download is needed.

### CLI commands
```
python3 main.py collect          # Scrape all web sources, save raw files
python3 main.py youtube          # Scan YouTube channels for transcripts
python3 main.py youtube <url>    # Fetch a single YouTube video
python3 main.py pending          # List unscored raw files (paste output to Claude Code)
python3 main.py diff             # Prepare statement diff for Claude Code to interpret
python3 main.py talking-points   # Prepare cross-official context for Claude Code
python3 main.py weekly           # Prepare weekly context for Claude Code
python3 main.py schedule         # Start daily background scheduler
```

### Speaker calibration notes (updated 2026-04-28)

- **Powell** term as Chair ends May 15, 2026. His final press conference (Apr 29) confirmed Kevin Warsh cleared the Senate Banking Committee that morning. Powell will stay on the Board as a governor "for a period of time to be determined" — to protect the institution from "legal attacks by the administration" which he called "unprecedented in our 113-year history." He committed to "keep a low profile" and work collaboratively with Warsh. Key policy signals from the Apr 29 press conference: (1) "labor demand has clearly softened" — first Troika-level demand-side labor admission; (2) HAWKISH Q&A: named two explicit pre-cut conditions — "backside of the energy shock" AND "progress on tariffs" must both occur "before we even thought about reducing rates"; (3) STACKING LOGIC applied explicitly: "we're already looking through the tariff shock, so [looking through energy] requires more caution" — Troika-level adoption of the Waller/Barkin "sequence of shocks" framework; (4) "next two quarters" deadline for tariff pass-through to dissipate. The Q&A is considerably more hawkish than the opening statement. Before Apr 29, Powell gave zero economic outlook speeches in 2026. Jefferson and Williams were carrying the policy signaling load.
- **Jefferson** uses the three-topic structure cleanly. His FOMC statement language echoing is very close to verbatim; his personal additions are where the signal lives. Key personal language to track: "susceptible to adverse shocks" (labor qualifier, appeared Apr 7) and "upside risk to my inflation forecast" (inflation qualifier, appeared Apr 7 — not yet in statement).
- **Williams** is the most data-rich Troika communicator. His labor analysis now distinguishes hard data (stabilization) from soft data (gradual softening) — a split the March 18 statement did not capture. His Mar 3 cut signal ("further reductions will eventually be warranted") was deliberately retracted by Mar 30 and remains absent. Track whether it re-emerges post-April FOMC.
- **Waller** gave the most hawkish Just Voter speech of 2026 on Apr 17. Key new framework: "sequence of transitory shocks" — explicitly warns against the reflexive "look through" approach when shocks stack. If this language spreads to Jefferson or Williams, it would signal a meaningful committee-wide hawkish recalibration. Also the first voter to say he would hold even if the labor market weakens, if inflation risks dominate. **Critical arc for calibration:** Waller dissented at Jan 28 preferring a cut; his Feb 23 speech ("Labor Market Data: Signal or Noise?") frames it as a "coin flip" on labor with "look through" tariffs intact and a conditional cut signal. By Apr 17 — after the February jobs disappointment and the late-February energy shock — he reversed to the committee's most hawkish stance. The Feb 23 scored speech is the essential pre-FOMC baseline for understanding this full reversal.
- **Paulson** (median voter) has set an explicit inflation-first bar: "If inflation is above 2 percent and has been for some time, I would be more cautious." This means she needs 2% inflation before considering patience on growth signals — more restrictive than Jefferson's symmetric dual-risk framing.
- **Goolsbee** (Chicago) is significantly less dovish in 2026 than his public reputation suggests. His Feb 24 NABE speech questioned whether rates are even restrictive ("not obvious that our interest rate policy is even restrictive") and explicitly cautioned against front-loading cuts. Do not rely on the "Goolsbee is the committee's dove" heuristic. His post-March speeches have no transcripts; YouTube is the primary fallback.
- **Bowman** (Vice Chair for Supervision) is the most explicitly dovish voter — "policy is moderately restrictive," wants "proactive" cuts. Her last economic outlook speech was January 16; her post-FOMC appearances are regulatory Type B. Her post-energy-shock policy view is unknown.
- **Miran** (new Governor) makes supply-side arguments for rate cuts (deregulation is disinflationary, balance sheet reduction warrants lower rates). He dissented at the March 18 meeting in favor of a cut. His analytical frame is distinct from all other officials.
- **Logan** (Dallas, Just Voter — confirmed Apr 29) uses the most hawkish framing of any voter and has the highest analytical credibility of any regional president (former NY Fed markets desk head). "Policy may be very close to neutral" (Feb 10). Dissented on Apr 29 against easing bias language — alongside Kashkari and Hammack. Her Feb 10 speech was a voter-level signal all along; its weight was previously understated due to incorrect voter classification. Track her as the hawkish anchor of the 2026 voter coalition.
- **Barkin** (Richmond, Non Voter) is neutral with strong on-the-ground intelligence. Introduced "series of supply shocks / cumulative effect matters" framing alongside Waller — watch for this to spread.

## Scheduling

- **Daily (non-blackout only)**: Check Fed Board website and regional Fed sites for new speeches; generate daily report for any new Type A speech and send by email at 6pm. **Skip entirely on FOMC blackout days** — no policy speeches are given during blackout, so there is nothing to report.
- **Post-FOMC meeting**: Immediately process statement diff; schedule minutes processing for ~3 weeks out; **update the reference FOMC date in CLAUDE.md and in all subsequent scored files and daily reports** — the reference date must always reflect the most recent FOMC meeting. Current reference FOMC: **April 29, 2026**.

**FOMC blackout calendar 2026** (second Saturday before meeting → day after meeting ends):

| FOMC Meeting | Blackout Start | Blackout End |
|---|---|---|
| Jan 28-29 | Jan 17 | Jan 30 | ✓ past
| Mar 18-19 | Mar 7 | Mar 20 | ✓ past
| Apr 28-29 | Apr 18 | Apr 30 | ✓ past
| Jun 17-18 | Jun 6 | Jun 19 |
| Jul 29-30 | Jul 18 | Jul 31 |
| Sep 16-17 | Sep 5 | Sep 18 |
| Oct 28-29 | Oct 17 | Oct 30 |
| Dec 9-10 | Nov 28 | Dec 11 |

Update this table each January with the new year's FOMC calendar. Also update `BLACKOUT_PERIODS_2026` in `send_daily_email.py`.
- **Weekly**: Run cross-official language tracking across past 30 days; generate weekly report
- **Event-triggered**: Jackson Hole, Congressional testimony — treat as priority, process same day

---

## Notes for Analyst Review

The analyst has direct experience writing Fed speeches and will provide periodic feedback on:
- Whether hawk-dove classifications are accurate
- Which sentences are substantive vs. boilerplate
- Speaker-specific calibration (some officials use consistently more cautious language regardless of their actual views)
- Cycle regime updates
- Median voter assessment (updated as committee composition or views shift)

Flag any speech or sentence where the classification is ambiguous for analyst review before including in reports.

---

## What is built (as of 2026-04-29)
- Web scrapers for all 13 Fed sources (Fed Board + 12 regional banks) with PDF extraction
- YouTube transcript scraper via yt-dlp with jargon cleanup
- Local storage mirroring the folder structure above (auto-synced to Drive)
- Qualitative hawk-dove scoring performed by Claude Code interactively (26 speeches + 3 press conferences scored)
- Statement diff module (text comparison + Claude Code interpretation)
- Cross-official talking point detection module
- Weekly report generator
- Daily/weekly scheduler
- Gmail MCP integration for email delivery (draft-based; send manually)

**Known gap — source URL storage:** Raw speech files do not currently include a `SOURCE:` header with the verified URL. This should be added to the scraper's `save_raw()` function and backfilled for existing files where URLs are known.

## Phase 2 (future — not yet implemented)
- Quantitative hawk-dove score (-3 to +3 scale) per speech
- Speaker-level time series for charting
- Embedding-based similarity scoring for talking point detection
- Greenbook forecast mapping for speech-implied economic projections
- Bloomberg media pickup tracking (requires institutional license)
- GDELT fallback for media monitoring
