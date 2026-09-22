# Changelog

All notable changes to clocwork are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.2.0] - 2026-09-22

### Added

- A run prints one line per phase with the time it took, the phase's
  warnings, a short summary and the page's path. On a terminal the output is
  coloured, with each warning under its phase's line, a live line saying
  what the phase is doing and a progress bar while cloc measures;
  redirected, it is plain lines, one fact per line. `-v`/`--verbose` also
  prints each phase's details and the per-language table. `NO_COLOR`, or
  `TERM=dumb`, turns the colour off. Ctrl-C prints `clocwork: interrupted`
  and exits 130. In redirected output the `Archive now …` line of
  `clocwork tokens` and the `Test code at …` line keep their wording, for
  scripts that read them.

- Token usage from Copilot CLI, read from `~/.copilot` (`COPILOT_HOME`).
  A session started on 1.0.69 or later is read from its per-call rows in
  `session-store.db`, each call on its own day; if a store is there but its
  rows are missing, the session is held back and the archive keeps what
  earlier runs gave it. An earlier session is read from whichever of its
  rows or its shutdown snapshots holds more, and a session with no store at
  all from its snapshots. The snapshots are cumulative, so only what each
  adds to the largest one before it is archived, and a resumed session is
  not counted twice. Its tokens land on commits with the trailer the CLI
  asks for by default,
  `Co-authored-by: Copilot <223556219+Copilot@users.noreply.github.com>`.

- Token usage from Kilo Code, read from `~/.local/share/kilo` on every
  system (`$XDG_DATA_HOME/kilo`, plus any database `KILO_DB` names) by the
  OpenCode reader, since Kilo Code's store is OpenCode's. Each record is read
  under the rules of the OpenCode release that Kilo release carried.
  Commits whose trailer names Kilo Code are credited to it.

- Token usage from Qwen Code, read from `~/.qwen` (`QWEN_HOME`,
  `QWEN_RUNTIME_DIR`, and every directory an `advanced.runtimeOutputDir`
  setting names): the per-call records releases from 0.4.0 write, and the
  Gemini CLI format earlier ones wrote. Commits with the
  `Co-authored-by: Qwen-Coder <qwen-coder@alibabacloud.com>` trailer Qwen
  Code appends are credited to it; a trailer that only names a Qwen model is
  not.

- Token usage from Antigravity, from the conversation databases of the CLI
  (`~/.gemini/antigravity-cli`) and the IDE. A conversation is placed by the
  CLI log of the run that created it, then `history.jsonl`, then
  `conversation_summaries.db`, then the workspace the conversation records
  itself; one that none of them places is held back, and a run that finds
  any of the repository's conversations says how many were. The IDE's older
  encrypted `.pb` conversations are not read.

- Every token source has a colour of its own on the token chart, whichever
  other sources a repository has logs from. A source this version does not
  know takes a colour no known source uses.

- The page's footer names the clocwork build that rendered it
  (`by clocwork 0.2.0`, plus the commit when run from a clone), and
  `full_commit_data.json` records the build that analysed it as
  `summary.analysed_by`.

- The dashboard has a light and a dark theme, Solarized Light and Solarized
  Dark. A switch at the top right picks light, dark or the system's setting,
  which is the default; the browser keeps the choice. Text reads at 4.5:1
  (WCAG AA) or better in both themes wherever it sits: on the page, on cards,
  in agent names and first-appearance labels, in tooltips and the explanatory
  note, and on selected or hovered controls.

- Token usage from OpenCode, read from `~/.local/share/opencode` on every
  system (`$XDG_DATA_HOME/opencode`, plus any database `OPENCODE_DB` names).
  All four of its storage layouts are read — the `opencode*.db` databases,
  the experimental `session_message` table for sessions only it holds, and
  the two file stores older releases wrote — and a record the migrations
  copied between them is counted once. Sessions are tied to the repository
  by the SHA-1 of `origin`, by the id OpenCode caches in the git directory,
  or by the directory they ran in; a forked session's copied messages are
  not counted again. Commits are credited to OpenCode when their trailer
  names it, and to a separate "OpenCode GitHub agent" when they come from
  `opencode-agent[bot]`, whose logs stay on the runner.

