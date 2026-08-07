#!/usr/bin/env python3
"""Provenance guard for raw transcripts.

CLAUDE.md carries a hard rule: the deliverable is the OFFICIAL transcript, and a
raw or scored file must never be built out of news coverage. That rule was
violated twice in 2026 — the June 17 and July 29 FOMC statements were both
reconstructed from media after a fetch failed, and the July 29 reconstruction
invented a word change ("elevated" -> "somewhat elevated") that was then scored
as the meeting's main signal and shipped to the analyst.

A rule that depends on an agent remembering it under pressure is not a control.
This makes it mechanical: any raw file that looks media-derived, or that lacks a
SOURCE: line pointing at an official domain, fails the build.

Usage:
    python3 scripts/check_provenance.py --all            # scan every raw file
    python3 scripts/check_provenance.py --changed <ref>  # only files changed since <ref>
    python3 scripts/check_provenance.py --all --list     # report only, always exit 0

CI runs the --changed form against the push base, so the gate blocks NEW
violations without demanding a backfill of ~109 legacy files that predate the
SOURCE: convention.

Scope: provenance checks apply to the file HEADER (first HEADER_LINES lines),
not the body. Official FOMC press-conference transcripts contain lines like
"Jeff Cox from CNBC.com" — reporters identifying themselves — which are not
provenance claims and must not trip the guard.

Quarantine: a file that must be kept for audit despite being media-derived (e.g.
a superseded reconstruction) is exempted by listing its repo-relative path in
scripts/provenance_allowlist.txt, one per line. Add a reason as a # comment.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

# Provenance lives in the header. Body text is transcript content and may
# legitimately name news outlets (reporters state their affiliation in Q&A).
HEADER_LINES = 40

REPO = Path(__file__).resolve().parent.parent
RAW = REPO / "data" / "raw"
ALLOWLIST = Path(__file__).resolve().parent / "provenance_allowlist.txt"

# Phrases that indicate a document was assembled from coverage rather than
# fetched from the source.
# Note: bare "reconstruction" is deliberately NOT listed. A corrected official
# file may carry a note explaining that it previously held one (see
# data/raw/statements/20260617_FOMC_Statement.txt) — flagging that would punish
# the fix. Match the phrases that assert provenance, not the ones that discuss it.
MEDIA_MARKERS = [
    "reconstructed from",
    "compiled from search",
    "search-indexed sources",
    "live-blog",
    "live blog",
    "key takeaways",
    "according to reports",
]

# Outlets. Matched as substrings against the whole document; a raw transcript
# should never cite these as its provenance.
MEDIA_DOMAINS = [
    "cnbc.com", "bloomberg.com", "reuters.com", "finance.yahoo.com",
    "fxstreet.com", "wolfstreet.com", "foxbusiness.com", "npr.org",
    "forbes.com", "axios.com", "cnn.com", "marketwatch.com", "barrons.com",
    "wsj.com", "ft.com", "usnews.com", "fortune.com",
]

# Domains a raw transcript may legitimately come from.
OFFICIAL_HOSTS = [
    "federalreserve.gov",
    "bostonfed.org", "newyorkfed.org", "philadelphiafed.org", "clevelandfed.org",
    "richmondfed.org", "atlantafed.org", "chicagofed.org", "stlouisfed.org",
    "minneapolisfed.org", "kansascityfed.org", "dallasfed.org", "frbsf.org",
    "doi.org",                      # regional banks mint DOIs for speeches
    "youtube.com", "youtu.be",      # explicit video-only fallback per CLAUDE.md
    "bis.org", "fraser.stlouisfed.org",   # historical corpora
]


def load_allowlist() -> set[str]:
    if not ALLOWLIST.exists():
        return set()
    out = set()
    for line in ALLOWLIST.read_text(encoding="utf-8").splitlines():
        line = line.split("#", 1)[0].strip()
        if line:
            out.add(line)
    return out


# ---------------------------------------------------------------------------
# On-record interviews (CLAUDE.md Type J).
#
# An official sometimes gives an on-record interview that no Fed site ever
# publishes — e.g. John Williams to Reuters, 2026-08-03. The outlet that
# conducted it prints the full Q&A verbatim, so the transcript IS the primary
# source; there is no official version to prefer over it. That is categorically
# different from the coverage this guard exists to block (paraphrase, "key
# takeaways", the June 17 / July 29 statement reconstructions).
#
# So a media host is allowed for these ONLY when the header proves the claim:
# the doc type is declared INTERVIEW and the required provenance marker is
# present. MEDIA_MARKERS stay fatal regardless — a "key takeaways" page does not
# become primary by relabeling it.
# ---------------------------------------------------------------------------
INTERVIEW_TYPE_RE = re.compile(r"^(?:DOC[_ ]?TYPE|TYPE):\s*(?:J\b|INTERVIEW)", re.M | re.I)
INTERVIEW_PROVENANCE_RE = re.compile(
    r"^PROVENANCE:\s*first-party interview[;,]?\s*no official transcript published",
    re.M | re.I)


def is_declared_interview(header: str) -> bool:
    """True only if the header carries BOTH the Type J declaration and marker."""
    return bool(INTERVIEW_TYPE_RE.search(header)
                and INTERVIEW_PROVENANCE_RE.search(header))


def check_file(path: Path) -> list[str]:
    """Return a list of problems with this raw file (empty = clean)."""
    problems: list[str] = []
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        return [f"unreadable: {e}"]

    # Only the header makes provenance claims — see HEADER_LINES.
    header = "\n".join(text.splitlines()[:HEADER_LINES])
    low = header.lower()
    interview = is_declared_interview(header)

    # Never waived: these phrases assert the file was assembled from coverage.
    for marker in MEDIA_MARKERS:
        if marker in low:
            problems.append(f'media marker in header: "{marker}"')
    if not interview:
        for dom in MEDIA_DOMAINS:
            if dom in low:
                problems.append(f"media domain in header: {dom}")

    # Every raw file must declare where it came from.
    m = re.search(r"^SOURCE:\s*(\S+)", header, re.MULTILINE)
    if not m:
        problems.append("no SOURCE: header")
    else:
        src = m.group(1).lower()
        if not any(h in src for h in OFFICIAL_HOSTS) and not interview:
            problems.append(f"SOURCE is not an official host: {m.group(1)}")

    # A Type J file must also state who conducted it and carry real Q&A, so the
    # exemption cannot be claimed by a stub or a summary wearing the label.
    if interview:
        if not re.search(r"^INTERVIEWER(?:S)?:\s*\S", header, re.M | re.I):
            problems.append("Type J interview without an INTERVIEWER: header")
        if len(re.findall(r"^\s*Q(?:UESTION)?[:.]", text, re.M | re.I)) < 2:
            problems.append("Type J interview without verbatim Q&A turns "
                            "(expected 'Q:'-prefixed questions)")

    return problems


def worktree_raw_files() -> list[Path] | None:
    """Raw .txt files new or modified in the working tree (pre-commit check).

    Needed by the collect job, which validates freshly scraped files BEFORE
    committing them — at that point there is nothing to diff against HEAD.
    """
    try:
        out = subprocess.run(
            ["git", "status", "--porcelain", "--untracked-files=all", "--", "data/raw"],
            cwd=REPO, capture_output=True, text=True, check=True).stdout
    except (subprocess.CalledProcessError, OSError):
        return None
    files = []
    for line in out.splitlines():
        if len(line) < 4:
            continue
        status, rel = line[:2], line[3:].strip()
        if status.strip() == "D":
            continue
        if " -> " in rel:                      # rename
            rel = rel.split(" -> ", 1)[1]
        rel = rel.strip('"')
        if rel.startswith("data/raw/") and rel.endswith(".txt"):
            p = REPO / rel
            if p.exists():
                files.append(p)
    return files


def changed_raw_files(base: str) -> list[Path] | None:
    """Raw .txt files added/modified since `base`. None if git can't tell us."""
    try:
        out = subprocess.run(
            ["git", "diff", "--name-only", "--diff-filter=d", base, "HEAD"],
            cwd=REPO, capture_output=True, text=True, check=True).stdout
    except (subprocess.CalledProcessError, OSError):
        return None
    files = []
    for line in out.splitlines():
        if line.startswith("data/raw/") and line.endswith(".txt"):
            p = REPO / line
            if p.exists():
                files.append(p)
    return files


