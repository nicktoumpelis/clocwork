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
import tempfile
from collections import namedtuple

from clocwork.paths import claude_project_dir

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


def transcript_dir(repo_path, projects_dir=PROJECTS_DIR):
    """The transcript directory for a repository, or None when it does not exist."""
    directory = os.path.join(projects_dir, claude_project_dir(repo_path))
    return directory if os.path.isdir(directory) else None


def empty_counts():
    return {k: 0 for k in COUNTERS}


def additive(input=0, output=0, cache_read=0, cache_write=0):
    """The four counters from a provider that reports cache reads and writes
    beside the uncached input (Anthropic, Bedrock). Missing values are zero
    and nothing goes below it."""
    return {"input": max(0, input or 0), "output": max(0, output or 0),
            "cache_read": max(0, cache_read or 0), "cache_write": max(0, cache_write or 0)}


def inclusive(prompt=0, output=0, cached=0, cache_write=0):
    """The four counters from a provider whose prompt count already contains
    its cached and cache-written tokens (OpenAI and most compatible APIs).
    Read as-is, such a prompt would count every cached token twice."""
    uncached = (prompt or 0) - (cached or 0) - (cache_write or 0)
    return additive(uncached, output, cached, cache_write)


def record(days, date, model, counts):
    """Add one model response to a scan's per-day, per-model totals."""
    day = days.setdefault(date, {"turns": 0, "models": {}})
    day["turns"] += 1
    totals = day["models"].setdefault(model or "unknown", empty_counts())
    for k in COUNTERS:
        totals[k] += counts[k]


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


VERSION = 1


def day_total(day):
    """Every token recorded for one day, across models and counters."""
    return sum(v for counts in day["models"].values() for v in counts.values())


def merge(archive, scanned):
    """Combine an archive with a fresh scan, keeping the larger record per day.

    A day's measurable total grows while work continues and shrinks once its
    session files pass out of Claude Code's retention window, so neither policy
    is safe alone: overwriting would let retention erase archived days, and
    skipping would freeze the current day at whatever it held on the first run
    of the morning. Keeping the larger record does both jobs.
    """
    merged = dict(archive)
    for date, day in scanned.items():
        if date not in merged or day_total(day) > day_total(merged[date]):
            merged[date] = day
    return merged


def load(path):
    """The archived days, or {} when no archive exists yet."""
    if not os.path.exists(path):
        return {}
    # Deliberately not try/except: a corrupt archive must raise here, not
    # return {}. archive() calls load() then save()s the merged result, so a
    # swallowed error here would make save() write only the current scan's
    # ~30 days, permanently erasing every archived day older than that.
    with open(path) as f:
        return json.load(f).get("days", {})


def save(path, days):
    directory = os.path.dirname(path) or "."
    with tempfile.NamedTemporaryFile(mode="w", dir=directory, delete=False) as tmp:
        try:
            json.dump({"version": VERSION, "days": dict(sorted(days.items()))}, tmp, indent=1)
            tmp.write("\n")
            tmp_name = tmp.name
        except Exception:
            tmp.close()
            os.unlink(tmp.name)
            raise
    os.replace(tmp_name, path)
    # NamedTemporaryFile creates 0600; the archive is a committed, shared file.
    os.chmod(path, 0o644)


def archive(repo_path, archive_path, projects_dir=PROJECTS_DIR, log=print):
    """Scan a repository's transcripts and merge them into its archive."""
    days = load(archive_path)
    was_days, was_total = len(days), sum(day_total(d) for d in days.values())

    directory = transcript_dir(repo_path, projects_dir)
    if directory is None:
        log(f"  No transcripts at {os.path.join(projects_dir, claude_project_dir(repo_path))}")
        log(f"  Archive left unchanged: {was_days} days, {was_total:,} tokens")
        return days

    result = scan(directory)
    days = merge(days, result.days)
    save(archive_path, days)

    total = sum(day_total(d) for d in days.values())
    log(f"  Scanned {len(result.days)} days of transcripts from {directory}")
    log(f"  Archive now {len(days)} days, {total:,} tokens "
        f"(+{len(days) - was_days} days, +{total - was_total:,} tokens)")
    if result.malformed:
        log(f"  NOTE: skipped {result.malformed} unparseable lines")
    return days
