"""Pure classification of repository paths: language, and whether a file is test code.

Nothing here touches the filesystem or a subprocess, which is what lets the
test-path rules be a table and lets classification run every time the cache
is read rather than once when it is written.
"""

import re

OTHER = "Other"

# Directory segments that mark test code, matched case-insensitively.
BUILTIN_DIRS = ("test", "tests", "__tests__", "testdata")
# "spec" directories are a Ruby and JavaScript convention; gated to those
# files so a specs/ directory of design documents is not counted as tests.
SPEC_DIRS = ("spec", "specs")
SPEC_EXTS = ("rb", "js", "jsx", "ts", "tsx", "mjs", "cjs", "coffee")
# Directory segments matched case-sensitively: the capitalised Xcode and JVM
# forms (Tests, WinterUITests, AppTest).
_CAPITALISED_DIR = re.compile(r"^\w+Tests?$")

# Filename patterns, as (regex over the filename, extensions or None for any).
BUILTIN_FILES = (
    (re.compile(r"_test\.go$"), None),
    (re.compile(r"^test_.*\.py$"), None),
    (re.compile(r"_test\.py$"), None),
    (re.compile(r"^conftest\.py$"), None),
    (re.compile(r"\.(test|spec)\.[^.]+$"), ("js", "jsx", "ts", "tsx", "mjs", "cjs")),
    (re.compile(r"Tests?\.[^.]+$"), ("java", "kt", "cs", "swift")),
    (re.compile(r"_(spec|test)\.rb$"), None),
    (re.compile(r"_test\.dart$"), None),
    (re.compile(r"_test\.exs$"), None),
)


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


def _glob_to_regex(pattern):
    """`**` matches across segments, `*` within one, `?` one character."""
    out = []
    i = 0
    while i < len(pattern):
        c = pattern[i]
        if pattern.startswith("**/", i):
            out.append("(?:.*/)?")
            i += 3
        elif pattern.startswith("**", i):
            out.append(".*")
            i += 2
        elif c == "*":
            out.append("[^/]*")
            i += 1
        elif c == "?":
            out.append("[^/]")
            i += 1
        else:
            out.append(re.escape(c))
            i += 1
    return re.compile("^" + "".join(out) + "$")


def _builtin_is_test(parts):
    dirs, name = parts[:-1], parts[-1]
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    if any(d.lower() in BUILTIN_DIRS for d in dirs):
        return True
    if ext in SPEC_EXTS and any(d.lower() in SPEC_DIRS for d in dirs):
        return True
    # JVM layouts (src/test/, src/androidTest/, src/integrationTest/) need
    # no rule of their own: "test" is a built-in word and the camel-cased
    # forms match _CAPITALISED_DIR.
    if any(_CAPITALISED_DIR.match(d) for d in dirs):
        return True
    for regex, exts in BUILTIN_FILES:
        if (exts is None or ext in exts) and regex.search(name):
            return True
    return False


class TestRules:
    """Test-path classification: built-ins plus a workspace's include/exclude globs.

    `exclude` is applied last and wins over everything; `replace=True` drops
    the built-ins so `include` is the whole rule set.
    """

    def __init__(self, include=(), exclude=(), replace=False):
        self.include = [_glob_to_regex(p) for p in include]
        self.exclude = [_glob_to_regex(p) for p in exclude]
        self.replace = replace

    def is_test(self, path):
        norm = path.replace("\\", "/")
        if any(r.match(norm) for r in self.exclude):
            return False
        if any(r.match(norm) for r in self.include):
            return True
        if self.replace:
            return False
        return _builtin_is_test(norm.split("/"))


DEFAULT_RULES = TestRules()