- Commits co-authored by Antigravity are recognised. It writes no trailer of
  its own, and the ones people add agree on nothing but the word itself, so a
  `Co-Authored-By:` trailer naming "Antigravity" in its display name or its
  address, by the whole-word rule under Changed, counts as Antigravity —
  before Gemini, since such a trailer often names the Gemini model that ran.
  A trailer that names a Claude model is still read as that model, as
  `Cursor (Claude Sonnet 4.5)` always has been.

### Changed

- An agent's name is matched as a whole word in a `Co-Authored-By:` trailer's
  display name or address local part, or as a whole label of its domain,
  rather than as a substring anywhere in the line. A contributor whose
  address is at a company called Antigravity Drones is no longer credited to
  Antigravity, and `Codexterous` is not Codex. A workspace's
  `[agents].extra` rows are matched by the same rule, so a short `match` no
  longer spreads across longer words, and the built-in names are tried first,
  so an extra names an agent the table does not know rather than renaming one
  it does. An `[agents].extra` row whose `match` or `name` is blank is now a
  configuration error; under the substring rule such a row matched every
  trailer, and under this one it would match none. Whitespace around a
  `match` is ignored.

- Only a trailer's own address is read as its address. A second one, in
  another pair of brackets or in a note (`(was jane@opencode.ai)`), is
  dropped, and a domain written in a note is judged label by label like the
  address's own, so `(see antigravity-drones.example)` no longer credits
  Antigravity while `(via opencode.ai)` still credits OpenCode. A note that
  names an agent in words (`(via Codex)`) still does, now after a bare
  address too.

- The dashboard's colours are Solarized's, in both themes, so agents,
  first-appearance lines and token sources have new hues. An agent's table
  badge now always takes that agent's chart colour. The main chart's line is
  the text colour, which no agent has, so no commit's point hides in it.
  Every agent keeps the same colour on every chart and in every run: a fixed
  one for the agents in the page's colour table, and for any other one taken
  from its name, which two agents can share.

- The AI-Assisted tile shows the commit count, with its share of all commits
  on the line below. A tile's value never wraps; one too long for its tile
  is set smaller.

- The HEAD snapshot counts every copy of an identical file, as the history
  always has. A repository that keeps copies of a file sees its lines at
  HEAD rise by those copies.

- Symlinks are no longer counted, nor is any path that was a symlink at some
  point, in any of its commits. cloc counted a symlink in the history only
  when it arrived with its target, so HEAD figures could disagree with the
  history.

- First-appearance labels are opaque, and are stacked in rows so that none
  covers another. A label with no row left takes its short form (`Opus 4.8`
  becomes `O4.8`), and is left off if that finds no room either.

- On a chart too narrow for every first-appearance label, labels are placed
  from the right, so the newest agents keep theirs and a label gives way to
  one that ends further right. A label left off shows while the pointer is
  within a few pixels of its line, or after a tap on it. Two labels whose
  short forms would read the same (`Opus 5`, `Omni 5`) are never shortened.

### Fixed

- A rename that changes language no longer shows as drift between the
  history and HEAD. Where cloc counts either name and the two differ in
  language (`notes.txt` to `notes.md`, or a page whose comment lines cloc
  counts as code under its new extension), the whole file now leaves the old
  name's language at the rename and arrives in the new one's, so the old name
  keeps its own language even when it is created again. A renamed file with
  no extension counts under the language cloc gives its content. In a
  history with renames this costs one more cloc run, over both sides of
  every rename; if that run fails, a warning says so and those renames drift
  as before.

- A file cloc names against its extension (`CMakeLists.txt`, a script by its
  shebang) counts under that name in every commit, where it used to show as
  drift.

