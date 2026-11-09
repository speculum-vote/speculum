#!/usr/bin/env bash
# Tell the owner when a run fails, through a GitHub issue (GitHub emails the repository's watchers).
# One open issue per kind of run: a failure opens it or adds a comment; the next success closes it.
# Usage: scripts/alert.sh <result: success|failure|cancelled|skipped> "<issue title>"
# Needs GH_TOKEN with issues: write, and GITHUB_REPOSITORY, GITHUB_SERVER_URL and GITHUB_RUN_ID (set by Actions).
set -u
result="$1"; title="$2"
run="$GITHUB_SERVER_URL/$GITHUB_REPOSITORY/actions/runs/$GITHUB_RUN_ID"
api="repos/$GITHUB_REPOSITORY/issues"
num=$(gh api "$api?state=open&per_page=100" --jq "[.[] | select(.pull_request == null and .title == \"$title\")][0].number // empty")
case "$result" in
  failure|cancelled)
    when=$(date -u '+%Y-%m-%d %H:%M UTC')
    msg="The run on $when ended: **$result**. Log: $run

The last good site stays up. A failed guard means the night's data was saved but not published; see the log for what it found."
    if [ -n "$num" ]; then
      gh api "$api/$num/comments" -f body="$msg" >/dev/null && echo "added to issue #$num"
    else
      gh api "$api" -f title="$title" -f body="$msg" >/dev/null && echo "opened an issue: $title"
    fi ;;
  success)
    if [ -n "$num" ]; then
      gh api "$api/$num/comments" -f body="Fixed: the run on $(date -u '+%Y-%m-%d %H:%M UTC') succeeded. $run" >/dev/null
      gh api -X PATCH "$api/$num" -f state=closed >/dev/null && echo "closed issue #$num"
    fi ;;
  *) echo "nothing to report ($result)" ;;
esac
exit 0
