# clocwork

Run `clocwork` inside any git repository and get a dashboard of its whole
history: lines per language and type (code, comment, blank) at every commit,
which commits an AI agent co-authored and when each model first appeared, and,
when the repository was worked on with Claude Code, what that work cost in
tokens, dollars and electricity. Every commit is measured with
`cloc --git --diff`, cached per file, and reconciled against a `cloc` snapshot
of HEAD so drift is visible rather than silent.

The output is one `index.html` (its charts load Chart.js and its plugins from a CDN) plus a
`commit_bodies.js` sidecar for the full commit messages, written to a
**workspace** next to the repository, never inside it.

## Requirements

- Python 3.11 or later (standard library only)
- [`cloc`](https://github.com/AlDanial/cloc) 2.x on `PATH` (`brew install cloc`, `apt install cloc`)
- `git`

## Running

From a clone, no install step:

```bash
git clone https://github.com/nicktoumpelis/clocwork.git
cd ~/code/foo && ~/code/clocwork/clocwork
```

Or install the `clocwork` command:

```bash
pip install -e ~/code/clocwork      # or: pipx install ~/code/clocwork
cd ~/code/foo && clocwork
```

The first run over a long history measures every commit with `cloc`, running
one `cloc` process per CPU core (`--jobs N` chooses the number). On a 10-core
machine the 289 commits of [spf13/cast](https://github.com/spf13/cast) take
14 seconds (113 seconds with `--jobs 1`), and a repository of 3,800 commits,
2,700 of them non-merge, takes about four minutes. Results are cached, so
later runs take seconds. `--max-commits N` caps one run and a later run
continues from where it stopped.

## Commands

```
clocwork [REPO]          analyse, archive tokens, render, open the dashboard
clocwork tokens [REPO]   archive Claude Code transcripts only
clocwork render -o DIR   re-render the dashboard from existing workspace data
```

`REPO` is the repository or any directory inside it; the default is the
current directory. A first argument that is not a subcommand is taken as
`REPO`, so `clocwork ~/code/foo` works.

`tokens` is a separate command because the two halves of the pipeline have
opposite economics. The `cloc` pass is slow and fully regenerable. The
transcript archive is cheap and irreplaceable: Claude Code keeps transcripts
for roughly 30 days, and a day that is not archived while its transcript
exists is gone for good. `clocwork tokens` is what to run from cron.

`render` needs no repository, only a workspace; it exists so the page can be
iterated on without re-analysing.

Options (`clocwork run --help`):

```
  -q, --quiet       print nothing but errors
  --config PATH     explicit clocwork.toml
  --locale TAG      region locale for the page (default: $CLOCWORK_LOCALE,
                    else the machine's region)
  --no-open         do not open the dashboard in a browser
  -o, --output DIR  workspace directory (default: <repo-parent>/<repo-
                    name>-stats)
  --branch REF      ref to analyse (default: the checked-out branch)
  --max-commits N   measure at most N uncached commits this run
  -j, --jobs N      cloc processes to run at once (default: one per CPU core)
  --no-tokens       skip the transcript scan
  --cache-dir DIR   cache location (default: $XDG_CACHE_HOME/clocwork, else
                    ~/.cache/clocwork; wins over both)
```

`tokens` takes only `-o` and `-q`: it writes no page. `render` takes the page
options and `-q`, and its `-o` is required. `--version` prints the version.
The same reference is a manual page: `man ./man/clocwork.1` from a clone.

The page formats every number, date and unit for a region locale. The
generator records it, because browsers expose only the language list: the
`CLOCWORK_LOCALE` environment variable wins (a BCP 47 tag such as `en-SE`),
then the macOS Language & Region setting, then `LC_ALL`, `LC_NUMERIC` and
`LANG`; `--locale` overrides all of them for one run.

## The workspace

Output goes to a sibling of the repository: `~/code/foo` produces
`~/code/foo-stats`. It is deliberately not inside the repository, because the
tool would then be measuring its own output and dirtying the working tree of
the repository it reports on. Pass `-o DIR` to put it elsewhere.

```
foo-stats/
  clocwork.json           which repository this workspace belongs to
  clocwork.toml           optional configuration (see below)
  token_usage.json        the per-day token archive; cannot be regenerated
  full_commit_data.json   the analysis
  index.html              the dashboard
  commit_bodies.js        full commit messages, loaded when a row is expanded
```

The workspace is meant to be committed to its own repository: that is the
backup for `token_usage.json`. `clocwork.json` is an identity guard. On every
run the target repository is compared against it, by remote URL first and
absolute path second, and a mismatch is refused with an error naming both
repositories, so no ordinary mistake can overwrite one repository's token
archive with another's.

The `cloc` cache lives outside the workspace, in
`$XDG_CACHE_HOME/clocwork/<name>-<hash>/` or `~/.cache/clocwork/`, keyed by
the repository's absolute path. It holds per-file rows rather than
per-language totals, so changing the language table or the test-path rules
below re-reads the cache instead of re-running `cloc`.

## Configuration

Optional. Searched in this order, first hit wins: `--config PATH`, then
`<workspace>/clocwork.toml`, then `<repo>/.clocwork.toml`. The last is read and
never written, so a repository can commit its own settings while someone
analysing it can still override them from their workspace.

```toml
title = "MyApp"                         # page heading; default is the repository's directory name

[tests]
include = ["integration/**", "e2e/**"]  # added to the built-in test-path rules
exclude = ["tests/fixtures/**"]         # applied last, wins over everything
replace = false                         # true drops the built-ins entirely

[agents]
extra = [{ match = "Jules", name = "Jules" }]   # substring of a Co-Authored-By trailer, reported name
```

Globs match the whole path from the repository root: `**` matches across
directories, `*` within one, `?` one character. `*.py` therefore matches only
top-level files; `**/*.py` matches at any depth.

### What counts as test code

Built in, by directory: `test`, `tests`, `__tests__`, `testdata` (any
case); `spec` and `specs` for Ruby, JavaScript, TypeScript and CoffeeScript
files only, so a `specs/` directory of design documents is not counted; a directory named `*Test` or
`*Tests` (Xcode, JVM); the `src/test/`, `src/androidTest/` and
`src/integrationTest/` layouts. By filename: `*_test.go`; `test_*.py`, `*_test.py`, `conftest.py`; `*.test.*`
and `*.spec.*` for JavaScript and TypeScript; `*Test.*` and `*Tests.*` for
Java, Kotlin, C# and Swift; `*_spec.rb`, `*_test.rb`, `*_test.dart`,
`*_test.exs`. Inline test code (Rust's `#[cfg(test)]`, Go examples in a
non-test file) is not detectable from paths.

The run summary prints the test share of HEAD. A share that is obviously wrong
is the signal to add a rule; the fix costs a config line and a re-read, not a
re-measure.

### Which commits are AI-assisted

Attribution comes from `Co-Authored-By:` trailers only, so a commit that
merely mentions an agent is not counted. Any Claude model is recognised and
normalised (`Claude Opus 4.6`, `Claude Opus 5 (1M)`), and Copilot, Cursor,
Codex, Devin and aider are recognised by name. Anything else stays unmatched
rather than guessed at; `[agents].extra` names the rest.

### Token usage

The token section appears when Claude Code transcripts exist for the
repository under `~/.claude/projects/`. Per-day totals are archived into
`token_usage.json` with a keep-the-larger-record rule, days before the
archive are estimated from the archive's tokens-per-line ratio, and the page
prices the result at API list prices and estimates its electricity. For any
repository not worked on with Claude Code on this machine, the section is
simply absent; that is the normal case, not an error.

## Development

```bash
python3 -m unittest discover -s tests -t . -q     # the Python suite
node tests/dashboard/run_all.js                   # the page, in a fake DOM under node
```

The dashboard suite renders a synthetic workspace (`tests/dashboard/fixture.py`)
through `./clocwork render`. Set `CLOCWORK_DASH_WORKSPACE=<dir>` to run the
same checks over any rendered workspace, a real one included.

`man/clocwork.1` is generated from the argparse parsers, and a test checks the
committed page is current. After changing any help text or the version,
regenerate it:

```bash
PYTHONPATH=src python3 -m clocwork.manpage > man/clocwork.1
```

To exercise the command end to end against a throwaway repository with Go,
Python, JavaScript and Java test conventions:

```bash
R=$(python3 -c 'import sys, tempfile, os; sys.path[:0] = ["src", "."]
from tests import repo_fixture as fx
d = tempfile.mkdtemp(); r = os.path.join(d, "poly"); os.makedirs(r); fx.make_polyglot_repo(r); print(r)')
./clocwork "$R" --no-open --cache-dir /tmp/clocwork-cache
```

## Licence

MIT.
