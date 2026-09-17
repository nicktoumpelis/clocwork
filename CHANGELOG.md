# Changelog

All notable changes to clocwork are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and versions follow
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Changed

- The HEAD snapshot counts every copy of an identical file, as the history
  always has. A repository that keeps copies of a file sees its lines at
  HEAD rise by those copies.
- Symlinks are no longer counted, nor is any path that was a symlink at some
  point, in any of its commits. cloc counted a symlink in the history only
  when it arrived with its target, so HEAD figures could disagree with the
  history.

### Fixed

- A renamed file's lines before the rename count under the language of its
  new name, unless the old name is used again later, and a file cloc names
  against its extension (`CMakeLists.txt`, a script by its shebang) counts
  under that name in every commit. Both used to show as drift between the
  history and HEAD.

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
