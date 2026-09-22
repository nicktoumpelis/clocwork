"""The clocwork(1) manual page, generated from the argparse parsers.

    PYTHONPATH=src python3 -m clocwork.manpage > man/clocwork.1

The page is committed rather than built at install time because pip has no
portable way to install a manual page; a clone reads it with
`man ./man/clocwork.1`, and a package manager formula can install the file
(the release spec's Homebrew channel will). A test regenerates the page and
compares it with the committed one, so a change to the help text or the
version that is not followed by the command above fails the suite.
Everything a parser knows - commands, options, defaults - comes from the
parser; the sections argparse cannot know (ENVIRONMENT, FILES, EXIT STATUS)
are written here, next to the code they describe.
"""

import argparse
import sys
from datetime import date as _date

from clocwork import __version__
from clocwork.cli import EXIT_ERROR, build_parser


def escape(text):
    """Text safe inside roff: backslashes and hyphens escaped, a leading
    request character neutralised."""
    text = text.replace("\\", "\\\\").replace("-", "\\-")
    if text.startswith((".", "'")):
        text = "\\&" + text
    return text


def _subcommands(parser):
    action = next(a for a in parser._actions if isinstance(a, argparse._SubParsersAction))
    return action.choices


def _synopsis(name, sub):
    """The usage line of one subcommand, as a bold command with its arguments."""
    usage = sub.format_usage().split(":", 1)[1].split()   # drop "usage:"
    words = [escape(w) for w in usage[2:] if w != "[-h]"]   # drop "clocwork", the command, and -h
    return f".B clocwork {name}\n" + (" ".join(words) + "\n" if words else "")


def _key(action):
    """What makes two options the same option: flags and help text."""
    return tuple(action.option_strings), action.help


def _entry(action, note=""):
    """One .TP entry. `note` is a sentence appended to the help; the help gets
    a full stop first unless it already ends with one."""
    metavar = action.metavar or action.dest.upper()
    text = action.help or ""
    if note and text.strip():
        text = text.rstrip() + ("" if text.rstrip().endswith(".") else ".") + " " + note
    elif note:
        text = note
    if action.option_strings:
        flags = ", ".join(escape(o) for o in action.option_strings)
        if action.nargs != 0:                 # takes a value; store_true has nargs 0
            flags += " " + escape(metavar)
        return f".TP\n.B {flags}\n{escape(text)}\n"
    return f".TP\n.I {escape(metavar)}\n{escape(text)}\n"


def _shared(subs):
    """Options that more than one command takes, in first-seen order,
    each with the commands that take it."""
    seen = {}
    for name, sub in subs.items():
        for action in sub._actions:
            if action.option_strings and "--help" not in action.option_strings:
                seen.setdefault(_key(action), (action, []))[1].append(name)
    return {key: pair for key, pair in seen.items() if len(pair[1]) > 1}


def _shared_options(subs):
    """The OPTIONS section: each shared option once, naming its commands
    unless every command takes it."""
    out = []
    for action, names in _shared(subs).values():
        if len(names) == len(subs):
            note = ""
        else:
            listed = names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]
            note = f"Taken by {listed}."
        out.append(_entry(action, note))
    return "".join(out).rstrip("\n")


def _options(sub, shared=()):
    """A command's own entries: positionals first, then the options no other
    command shares, each in declaration order."""
    positionals, options = [], []
    for action in sub._actions:
        if "--help" in action.option_strings:
            continue
        if action.option_strings:
            if _key(action) not in shared:
                options.append(_entry(action))
        else:
            positionals.append(_entry(action))
    return "".join(positionals + options)


