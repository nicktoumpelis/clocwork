"""The clocwork(1) manual page, generated from the argparse parsers.

    python3 -m clocwork.manpage > man/clocwork.1

The page is committed rather than built at install time because pip has no
portable way to install a manual page; a clone reads it with
`man ./man/clocwork.1`, and the Homebrew formula will install it. A test
regenerates the page and compares it with the committed one, so a change to
the help text that is not followed by the command above fails the suite.
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


def _options(sub):
    """Positionals first, then options, each in declaration order."""
    positionals, options = [], []
    for action in sub._actions:
        if "--help" in action.option_strings:
            continue
        metavar = action.metavar or action.dest.upper()
        if action.option_strings:
            flags = ", ".join(escape(o) for o in action.option_strings)
            if action.nargs != 0:                 # takes a value; store_true has nargs 0
                flags += " " + escape(metavar)
            options.append(f".TP\n.B {flags}\n{escape(action.help or '')}\n")
        else:
            positionals.append(f".TP\n.I {escape(metavar)}\n{escape(action.help or '')}\n")
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
                 "Every commit reachable from the analysed ref is measured with\n"
                 ".BR cloc (1)\n"
                 "in git diff mode and cached per file, so a first run over a long history is slow and every later run takes seconds. "
                 "The result is a self\\-contained\n.I index.html\n"
                 "written to a workspace next to the repository, never inside it: lines per language and type at every commit, "
                 "which commits an AI agent co\\-authored and when each model first appeared, and, when Claude Code transcripts "
                 "exist for the repository, what the work cost in tokens.\n.PP\n"
                 "A first argument that is not a command is taken as\n.IR REPO ,\nso\n.B clocwork ~/code/foo\nworks; "
                 "the default is the current directory, and any directory inside the repository will do.")
    commands = [".SH COMMANDS"]
    for name, sub in subs.items():
        commands.append((f".SS {name}\n" + _synopsis(name, sub) + ".PP\n" + escape(_help_of(parser, name)) + "\n" + _options(sub)).rstrip("\n"))
    lines.append("\n".join(commands))
    lines.append(".SH ENVIRONMENT\n"
                 ".TP\n.B CLOCWORK_LOCALE\nA BCP 47 tag such as\n.BR en\\-SE .\n"
                 "The region locale the page formats numbers, dates and units with. Wins over the machine's setting;\n"
                 ".B \\-\\-locale\nwins over both.\n"
                 ".TP\n.B XDG_CACHE_HOME\nWhen set, the cloc cache lives under\n.IR $XDG_CACHE_HOME/clocwork/ ;\notherwise under\n.IR ~/.cache/clocwork/ .")
    lines.append(".SH FILES\n"
                 ".TP\n.I <repo\\-parent>/<repo\\-name>\\-stats/\nThe workspace: a sibling of the repository, overridden with\n.BR \\-o .\n"
                 ".TP\n.I clocwork.json\nWhich repository the workspace belongs to. A run against another repository is refused rather than overwriting the workspace.\n"
                 ".TP\n.I clocwork.toml\nOptional configuration: page title, test\\-path rules, extra agents. The first found wins:\n"
                 ".BR \\-\\-config ,\nthen this file in the workspace, then\n.I .clocwork.toml\nin the repository.\n"
                 ".TP\n.I token_usage.json\nThe per\\-day token archive scanned from Claude Code transcripts. It cannot be regenerated once the transcripts expire; no run shrinks it.\n"
                 ".TP\n.I full_commit_data.json\nThe analysis the page is rendered from.\n"
                 ".TP\n.IR index.html \", \" commit_bodies.js\nThe dashboard and its sidecar of full commit messages.\n"
                 ".TP\n.I ~/.cache/clocwork/<name>\\-<hash>/cloc_cache.json\nPer\\-file cloc results keyed by commit, so a changed test rule or language table re\\-reads the cache instead of re\\-running cloc.")
    lines.append(".SH EXIT STATUS\n.TP\n.B 0\nSuccess.\n"
                 f".TP\n.B {EXIT_ERROR}\nAn error the command reported: cloc missing, no git repository, a repository with no commits, "
                 "a workspace belonging to another repository, invalid configuration, or an unreadable or unwritable file. "
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
