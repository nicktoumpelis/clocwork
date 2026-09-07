#!/usr/bin/env python3
"""Token usage measured from Claude Code transcripts.

Claude Code writes one JSONL transcript per session under
~/.claude/projects/<encoded-repo-path>/ and keeps them for about 30 days. This
module turns those files into per-day, per-model token totals so they can be
archived before they expire, because once a transcript is gone the tokens it
recorded cannot be recovered from anywhere.

Resumed and forked sessions replay earlier turns verbatim into the new
transcript, so every assistant turn is deduplicated by its message id. On
one repository's history that replay accounts for 22,069 of 40,398 turns: summing
without deduplication over-counts by more than 2x.
"""

import json
import os
import re
import sys
from collections import namedtuple

COUNTERS = ("input", "output", "cache_read", "cache_write")

# Claude Code's usage field names, mapped to the shorter ones used in the archive.
USAGE_FIELDS = {
    "input_tokens": "input",
    "output_tokens": "output",
    "cache_read_input_tokens": "cache_read",
    "cache_creation_input_tokens": "cache_write",
}

PROJECTS_DIR = os.path.expanduser("~/.claude/projects")

ScanResult = namedtuple("ScanResult", "days malformed")


def encode_repo_path(repo_path):
    """Claude Code's directory name for a repository: the absolute path with
    every non-alphanumeric character replaced by a hyphen, one for one."""
    return re.sub(r"[^a-zA-Z0-9]", "-", os.path.abspath(repo_path))


def transcript_dir(repo_path, projects_dir=PROJECTS_DIR):
    """The transcript directory for a repository, or None when it does not exist."""
    directory = os.path.join(projects_dir, encode_repo_path(repo_path))
    return directory if os.path.isdir(directory) else None


def empty_counts():
    return {k: 0 for k in COUNTERS}


def scan(directory):
    """Per-day, per-model token totals for every transcript in `directory`."""
    days = {}
    seen = set()
    malformed = 0

    for name in sorted(os.listdir(directory)):
        if not name.endswith(".jsonl"):
            continue
        with open(os.path.join(directory, name), errors="replace") as f:
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
                if rec.get("type") != "assistant":
                    continue
                msg = rec.get("message") or {}
                usage = msg.get("usage")
                if not usage:
                    continue
                key = msg.get("id") or rec.get("requestId") or rec.get("uuid")
                if key is not None:
                    if key in seen:
                        continue            # a replayed turn from a resumed session
                    seen.add(key)
                date = (rec.get("timestamp") or "")[:10]
                if not date:
                    continue
                day = days.setdefault(date, {"turns": 0, "models": {}})
                day["turns"] += 1
                counts = day["models"].setdefault(msg.get("model") or "unknown", empty_counts())
                for field, counter in USAGE_FIELDS.items():
                    counts[counter] += usage.get(field) or 0

    return ScanResult(days, malformed)
