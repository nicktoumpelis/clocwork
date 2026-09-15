#!/usr/bin/env python3
"""Per-commit line counts with cloc.

For each commit, cloc's git diff mode reports added and removed lines per file,
split into code, comment and blank. This module classifies every file by
language (cloc's own extension table) and by whether it is test code, sums the
result into per-language matrices, and caches them by commit hash so the
expensive first pass is never repeated.

Matrix row layout, used everywhere downstream:

    [codeAdded, codeRemoved, commentAdded, commentRemoved, blankAdded, blankRemoved]
"""

import csv
import io
import json
import os
import shutil
import subprocess
import time
from collections import namedtuple

from clocwork.classify import DEFAULT_RULES, language_for, parse_extension_table

TYPES = ("code", "comment", "blank")

# git's well-known empty tree, used as the parent of the root commit.
EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"


class ClocMissing(RuntimeError):
    pass


class ClocError(RuntimeError):
    pass


def empty_row():
    return [0, 0, 0, 0, 0, 0]


_SKIP_KEYS = ("header", "SUM", "nFiles")


def _add_counts(matrix, lang, offset, counts):
    row = matrix.setdefault(lang, empty_row())
    for t, name in enumerate(TYPES):
        row[2 * t + offset] += int(counts.get(name, 0))


def _prune(matrix):
    return {lang: row for lang, row in matrix.items() if any(row)}


def _type_counts(counts):
    return {t: int(counts.get(t, 0)) for t in TYPES}


def diff_rows(obj):
    """The added and removed sections of a `cloc --git --diff --by-file --json`
    result as per-file rows, unclassified. "modified" lines are changed in
    place and do not alter totals, so they are not kept."""
    rows = {}
    for section in ("added", "removed"):
        rows[section] = {path: _type_counts(counts)
                         for path, counts in obj.get(section, {}).items()
                         if path not in _SKIP_KEYS and isinstance(counts, dict)}
    return rows


def classify_rows(rows, table, rules):
    """Per-language matrices (lines, test_lines) from per-file rows.

    Classification happens here, at read time, so a changed language table or
    test rule costs a re-read of the cache rather than a re-run of cloc.
    """
    lines, test_lines = {}, {}
    for section, offset in (("added", 0), ("removed", 1)):
        for path, counts in rows.get(section, {}).items():
            lang = language_for(path, table)
            _add_counts(lines, lang, offset, counts)
            if rules.is_test(path):
                _add_counts(test_lines, lang, offset, counts)
    return _prune(lines), _prune(test_lines)


def _accumulate(target, lang, counts):
    row = target.setdefault(lang, {t: 0 for t in TYPES})
    for t in TYPES:
        row[t] += counts[t]


def parse_snapshot_by_language(obj):
    """Parse `cloc --git --json <rev>` into {language: {code, comment, blank}}."""
    return {k: _type_counts(v) for k, v in obj.items()
            if k not in _SKIP_KEYS and isinstance(v, dict)}


def parse_snapshot_by_file(obj, table, rules=DEFAULT_RULES):
    """Parse `cloc --git --by-file --json <rev>` into (all_files, test_files)."""
    all_files, test_files = {}, {}
    for path, counts in obj.items():
        if path in _SKIP_KEYS or not isinstance(counts, dict):
            continue
        lang = language_for(path, table)
        tc = _type_counts(counts)
        _accumulate(all_files, lang, tc)
        if rules.is_test(path):
            _accumulate(test_files, lang, tc)
    return all_files, test_files


def require_cloc():
    if shutil.which("cloc") is None:
        raise ClocMissing("cloc is not installed or not on PATH. Install it with: brew install cloc")


def run_cloc(args, cwd):
    """Run cloc with JSON output and return the parsed object ({} when cloc prints nothing)."""
    result = subprocess.run(["cloc", "--quiet", "--json"] + list(args),
                            capture_output=True, text=True, cwd=cwd)
    if result.returncode != 0:
        raise ClocError(result.stderr.strip() or f"cloc exited with {result.returncode}")
    out = result.stdout.strip()
    if not out:
        return {}
    try:
        return json.loads(out)
    except json.JSONDecodeError as e:
        raise ClocError(f"cloc produced invalid JSON: {e}")


def load_extension_table():
    result = subprocess.run(["cloc", "--show-ext"], capture_output=True, text=True)
    return parse_extension_table(result.stdout)


