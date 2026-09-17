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

import collections
import concurrent.futures
import functools
import json
import os
import re
import shutil
import subprocess
import time
from collections import namedtuple

from clocwork import paths
from clocwork.classify import DEFAULT_RULES, UNCOUNTED, extension, language_for, parse_extension_table, path_key

TYPES = ("code", "comment", "blank")

# git's well-known empty tree, used as the parent of the root commit.
EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"

# Before 2.06, `cloc --show-ext` printed "rb -> Ruby", which
# parse_extension_table reads as the language "-> Ruby". That table names every
# extension missing from the analysed ref, so a language whose files were all
# deleted is reported as "-> Ruby", and the run still succeeds.
MIN_VERSION = (2, 6)
INSTALL_HINT = ("clocwork needs cloc 2.06 or later: brew install cloc (macOS), a distribution package "
                "of 2.06 or later, or cloc-<version>.pl from https://github.com/AlDanial/cloc/releases "
                "saved as an executable named cloc on PATH.")


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
    # Sorted by language: cloc lists files in Perl hash order, which changes
    # from one run to the next, and the workspace file must not churn with it.
    return {lang: row for lang, row in sorted(matrix.items()) if any(row)}


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
            if lang == UNCOUNTED:
                continue
            _add_counts(lines, lang, offset, counts)
            if rules.is_test(path):
                _add_counts(test_lines, lang, offset, counts)
    return _prune(lines), _prune(test_lines)


def _accumulate(target, lang, counts):
    row = target.setdefault(lang, {t: 0 for t in TYPES})
    for t in TYPES:
        row[t] += counts[t]


def parse_snapshot_by_language(report):
    """{language: {code, comment, blank}} from a `by_file_report`, each file
    under the language cloc gave it."""
    by_lang = {}
    for path, counts in report.items():
        if path in _SKIP_KEYS or not isinstance(counts, dict) or not counts.get("language"):
            continue
        _accumulate(by_lang, counts["language"], _type_counts(counts))
    return by_lang


def parse_snapshot_by_file(obj, table, rules=DEFAULT_RULES):
    """Parse `cloc --git --by-file --json <rev>` into (all_files, test_files)."""
    all_files, test_files = {}, {}
    for path, counts in obj.items():
        if path in _SKIP_KEYS or not isinstance(counts, dict):
            continue
        lang = language_for(path, table)
        if lang == UNCOUNTED:
            continue
        tc = _type_counts(counts)
        _accumulate(all_files, lang, tc)
        if rules.is_test(path):
            _accumulate(test_files, lang, tc)
    return all_files, test_files


@functools.cache
def _version(path):
    """(major, minor) from `cloc --version`, or None when it prints no version."""
    result = subprocess.run([path, "--version"], capture_output=True, text=True, stdin=subprocess.DEVNULL)
    m = re.match(r"([0-9]+)\.([0-9]+)", result.stdout.strip())
    return (int(m[1]), int(m[2])) if m else None


def require_cloc():
    """Raise ClocMissing unless the cloc on PATH is one clocwork can read.

    A version that cannot be read is let through: a cloc that fails outright
    is reported by its first real run.
    """
    path = shutil.which("cloc")
    if path is None:
        raise ClocMissing("cloc is not installed or not on PATH. " + INSTALL_HINT)
    version = _version(path)
    if version is not None and version < MIN_VERSION:
        raise ClocMissing(f"cloc {version[0]}.{version[1]:02d} ({path}) is too old. " + INSTALL_HINT)


def run_cloc(args, cwd):
    """Run cloc with JSON output and return the parsed object ({} when cloc prints nothing)."""
    result = subprocess.run(["cloc", "--quiet", "--json"] + list(args),
                            capture_output=True, text=True, cwd=cwd, env=paths.git_env())
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


def parse_by_file_json(obj, base=None):
    """Learn a language table from `cloc --git --by-file --json <rev>`.

    Each extension gets one language: `base`'s (cloc's extension table) when
    some file with that extension has it, otherwise the language most of
    those files have. A file cloc names otherwise (CMakeLists.txt, a script
    by its shebang), and every file with no extension, is learned by path
    (`path_key`), so one odd file relabels neither itself nor the rest. Only
    paths present at the revision are learned; `classify.renamed_languages`
    covers their earlier names. The JSON report, not the CSV one: cloc does
    not quote CSV fields, so a comma in a name split it.
    """
    base = base or {}
    files = {}
    for path, counts in obj.items():
        if path in _SKIP_KEYS or not isinstance(counts, dict) or not counts.get("language"):
            continue
        files[path] = counts["language"]
    by_extension = {}
    for path, language in files.items():
        ext = extension(path)
        if ext is not None:
            by_extension.setdefault(ext, collections.Counter())[language] += 1
    learned = {}
    for ext, counts in by_extension.items():
        if base.get(ext) in counts:
            learned[ext] = base[ext]
        else:
            learned[ext] = min(counts, key=lambda language: (-counts[language], language))
    for path, language in files.items():
        ext = extension(path)
        if ext is None or language != learned[ext]:
            learned[path_key(path)] = language
    return learned


def merge_language_tables(base, overlay):
    merged = dict(base)
    merged.update(overlay)
    return merged


