"""Pure classification of repository paths: language, and whether a file is test code.

Nothing here touches the filesystem or a subprocess, which is what lets the
test-path rules be a table and lets classification run every time the cache
is read rather than once when it is written.
"""

import re

OTHER = "Other"
# The table's entry for a path clocwork does not count (a symlink): its rows
# are left out of the history and the snapshot alike.
UNCOUNTED = ""

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


def extension(path):
    """The lower-cased extension of a path's filename, or None when it has none.

    A leading dot alone does not make one: ".gitignore" has no extension.
    """
    name = path.rsplit("/", 1)[-1]
    if "." not in name or name.startswith(".") and name.count(".") == 1:
        return None
    return name.rsplit(".", 1)[-1].lower()


def path_key(path):
    """The language-table key for one file.

    cloc names a file with no extension by filename or shebang, and can name
    a file against its extension (CMakeLists.txt is CMake, not Text), so the
    table holds such files by path. An extension never contains a slash, so
    the two kinds of key cannot collide: a root file called "go" is not an
    entry for ".go".
    """
    return "/" + path


def language_for(path, table):
    """A file's language: its own entry if it has one, else its extension's.
    UNCOUNTED means the file is left out."""
    own = table.get(path_key(path))
    if own is not None:
        return own
    ext = extension(path)
    return OTHER if ext is None else table.get(ext, OTHER)


def rename_plan(renames, table, present=()):
    """Path entries for renamed names, and the renames that change language.

    `renames` is [(old, new, old_language, new_language)], newest first, with
    the language cloc gives each side's content under that side's name (None
    when cloc does not count it). A name gone from the analysed ref and
    without an entry learns that language where the table would give it
    another, so an extensionless script is not Other in the history; the
    newest content decides. A name in `present` or already in the table
    keeps its language.

    cloc reports a rename under the old name, counted by the old name's
    parser. Where the two sides differ in language, by cloc or by the table,
    those rows cannot stand for the new name, and the caller replaces them
    (`cloc.rename_adjustments`); the old name keeps its own language.
    Returns (learned entries, indices of the renames that change language).
    """
    table = dict(table)
    learned = {}

    def learn(name, language):
        key = path_key(name)
        if language and key not in table and name not in present and language != language_for(name, table):
            table[key] = learned[key] = language

    for old, new, old_language, new_language in renames:
        learn(old, old_language)
        learn(new, new_language)
    changed = [i for i, (old, new, old_language, new_language) in enumerate(renames)
               if (old_language or new_language)
               and (old_language != new_language or language_for(old, table) != language_for(new, table))]
    return learned, changed


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