def parse_by_file_csv(text):
    """Learn {extension: language} from a `cloc --by-file --csv` report (non-diff).

    The report starts with a header row beginning "language,filename,"; rows
    after it are one file each; the SUM row is skipped. Only files with an
    extension contribute.
    """
    learned = {}
    lines = text.splitlines()
    start = next((i for i, l in enumerate(lines) if l.startswith("language,filename,")), None)
    if start is None:
        return learned
    for row in csv.reader(io.StringIO("\n".join(lines[start + 1:]))):
        if len(row) < 2 or row[0] == "SUM" or not row[1]:
            continue
        name = row[1].rsplit("/", 1)[-1]
        if "." in name and not (name.startswith(".") and name.count(".") == 1):
            learned[name.rsplit(".", 1)[-1].lower()] = row[0]
    return learned


def merge_language_tables(base, overlay):
    merged = dict(base)
    merged.update(overlay)
    return merged


def learn_extensions(repo, rev):
    result = subprocess.run(["cloc", "--quiet", "--git", "--by-file", "--csv", rev],
                            capture_output=True, text=True, cwd=repo)
    return parse_by_file_csv(result.stdout)


def build_language_table(repo, rev):
    """cloc's extension table, corrected by how cloc actually classified the files at rev."""
    return merge_language_tables(load_extension_table(), learn_extensions(repo, rev))


def diff_commit(repo, parent, commit):
    return diff_rows(run_cloc(["--git", "--diff", "--by-file", parent or EMPTY_TREE, commit], repo))


def snapshot(repo, rev, table, rules=DEFAULT_RULES):
    by_lang = parse_snapshot_by_language(run_cloc(["--git", rev], repo))
    all_files, tests = parse_snapshot_by_file(run_cloc(["--git", "--by-file", rev], repo), table, rules)
    return by_lang, all_files, tests


class Cache:
    """Per-commit results keyed by full hash, written atomically."""

    # 2: per-language aggregates that depended on the language table.
    # 3: per-file rows; language and test classification happen on read, so
    #    neither the table nor the test rules can invalidate an entry.
    VERSION = 3

    def __init__(self, path):
        self.path = path
        self.entries = {}
        self.dirty = 0
        if os.path.exists(path):
            try:
                with open(path) as f:
                    data = json.load(f)
            except (json.JSONDecodeError, OSError):
                return
            if data.get("version") == self.VERSION:
                self.entries = data.get("commits", {})

    def get(self, commit_hash):
        return self.entries.get(commit_hash)

    def put(self, commit_hash, rows):
        self.entries[commit_hash] = rows
        self.dirty += 1

    def save(self):
        os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
        tmp = self.path + ".tmp"
        with open(tmp, "w") as f:
            json.dump({"version": self.VERSION, "commits": self.entries}, f, separators=(",", ":"), sort_keys=True)
        os.replace(tmp, self.path)
        self.dirty = 0


MeasureResult = namedtuple("MeasureResult", "measured failed pending")


def measure_commits(repo, commits, cache, table, rules, max_commits=None, flush_every=50,
                    differ=None, log=print, clock=time.monotonic):
    """Measure every non-merge commit not already in the cache.

    commits: [{"hash", "parent", "is_merge"}] in history order.
    Returns MeasureResult(measured={hash: (lines, test_lines)}, failed=[hash], pending=[hash]).
    The cache holds per-file rows; every entry, cached or fresh, is classified
    with this run's table and rules on the way out. Failures are logged and
    not cached so a later run retries them. When max_commits is set, uncached
    commits beyond the cap are left pending.
    """
    differ = differ or diff_commit
    measured, failed, pending = {}, [], []
    todo = [c for c in commits if not c["is_merge"] and cache.get(c["hash"]) is None]
    if max_commits is not None:
        todo = todo[:max_commits]
    todo_hashes = {c["hash"] for c in todo}
    started = clock()
    done = 0

    for c in commits:
        if c["is_merge"]:
            continue
        cached = cache.get(c["hash"])
        if cached is not None:
            measured[c["hash"]] = classify_rows(cached, table, rules)
            continue
        if c["hash"] not in todo_hashes:
            pending.append(c["hash"])
            continue
        try:
            rows = differ(repo, c["parent"] or EMPTY_TREE, c["hash"])
        except ClocError as e:
            failed.append(c["hash"])
            log(f"  cloc failed on {c['hash'][:7]}: {e}")
            continue
        cache.put(c["hash"], rows)
        measured[c["hash"]] = classify_rows(rows, table, rules)
        done += 1
        if done % flush_every == 0:
            cache.save()
            elapsed = clock() - started
            remaining = (len(todo) - done) * (elapsed / done)
            log(f"  measured {done}/{len(todo)} new commits, {elapsed:.0f}s elapsed, ~{remaining:.0f}s remaining")

    if cache.dirty:
        cache.save()
    return MeasureResult(measured, failed, pending)
