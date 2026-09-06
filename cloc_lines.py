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

import json
import os
import re
import shutil
import subprocess
import time
from collections import namedtuple

TYPES = ("code", "comment", "blank")
OTHER = "Other"

# A file is test code when any directory on its path is "Tests" or ends in
# "Tests" (WinterTests, WinterUITests). The filename itself is not considered.
TEST_SEGMENT = re.compile(r"^\w*Tests$")

# git's well-known empty tree, used as the parent of the root commit.
EMPTY_TREE = "4b825dc642cb6eb9a060e54bf8d69288fbee4904"


class ClocMissing(RuntimeError):
    pass


class ClocError(RuntimeError):
    pass


def empty_row():
    return [0, 0, 0, 0, 0, 0]


def is_test_path(path):
    parts = path.replace("\\", "/").split("/")
    return any(TEST_SEGMENT.match(seg) for seg in parts[:-1])


def parse_extension_table(text):
    """Parse `cloc --show-ext` output into {extension: language}.

    Language names are kept whole: "C/C++ Header" is one language, and an
    ambiguous entry such as "MATLAB/Mathematica/Objective-C/MUMPS/Mercury" is
    reported verbatim so the HEAD mapping check can flag it if it ever appears.
    """
    table = {}
    for line in text.splitlines():
        parts = line.split(None, 1)
        if len(parts) == 2:
            table[parts[0].lower()] = parts[1].strip()
    return table


def language_for(path, table):
    name = path.rsplit("/", 1)[-1]
    if "." not in name or name.startswith(".") and name.count(".") == 1:
        return OTHER
    ext = name.rsplit(".", 1)[-1].lower()
    return table.get(ext, OTHER)


_SKIP_KEYS = ("header", "SUM", "nFiles")


def _add_counts(matrix, lang, offset, counts):
    row = matrix.setdefault(lang, empty_row())
    for t, name in enumerate(TYPES):
        row[2 * t + offset] += int(counts.get(name, 0))


def _prune(matrix):
    return {lang: row for lang, row in matrix.items() if any(row)}


def parse_diff_json(obj, table):
    """Sum a `cloc --git --diff --by-file --json` result into per-language matrices.

    Returns (lines, test_lines). "modified" lines are changed in place and do
    not alter totals, so only the "added" and "removed" sections are read.
    """
    lines, test_lines = {}, {}
    for section, offset in (("added", 0), ("removed", 1)):
        for path, counts in obj.get(section, {}).items():
            if path in _SKIP_KEYS or not isinstance(counts, dict):
                continue
            lang = language_for(path, table)
            _add_counts(lines, lang, offset, counts)
            if is_test_path(path):
                _add_counts(test_lines, lang, offset, counts)
    return _prune(lines), _prune(test_lines)


def _type_counts(counts):
    return {t: int(counts.get(t, 0)) for t in TYPES}


def _accumulate(target, lang, counts):
    row = target.setdefault(lang, {t: 0 for t in TYPES})
    for t in TYPES:
        row[t] += counts[t]


def parse_snapshot_by_language(obj):
    """Parse `cloc --git --json <rev>` into {language: {code, comment, blank}}."""
    return {k: _type_counts(v) for k, v in obj.items()
            if k not in _SKIP_KEYS and isinstance(v, dict)}


def parse_snapshot_by_file(obj, table):
    """Parse `cloc --git --by-file --json <rev>` into (all_files, test_files)."""
    all_files, test_files = {}, {}
    for path, counts in obj.items():
        if path in _SKIP_KEYS or not isinstance(counts, dict):
            continue
        lang = language_for(path, table)
        tc = _type_counts(counts)
        _accumulate(all_files, lang, tc)
        if is_test_path(path):
            _accumulate(test_files, lang, tc)
    return all_files, test_files