def render(parser=None, version=__version__, date=None):
    parser = parser or build_parser()
    date = date or _date.today().isoformat()
    subs = _subcommands(parser)
    lines = [f'.TH CLOCWORK 1 "{date}" "clocwork {version}" "User Commands"']
    lines.append(".SH NAME\nclocwork \\- lines per language, AI co\\-authored commits and token cost over a repository's history")
    lines.append(".SH SYNOPSIS\n" + "\n.br\n".join(
        [".B clocwork\n[\\fIOPTIONS\\fR] [\\fIREPO\\fR]"] +
        [_synopsis(name, sub).rstrip("\n") for name, sub in subs.items() if name != "run"] +
        [".B clocwork \\-\\-version"]))
    lines.append(".SH DESCRIPTION\n" + escape(parser.description) + "\n.PP\n"
                 "Every non\\-merge commit reachable from the analysed ref is measured with\n"
                 ".BR cloc (1)\n"
                 "in git diff mode and cached per file, so a first run over a long history is slow and every later run takes seconds; "
                 "merge commits carry no code of their own and are listed but not measured. The result is one\n.I index.html\n"
                 "(its charts load Chart.js and its plugins from a CDN) plus a\n.I commit_bodies.js\nsidecar, "
                 "written to a workspace next to the repository, never inside it: lines per language and type at every commit, "
                 "which commits an AI agent co\\-authored and when each model first appeared, and, when a coding agent's logs "
                 "for the repository are on the machine (Claude Code, Codex CLI, Copilot CLI, Gemini CLI, Kilo Code, OpenCode, Qwen Code), what the work cost in tokens.\n.PP\n"
                 "A first argument that is not a command is taken as\n.IR REPO ,\nso\n.B clocwork ~/code/foo\nworks; "
                 "the default is the current directory, and any directory inside the repository will do.")
    lines.append(".SH OPTIONS\nOptions more than one command takes. Each command's own options follow it below.\n"
                 + _shared_options(subs))
    shared = _shared(subs)
    commands = [".SH COMMANDS"]
    for name, sub in subs.items():
        commands.append((f".SS {name}\n" + _synopsis(name, sub) + ".PP\n" + escape(_help_of(parser, name)) + "\n"
                         + _options(sub, shared)).rstrip("\n"))
    lines.append("\n".join(commands))
    lines.append(".SH ENVIRONMENT\n"
                 ".TP\n.B CLOCWORK_LOCALE\nA BCP 47 tag such as\n.BR en\\-SE .\n"
                 "The region locale the page formats numbers, dates and units with. Wins over the machine's setting;\n"
                 ".B \\-\\-locale\nwins over both.\n"
                 ".TP\n.B CODEX_HOME\nWhere Codex CLI keeps its sessions, read from its\n.I sessions/\nand\n.I archived_sessions/\ndirectories; the default is\n.IR ~/.codex .\n"
                 ".TP\n.B COPILOT_HOME\nWhere Copilot CLI keeps its sessions, read from the\n.I events.jsonl\nin each directory below\n.IR session-state/\nand from\n.IR session-store.db ;\nthe default is\n.IR ~/.copilot .\n"
                 ".TP\n.B GEMINI_CLI_HOME\nThe directory Gemini CLI uses in place of the home directory; its sessions are read from\n.I .gemini/tmp/\nand\n.I .cache/.gemini/tmp/\nbelow it.\n"
                 ".TP\n.B KILO_DB\nA Kilo Code database to read besides every\n.I kilo*.db\nand\n.I opencode\\-*.db\nin its data directory; absolute, or relative to that directory.\n"
                 ".TP\n.B OPENCODE_DB\nAn OpenCode database to read besides every\n.I opencode*.db\nin its data directory; absolute, or relative to that directory.\n"
                 ".TP\n.B QWEN_HOME\nWhere Qwen Code keeps its sessions, read from\n.I projects/*/chats/\nand\n.I tmp/\nbelow it; the default is\n.IR ~/.qwen .\n"
                 ".TP\n.B QWEN_RUNTIME_DIR\nA further directory Qwen Code writes its sessions to, read as\n.B QWEN_HOME\nis.\n"
                 ".TP\n.B QWEN_CODE_SYSTEM_SETTINGS_PATH\nQwen Code's system settings file, whose\n.B advanced.runtimeOutputDir\nsetting, like the user's and the repository's, can name a further directory for its sessions.\n"
                 ".TP\n.B QWEN_CODE_SYSTEM_DEFAULTS_PATH\nQwen Code's system defaults file, read the same way.\n"
                 ".TP\n.B XDG_CACHE_HOME\nWhen set, the cloc cache lives under\n.IR $XDG_CACHE_HOME/clocwork/ ;\notherwise under\n.IR ~/.cache/clocwork/ .\n"
                 ".B \\-\\-cache\\-dir\nwins over both. Only\n.B run\nuses the cache.\n"
                 ".TP\n.B XDG_DATA_HOME\nWhere OpenCode and Kilo Code keep their sessions, read from\n.I opencode/\nand\n.I kilo/\nbelow it; the default is\n.I ~/.local/share\non every system, neither having a variable of its own.")
    lines.append(".SH FILES\n"
                 ".TP\n.I <repo\\-parent>/<repo\\-name>\\-stats/\nThe workspace: a sibling of the repository, overridden with\n.BR \\-o .\n"
                 ".TP\n.I clocwork.json\nWhich repository the workspace belongs to. A run against another repository is refused rather than overwriting the workspace.\n"
                 ".TP\n.I clocwork.toml\nOptional configuration: page title, test\\-path rules, extra agents. The first found wins:\n"
                 ".BR \\-\\-config ,\nthen this file in the workspace, then\n.I .clocwork.toml\nin the repository.\n"
                 ".TP\n.I token_usage.json\nThe per\\-day token archive, kept per agent, read from coding agents' logs. It cannot be regenerated once the logs expire; no run shrinks it.\n"
                 ".TP\n.I full_commit_data.json\nThe analysis the page is rendered from, with the clocwork version that made it, and its commit when run from a clone. The page's footer names the build that rendered it.\n"
                 ".TP\n.IR index.html \", \" commit_bodies.js\nThe dashboard and its sidecar of full commit messages.\n"
                 ".TP\n.I ~/.cache/clocwork/<name>\\-<hash>/cloc_cache.json\nPer\\-file cloc results keyed by commit, so a changed test rule or language table re\\-reads the cache instead of re\\-running cloc.")
    lines.append(".SH EXIT STATUS\n.TP\n.B 0\nSuccess.\n"
                 f".TP\n.B {EXIT_ERROR}\nAn error the command reported: Python older than 3.11, cloc missing, older than 2.06 or failing, no git repository, a repository with no commits, "
                 "a workspace belonging to another repository, invalid configuration, or an unreadable, unwritable or corrupt file. "
                 "A usage error also exits 2, with the usage line on standard error.")
    lines.append(".SH SEE ALSO\n.BR cloc (1),\n.BR git (1),\n.BR git\\-log (1)")
    return "\n".join(lines) + "\n"


def _help_of(parser, name):
    action = next(a for a in parser._actions if isinstance(a, argparse._SubParsersAction))
    for choice in action._choices_actions:
        if choice.dest == name:
            return choice.help or ""
    return ""


def main():
    sys.stdout.write(render())
    return 0


if __name__ == "__main__":
    sys.exit(main())
