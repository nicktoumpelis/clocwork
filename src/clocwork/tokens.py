#!/usr/bin/env python3
"""The token archive: per-day, per-model totals that outlive the agent logs
they were measured from.

Coding agents keep their logs for a limited time (Claude Code for about 30
days), and once a log is gone the tokens it recorded cannot be recovered from
anywhere. Each run scans the sources in clocwork.sources and merges what they
find into token_usage.json, which no code path may shrink.

Every source reduces its provider's usage fields to the same four disjoint
counters. Providers disagree about whether cached tokens are part of the
prompt count; additive() and inclusive() are the two readings, so the archive
never counts a token twice.
"""

import json
import os
import re
import tempfile
from collections import namedtuple

COUNTERS = ("input", "output", "cache_read", "cache_write")

# days: {date: {"turns", "models"}}; malformed: lines that did not parse;
# skipped: files that could not be read at all.
ScanResult = namedtuple("ScanResult", "days malformed skipped", defaults=(0,))

DATE = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")

VERSION = 2
# Version 1 archives predate sources and hold Claude Code transcripts only.
LEGACY_SOURCE = "claude-code"


class ArchiveError(RuntimeError):
    pass


def empty_counts():
    return {k: 0 for k in COUNTERS}


def text(value):
    """A non-empty string as written, or None. Agents write ids, model names
    and hashes as strings; a value of another type is read as missing."""
    return value if isinstance(value, str) and value else None


def day(stamp):
    """The date ('YYYY-MM-DD') an ISO 8601 timestamp starts with, or '' when
    the value is not one, which puts its usage on no day."""
    return stamp[:10] if isinstance(stamp, str) and DATE.match(stamp) else ""


def count(value):
    """A token count as written, or 0 for anything that is not an integer:
    no agent writes a missing, fractional or textual count, so every reader
    gives one the same meaning."""
    return value if isinstance(value, int) and not isinstance(value, bool) else 0


def additive(input=0, output=0, cache_read=0, cache_write=0):
    """The four counters from a provider that reports cache reads and writes
    beside the uncached input (Anthropic, Bedrock). A value that is not a
    count is zero, and nothing goes below it."""
    return {"input": max(0, count(input)), "output": max(0, count(output)),
            "cache_read": max(0, count(cache_read)), "cache_write": max(0, count(cache_write))}


def inclusive(prompt=0, output=0, cached=0, cache_write=0):
    """The four counters from a provider whose prompt count already contains
    its cached and cache-written tokens (OpenAI and most compatible APIs).
    Read as-is, such a prompt would count every cached token twice."""
    uncached = count(prompt) - count(cached) - count(cache_write)
    return additive(uncached, output, cached, cache_write)


def record(days, date, model, counts):
    """Add one model response to a scan's per-day, per-model totals."""
    day = days.setdefault(date, {"turns": 0, "models": {}})
    day["turns"] += 1
    totals = day["models"].setdefault(text(model) or "unknown", empty_counts())
    for k in COUNTERS:
        totals[k] += counts[k]


def source_total(entry):
    """Every token in one source's record for one day."""
    return sum(v for counts in entry["models"].values() for v in counts.values())


def day_total(day):
    """Every token recorded for one day, across sources, models and counters."""
    return sum(source_total(entry) for entry in day.values())


def merge(archive, scanned):
    """Combine an archive with a fresh scan, keeping the larger record for
    each (date, source).

    A record's measurable total grows while work continues and shrinks once
    its logs pass out of the agent's retention window, so neither policy is
    safe alone: overwriting would let retention erase archived days, and
    skipping would freeze the current day at whatever it held on the first run
    of the morning. Keeping the larger record does both jobs. It is decided
    per source because agents' logs expire independently: one day can hold a
    shrinking Claude Code record beside a growing Codex one.
    """
    merged = {date: dict(day) for date, day in archive.items()}
    for date, day in scanned.items():
        target = merged.setdefault(date, {})
        for source, entry in day.items():
            if source not in target or source_total(entry) > source_total(target[source]):
                target[source] = entry
    return merged


def load(path):
    """The archived days, by date and then by source, or {} when no archive
    exists yet. A version 1 archive is read as Claude Code's."""
    if not os.path.exists(path):
        return {}
    # Deliberately not try/except: a corrupt archive must raise here, not
    # return {}. archive() calls load() then save()s the merged result, so a
    # swallowed error here would make save() write only the current scan's
    # ~30 days, permanently erasing every archived day older than that.
    with open(path) as f:
        data = json.load(f)
    version, days = data.get("version"), data.get("days", {})
    if version == 1:
        return {date: {LEGACY_SOURCE: day} for date, day in days.items()}
    if version == VERSION:
        return days
    raise ArchiveError(f"{path} is a version {version} token archive; "
                       f"this clocwork reads versions 1 and {VERSION}")


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


def archive(repo_path, archive_path, sources, homes=None, log=print):
    """Scan every source's logs for a repository and merge them into its archive.

    `homes` maps a source key to the directories to read in place of the
    source's own defaults; that is how the tests point a source at a fixture.
    The archive is written only when some source found usage for the
    repository, so a machine without any never creates or touches one.
    """
    days = load(archive_path)
    was_days, was_total = len(days), sum(day_total(d) for d in days.values())

    scanned, missing = {}, []
    for source in sources:
        # An override is used even when empty: [] means read nothing.
        where = (homes or {}).get(source.KEY)
        if where is None:
            where = source.default_homes(os.environ)
        result = source.scan(repo_path, where)
        if result is None:
            missing.append(f"{source.LABEL} ({', '.join(where) or 'no directories'})")
            continue
        for date, day in result.days.items():
            scanned.setdefault(date, {})[source.KEY] = day
        n = len(result.days)
        log(f"  Scanned {n} {'day' if n == 1 else 'days'} of {source.LABEL} logs")
        if result.malformed:
            log(f"  NOTE: skipped {result.malformed} unparseable {source.LABEL} lines")
        if result.skipped:
            reason = getattr(source, "SKIPPED", "")
            log(f"  NOTE: could not read {result.skipped} {source.LABEL} files" + (f": {reason}" if reason else ""))
    if missing:
        log(f"  No logs for this repository from {'; '.join(missing)}")
    if not scanned:
        log(f"  Archive left unchanged: {was_days} days, {was_total:,} tokens")
        return days

    days = merge(days, scanned)
    save(archive_path, days)
    total = sum(day_total(d) for d in days.values())
    log(f"  Archive now {len(days)} days, {total:,} tokens "
        f"(+{len(days) - was_days} days, +{total - was_total:,} tokens)")
    return days
