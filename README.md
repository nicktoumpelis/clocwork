# clocwork

Run `clocwork` inside any git repository and get a dashboard of its whole
history: lines per language and type (code, comment, blank) at every commit,
which commits an AI agent co-authored and when each model first appeared, and,
when the repository was worked on with Claude Code, Codex CLI or Gemini CLI,
what that work cost in tokens, dollars and electricity. Every commit is
measured with `cloc --git --diff`, cached per file, and reconciled against a
`cloc` snapshot of HEAD so drift is visible rather than silent.

The output is one `index.html` (its charts load Chart.js and its plugins from
a CDN) plus a `commit_bodies.js` sidecar for the full commit messages, written
to a **workspace** next to the repository, never inside it.

## Requirements

- Python 3.11 or later (standard library only)
- [`cloc`](https://github.com/AlDanial/cloc) 2.06 or later on `PATH`. On
  macOS, `brew install cloc` gives a current release. Linux distributions
  often package an older one (Ubuntu 24.04 has 1.98). clocwork refuses an
  older cloc, because earlier releases list file extensions in a form it
  misreads. If yours is older, save `cloc-<version>.pl` from the
  [cloc releases](https://github.com/AlDanial/cloc/releases) as an
  executable named `cloc` on `PATH`.
- `git`

## Installing

```bash
pipx install clocwork          # or: pip install clocwork
```

pip does not install the manual page; `man/clocwork.1` is in the repository
and in the source distribution.

To run from a clone instead, with no install step:

```bash
git clone https://github.com/nicktoumpelis/clocwork.git ~/code/clocwork
cd ~/code/foo && ~/code/clocwork/clocwork
```

For development, `pip install -e ~/code/clocwork` installs the `clocwork`
command from the clone.

## Running

Run `clocwork` inside the repository to analyse, or pass its path. The first
run over a long history measures every commit with `cloc`, running one
`cloc` process per CPU core (`--jobs N` chooses the number). On a 10-core
machine the 289 commits of [spf13/cast](https://github.com/spf13/cast) take
14 seconds (113 seconds with `--jobs 1`), and a repository of 3,800 commits,
2,700 of them non-merge, takes about four minutes. Results are cached, so
later runs take seconds. `--max-commits N` caps one run and a later run
continues from where it stopped.

## Commands

```
clocwork [REPO]          analyse, archive tokens, render, open the dashboard
clocwork tokens [REPO]   archive agent token logs only
clocwork render -o DIR   re-render the dashboard from existing workspace data
```

`REPO` is the repository or any directory inside it; the default is the
current directory. A first argument that is not a subcommand is taken as
`REPO`, so `clocwork ~/code/foo` works.

`tokens` is a separate command because the two halves of the pipeline have
opposite economics. The `cloc` pass is slow and fully regenerable. The token
archive is cheap and irreplaceable: coding agents delete their logs (Claude
Code after roughly 30 days), and a day that is not archived while its logs
exist is gone for good. `clocwork tokens` is what to run from cron.

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
  --no-tokens       skip the agent log scan
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
  token_usage.json        the per-day, per-agent token archive; cannot be regenerated
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
Codex, Devin, aider, Gemini and Gemini Code Assist are recognised by name.
Anything else stays unmatched rather than guessed at; `[agents].extra` names
the rest.

### Token usage

The token section appears when the workspace's token archive holds at least
one day. Each run reads the logs coding agents keep on the machine and
archives per-day totals, per agent and model, into `token_usage.json`:

| Agent | Logs read | Override |
|---|---|---|
| Claude Code | `~/.claude/projects/`, the directory named after the repository's path | none |
| Codex CLI | `~/.codex/sessions/` and `~/.codex/archived_sessions/` | `CODEX_HOME` replaces `~/.codex` |
| Gemini CLI | `~/.gemini/tmp/` and `~/.cache/.gemini/tmp/`, sessions started in the repository or a directory it tracks | `GEMINI_CLI_HOME` replaces `~` |

A Codex session belongs to the repository when it records the same remote
as the repository's `origin`, so sessions from any clone or worktree count.
A session that recorded another remote still belongs when it ran in the
repository, or a directory inside it, from one of the repository's commits.
A renamed or transferred repository keeps its sessions that way, and a
different repository later cloned to the same path gets them only if it
holds the commit they started from. When the session records no remote, or
`origin` is missing or not a URL clocwork recognises, the session belongs
when it ran in the repository or a directory inside it.
Gemini CLI identifies a session's project only by a hash of the directory it
started in, so its sessions count when that is the repository's current path
or a directory tracked at `HEAD` below it.

Only dates, model names, and token and turn counts reach the archive;
prompts and replies are never kept. The archive keeps the larger record for
each day and agent, because agents delete their logs and a day not archived
in time is gone.

A day the archive does not cover for an agent, but on which that agent's
commits changed lines, is estimated from the agent's own tokens-per-line
ratio; a record that holds no tokens covers nothing. The result is priced at
API list prices, each measured day at the prices in force on it and the
estimated days at the measured mix, and its electricity is estimated. For
any repository not worked on with these agents on this machine, the section
and the commit table's Tokens column are simply absent; that is the normal
case, not an error.

Tokens land only on the commits of the agent whose logs measured them,
split across that agent's commits of the day by lines changed. A commit
carries no token figure when its agent's logs are not read (Copilot, Cursor,
Devin, aider, Gemini Code Assist or any other), or when they cover no day on
which that agent's commits changed lines, and it is never priced at another
agent's rate. When the repository has token data, the run summary counts
those commits and names their agents. Gemini Code Assist is the name for
`gemini-code-assist[bot]`, which GitHub credits when one of its review
suggestions is accepted.

Codex asks its model to end commit messages with
`Co-authored-by: Codex <noreply@openai.com>` unless attribution is turned
off. Gemini CLI adds no trailer, so its tokens reach a commit only when the
commit credits Gemini by hand, in a trailer such as
`Co-Authored-By: Gemini CLI <address>`; otherwise the page says its tokens
land on no commit. Codex rollouts that Codex has compressed are read on
Python 3.14 and later; earlier versions count them as unreadable and say so
in the log.

An archive written by an earlier version is read as Claude Code's and
rewritten in the per-agent shape the next time a scan finds logs; an archive
of a version this clocwork does not know is refused with an error rather
than read or overwritten.

## Development

```bash
python3 -m unittest discover -s tests -t . -q     # the Python suite
node tests/dashboard/run_all.js                   # the page, in a fake DOM under node
```

The dashboard suite renders a synthetic workspace (`tests/dashboard/fixture.py`)
through `./clocwork render`. Set `CLOCWORK_DASH_WORKSPACE=<dir>` to run the
checks over any rendered workspace, a real one included; the files that
exercise the token-less page and the page with several agents render their
own synthetic variants regardless. Checks that assume the fixture's size,
such as the 500-row cap, fail over a short history.

`tests/fixtures/` holds real Codex CLI and Gemini CLI sessions from two
MIT-licensed repositories, reduced to identity, model, usage and timestamps;
its README names the sources and carries their licence notices.

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