- A `Co-Authored-By:` trailer is read from its own line. An empty one used to
  take the next line of the message as its value, so `Co-Authored-By:`
  followed by "Codex wrote the tests" credited Codex; it now credits no one.
  Reading trailers no longer slows with the square of the message's length
  when blank lines follow the last one.

- A file with no extension (`Makefile`, `Dockerfile`, a script with a
  shebang) that is still in the analysed branch, or was renamed into it,
  counts under the language cloc gives it in every commit, where it used to
  count as `Other` and show as drift.

- The original Claude Opus 4 is priced at its own list price, $15 and $75
  per million input and output tokens; it was priced at Opus 4.5's, a third
  of that. Opus 4.5 to 4.8 each have a row of their own.

- A model id spelled the way a router or a cloud writes it is priced:
  `openrouter/openai/gpt-5.5`, Bedrock's `us.anthropic.claude-…-v1:0`,
  Vertex's `claude-…@version`, and Claude Code's `[1m]` suffix. An id with
  a router suffix such as `:thinking` names another price and stays
  unpriced.

- A `GIT_DIR`, `GIT_WORK_TREE` or other repository-selecting variable
  inherited from a hook or a wrapper no longer points git or cloc at another
  repository.

- The page no longer scrolls sideways at phone widths or after the window
  is narrowed.

## [0.1.1] - 2026-09-17

### Added

- A Homebrew formula: `brew install nicktoumpelis/tap/clocwork` installs
  cloc and the manual page with it.
- The README shows the top of the dashboard.
- Releases reach PyPI from a GitHub Actions workflow with trusted
  publishing, which uploads the files attached to the GitHub release.

### Fixed

- On a GitHub or GitLab repository whose path contains `bitbucket.org`,
  commit links used Bitbucket's `/commits/` form, which opens the history
  from that commit rather than the commit. The form now follows the remote's
  host alone.

## [0.1.0] - 2026-09-16

First public release.

### Added

- `clocwork [REPO]`: analyses a git repository's whole history into a
  dashboard in a sibling workspace (`<repo>-stats`).
  - Every commit is measured with `cloc --git --diff`, cached per file, and
    reconciled against a `cloc` snapshot of HEAD.
  - `cloc` runs once per CPU core by default (`--jobs`), and
    `--max-commits` spreads a long history over several runs.
  - `cloc` 2.06 or later is required. An older one is refused, because it
    lists file extensions in a form clocwork misreads.
- Lines per language and per type (code, comment, blank) at every commit,
  and the test-code share at the tip of the analysed branch.
  - Built-in test-path rules cover common ecosystems.
  - `clocwork.toml` can add to the rules, exclude from them or replace them.
- AI-assisted commits, read from `Co-Authored-By` trailers, with the date
  each agent, and each Claude model, first appeared.
  - Any Claude model is recognised, as are Copilot, Cursor, Codex, Devin,
    aider, Gemini and Gemini Code Assist.
  - `[agents].extra` names anything else.
- Token usage from Claude Code, Codex CLI and Gemini CLI logs.
  - It is archived per day, agent and model in `token_usage.json`, which no
    run shrinks.
  - Days without logs are estimated from each agent's own tokens-per-line
    ratio.
  - Usage is priced at API list prices, and its electricity is estimated.
  - `clocwork tokens` archives without analysing, for use from cron.
- `clocwork render` re-renders an existing workspace.
- `clocwork.json` is a workspace identity guard: a run against a different
  repository is refused.
- Every number, date and unit on the page is formatted for a region locale.
- A `clocwork(1)` manual page.

[Unreleased]: https://github.com/nicktoumpelis/clocwork/compare/v0.2.0...HEAD
[0.2.0]: https://github.com/nicktoumpelis/clocwork/compare/v0.1.1...v0.2.0
[0.1.1]: https://github.com/nicktoumpelis/clocwork/releases/tag/v0.1.1
[0.1.0]: https://github.com/nicktoumpelis/clocwork/releases/tag/v0.1.0
