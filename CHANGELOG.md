# Changelog

All notable changes to clocwork are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

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
  address counts as Antigravity — before Gemini, since such a trailer often
  names the Gemini model that ran. A trailer that names a Claude model is
  still read as that model, as `Cursor (Claude Sonnet 4.5)` always has been.
  Antigravity's token usage is not read yet.

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

- The HEAD snapshot counts every copy of an identical file, as the history
  always has. A repository that keeps copies of a file sees its lines at
  HEAD rise by those copies.
- Symlinks are no longer counted, nor is any path that was a symlink at some
  point, in any of its commits. cloc counted a symlink in the history only
  when it arrived with its target, so HEAD figures could disagree with the
  history.
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

[Unreleased]: https://github.com/nicktoumpelis/clocwork/compare/v0.1.1...HEAD
[0.1.1]: https://github.com/nicktoumpelis/clocwork/releases/tag/v0.1.1
[0.1.0]: https://github.com/nicktoumpelis/clocwork/releases/tag/v0.1.0