def regular_files(repo, rev):
    """The paths of rev's regular files: no symlinks, no submodules."""
    result = subprocess.run(["git", "-C", repo, "ls-tree", "-r", "-z", "--full-tree", rev],
                            capture_output=True, text=True, env=paths.git_env())
    files = set()
    for entry in result.stdout.split("\0"):
        meta, _, path = entry.partition("\t")
        if path and meta.startswith("100"):
            files.add(path)
    return files


def only_files(report, files):
    """The report's entries for `files`, and its header."""
    return {k: v for k, v in report.items() if k == "header" or k in files}


def by_file_report(repo, rev, uncounted=()):
    """cloc's per-file report of the regular files at rev, less `uncounted`.

    --skip-uniqueness: cloc otherwise counts identical files once, while the
    per-commit diffs count every copy. Symlinks are left out: cloc reads one
    as its target, in the snapshot always and in a diff only sometimes.
    """
    report = run_cloc(["--git", "--by-file", "--skip-uniqueness", rev], repo)
    return only_files(report, regular_files(repo, rev) - set(uncounted))


def learn_extensions(repo, rev, base=None, report=None):
    return parse_by_file_json(by_file_report(repo, rev) if report is None else report, base)


def build_language_table(repo, rev):
    """cloc's extension table, corrected by how cloc actually classified the files at rev."""
    base = load_extension_table()
    return merge_language_tables(base, learn_extensions(repo, rev, base))


def diff_commit(repo, parent, commit):
    return diff_rows(run_cloc(["--git", "--diff", "--by-file", parent or EMPTY_TREE, commit], repo))


def snapshot(repo, rev, table, rules=DEFAULT_RULES, report=None):
    """The tree at rev by the language cloc gave each file, and by the
    language `table` gives it (the two differ only where the table is
    wrong), from one `by_file_report`: `report`, if already in hand."""
    if report is None:
        report = by_file_report(repo, rev)
    all_files, tests = parse_snapshot_by_file(report, table, rules)
    return parse_snapshot_by_language(report), all_files, tests


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


def _measure_one(differ, repo, commit):
    """Run the differ for one commit. A cloc failure comes back as a value
    rather than an exception, so it is reported and skipped like any other
    result instead of ending the pass."""
    try:
        return differ(repo, commit["parent"] or EMPTY_TREE, commit["hash"]), None
    except ClocError as e:
        return None, e


def measure_commits(repo, commits, cache, table, rules, max_commits=None, flush_every=50,
                    differ=None, log=print, clock=time.monotonic, jobs=1):
    """Measure every non-merge commit not already in the cache.

    commits: [{"hash", "parent", "is_merge"}] in history order.
    Returns MeasureResult(measured={hash: (lines, test_lines)}, failed=[hash], pending=[hash]).
    The cache holds per-file rows; every entry, cached or fresh, is classified
    with this run's table and rules on the way out. Failures are logged and
    not cached so a later run retries them. When max_commits is set, uncached
    commits beyond the cap are left pending.

    `jobs` cloc processes run at once. Each is a subprocess a worker thread
    only waits on, so threads suffice and nothing needs pickling; the cache,
    the results and the log are touched by this thread alone. However the
    pass ends, the queue is cancelled and every measured commit, including
    those that finish while the queue is being dropped, is flushed.
    """
    differ = differ or diff_commit
    measured, failed, pending = {}, [], []
    todo = [c for c in commits if not c["is_merge"] and cache.get(c["hash"]) is None]
    if max_commits is not None:
        todo = todo[:max_commits]
    todo_hashes = {c["hash"] for c in todo}

    for c in commits:
        if c["is_merge"]:
            continue
        cached = cache.get(c["hash"])
        if cached is not None:
            measured[c["hash"]] = classify_rows(cached, table, rules)
        elif c["hash"] not in todo_hashes:
            pending.append(c["hash"])

    started = clock()
    done = 0

    def record(c, rows, error):
        nonlocal done
        if error is not None:
            failed.append(c["hash"])
            log(f"  cloc failed on {c['hash'][:7]}: {error}")
            return
        cache.put(c["hash"], rows)
        measured[c["hash"]] = classify_rows(rows, table, rules)
        done += 1
        if done % flush_every == 0:
            cache.save()
            elapsed = clock() - started
            remaining = (len(todo) - done) * (elapsed / done)
            log(f"  measured {done}/{len(todo)} new commits, {elapsed:.0f}s elapsed, ~{remaining:.0f}s remaining")

    pool = concurrent.futures.ThreadPoolExecutor(max_workers=jobs)
    futures, outstanding = {}, set()
    try:
        futures = {pool.submit(_measure_one, differ, repo, c): c for c in todo}
        outstanding = set(futures)
        for future in concurrent.futures.as_completed(futures):
            outstanding.discard(future)
            record(futures[future], *future.result())
    finally:
        # However the pass ended: keep what is recorded before joining the
        # in-flight jobs, because a second Ctrl-C during that join must not
        # lose it; drop the queue; then keep whatever the join finished.
        try:
            if cache.dirty:
                cache.save()
        finally:
            pool.shutdown(cancel_futures=True)
        for future in outstanding:
            if future.done() and not future.cancelled() and future.exception() is None:
                rows, error = future.result()
                if error is None:      # a cloc killed by the same Ctrl-C is noise, and the next run retries it
                    record(futures[future], rows, None)
        if cache.dirty:
            cache.save()
    order = {c["hash"]: i for i, c in enumerate(todo)}
    failed.sort(key=order.__getitem__)       # history order, whatever order they finished in
    return MeasureResult(measured, failed, pending)
