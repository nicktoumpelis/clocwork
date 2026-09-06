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