def main() -> int:
    argv = sys.argv[1:]
    report_only = "--list" in argv
    scan_all = "--all" in argv

    base = None
    if "--changed" in argv:
        i = argv.index("--changed")
        if i + 1 < len(argv):
            base = argv[i + 1]

    allow = load_allowlist()

    if not RAW.exists():
        print(f"No raw directory at {RAW} — nothing to check.")
        return 0

    targets: list[Path]
    if "--worktree" in argv and not scan_all:
        found = worktree_raw_files()
        if found is None:
            print("Could not read git status; falling back to full scan.")
            targets = sorted(RAW.rglob("*.txt"))
        else:
            targets = found
            print(f"Checking {len(targets)} new/modified raw file(s) in the working tree.")
    elif base and not scan_all:
        found = changed_raw_files(base)
        if found is None:
            print(f"Could not diff against {base!r}; falling back to full scan.")
            targets = sorted(RAW.rglob("*.txt"))
        else:
            targets = found
            print(f"Checking {len(targets)} raw file(s) changed since {base}.")
    else:
        targets = sorted(RAW.rglob("*.txt"))

    failures: dict[str, list[str]] = {}
    exempted = 0
    checked = 0

    for path in targets:
        rel = path.relative_to(REPO).as_posix()
        if rel in allow:
            exempted += 1
            continue
        checked += 1
        problems = check_file(path)
        if problems:
            failures[rel] = problems

    print(f"Provenance check: {checked} raw file(s) scanned, "
          f"{exempted} allowlisted, {len(failures)} problem file(s).")

    if failures:
        print()
        for rel, problems in sorted(failures.items()):
            print(f"  {rel}")
            for p in problems:
                print(f"      - {p}")
        print()
        print("A raw transcript must be fetched from the official source.")
        print("NEVER substitute news coverage. If the source cannot be reached,")
        print("mark the document NOT SCORED — TRANSCRIPT PENDING and recover it")
        print("later. To keep a superseded reconstruction for audit, add its path")
        print(f"to {ALLOWLIST.relative_to(REPO)}.")

    if report_only:
        return 0
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
