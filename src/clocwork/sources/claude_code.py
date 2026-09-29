"""Claude Code: one JSONL transcript per session under
~/.claude/projects/<encoded-repo-path>/, kept for about 30 days.

A sub-agent's turns go to a transcript of its own,
<session-id>/subagents/agent-<id>.jsonl beside the session's, flat whatever
the nesting; none of them is in the parent's. Over one repository's last
month they held a quarter of the tokens.

Resumed and forked sessions replay earlier turns verbatim into the new
transcript, so every assistant turn is deduplicated by its message id, across
parents and sub-agents alike. On one repository's history that replay accounts
for 22,069 of 40,398 turns: summing without deduplication over-counts by more
than 2x.
"""

import json
import os
import re

from clocwork import tokens
from clocwork.paths import claude_project_dir

KEY = "claude-code"
LABEL = "Claude Code"
# Every name agents.parse_claude_model produces, the unknown version included.
AGENT = re.compile(r"^Claude\b")


def default_homes(env):
    return [os.path.expanduser("~/.claude/projects")]


def transcript_dir(repo, projects_dir):
    """The transcript directory for a repository, or None when it does not exist."""
    directory = os.path.join(projects_dir, claude_project_dir(repo))
    return directory if os.path.isdir(directory) else None


def scan(repo, homes):
    """The repository's usage from the first home holding its transcripts."""
    for home in homes:
        directory = transcript_dir(repo, home)
        if directory is not None:
            return scan_directory(directory)
    return None


def transcripts(directory):
    """Every transcript in a project directory: the sessions' own, then each
    session's sub-agents'. Only those two places hold transcripts; a session's
    other folders (tool-results/, workflows/) hold tool output and scripts."""
    def jsonl(folder):
        return [os.path.join(folder, n) for n in sorted(os.listdir(folder)) if n.endswith(".jsonl")]
    found = jsonl(directory)
    for name in sorted(os.listdir(directory)):
        sub = os.path.join(directory, name, "subagents")
        if os.path.isdir(sub):
            found += jsonl(sub)
    return found


def scan_directory(directory):
    """Per-day, per-model token totals for every transcript in `directory`."""
    days = {}
    seen = set()
    malformed = 0

    for path in transcripts(directory):
        with open(path, errors="replace") as f:
            for line in f:
                # Cheap prefilter: most lines are user turns, tool results and
                # attachments. Parsing only the candidates keeps a full scan of
                # a ~1 GB directory under two seconds.
                if '"usage"' not in line:
                    continue
                try:
                    rec = json.loads(line)
                except ValueError:
                    malformed += 1
                    continue
                # A line of another shape is skipped, and an id, model or
                # timestamp of the wrong type is read as missing.
                if not isinstance(rec, dict) or rec.get("type") != "assistant":
                    continue
                msg = rec.get("message")
                usage = msg.get("usage") if isinstance(msg, dict) else None
                if not usage or not isinstance(usage, dict):
                    continue
                key = tokens.text(msg.get("id")) or tokens.text(rec.get("requestId")) or tokens.text(rec.get("uuid"))
                if key is not None:
                    if key in seen:
                        continue            # a replayed turn from a resumed session
                    seen.add(key)
                date = tokens.day(rec.get("timestamp"))
                if not date:
                    continue
                counts = tokens.additive(
                    usage.get("input_tokens"), usage.get("output_tokens"),
                    usage.get("cache_read_input_tokens"), usage.get("cache_creation_input_tokens"))
                # A turn that used no tokens, such as the "<synthetic>" turns
                # Claude Code writes, is not a response.
                if any(counts.values()):
                    tokens.record(days, date, msg.get("model"), counts)

    return tokens.ScanResult(days, malformed)
