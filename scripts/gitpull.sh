#!/bin/bash
set -e
REPO=/Users/revilth/Documents/Claude_Research/Monitoring_Fed
LOG=$REPO/logs/gitpull.log

echo "$(date '+%Y-%m-%d %H:%M:%S') Starting git pull" >> "$LOG"
cd "$REPO"
/usr/bin/git pull --no-rebase origin main >> "$LOG" 2>&1
echo "$(date '+%Y-%m-%d %H:%M:%S') Done" >> "$LOG"
