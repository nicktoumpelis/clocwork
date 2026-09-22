"""The clocwork command.

    clocwork [REPO]          analyse, archive tokens, render, open
    clocwork tokens [REPO]   archive agent token logs only
    clocwork render -o DIR   re-render the dashboard from workspace data

A first argument that is not a subcommand is the repository, so bare
`clocwork` and `clocwork ~/code/foo` both work. `tokens` is separate because
the two halves of the pipeline have opposite economics: the cloc pass is slow
and fully regenerable, the token archive is cheap and irreplaceable once an
agent deletes the logs it was read from (Claude Code keeps about 30 days).
"""

import argparse
import os
import pathlib
import sys
import webbrowser

from clocwork import __version__, analyse, cloc, config, paths, render, sources, tokens, ui

COMMANDS = ("run", "tokens", "render")
EXIT_ERROR = 2
EXIT_INTERRUPTED = 130


def non_negative(text):
    value = int(text)
    if value < 0:
        raise argparse.ArgumentTypeError(f"must be 0 or more, not {value}")
    return value


def positive(text):
    value = int(text)
    if value < 1:
        raise argparse.ArgumentTypeError(f"must be 1 or more, not {value}")
    return value


def build_parser():
    p = argparse.ArgumentParser(
        prog="clocwork",
        description="Lines per language, AI co-authored commits and token cost over a repository's history.")
    p.add_argument("--version", action="version", version=f"clocwork {__version__}")
    # Each command accepts only the options it acts on, so --help and the
    # manual page cannot promise an option that is silently ignored.
    quiet = argparse.ArgumentParser(add_help=False)
    loudness = quiet.add_mutually_exclusive_group()
    loudness.add_argument("-q", "--quiet", action="store_true", help="print nothing but errors")
    loudness.add_argument("-v", "--verbose", action="store_true", help="also print each step's details")
    page = argparse.ArgumentParser(add_help=False)
    page.add_argument("--config", metavar="PATH", help="explicit clocwork.toml")
    page.add_argument("--locale", metavar="TAG",
                      help="region locale for the page (default: $CLOCWORK_LOCALE, else the machine's region)")
    page.add_argument("--no-open", action="store_true", help="do not open the dashboard in a browser")
    workspace_help = "workspace directory (default: <repo-parent>/<repo-name>-stats)"
    repo_help = "repository or any directory inside it (default: cwd)"
    sub = p.add_subparsers(dest="command", metavar="COMMAND")
    run = sub.add_parser("run", parents=[quiet, page], help="analyse, archive tokens and render (the default)")
    run.add_argument("repo", nargs="?", metavar="REPO", help=repo_help)
    run.add_argument("-o", "--output", metavar="DIR", help=workspace_help)
    run.add_argument("--branch", metavar="REF", help="ref to analyse (default: the checked-out branch)")
    run.add_argument("--max-commits", type=non_negative, metavar="N", help="measure at most N uncached commits this run")
    run.add_argument("-j", "--jobs", type=positive, metavar="N",
                     help="cloc processes to run at once (default: one per CPU core)")
    run.add_argument("--no-tokens", action="store_true", help="skip the agent log scan")
    run.add_argument("--cache-dir", metavar="DIR",
                     help="cache location (default: $XDG_CACHE_HOME/clocwork, else ~/.cache/clocwork; wins over both)")
    tok = sub.add_parser("tokens", parents=[quiet], help="archive agent token logs only")
    tok.add_argument("repo", nargs="?", metavar="REPO", help=repo_help)
    tok.add_argument("-o", "--output", metavar="DIR", help=workspace_help)
    ren = sub.add_parser("render", parents=[quiet, page], help="re-render the dashboard from existing workspace data")
    ren.add_argument("-o", "--output", metavar="DIR", required=True, help="the workspace to render")
    return p


def parse_args(argv):
    argv = list(argv)
    if not argv or (argv[0] not in COMMANDS and argv[0] not in ("-h", "--help", "--version")):
        argv.insert(0, "run")
    args = build_parser().parse_args(argv)
    for name, default in (("repo", None), ("branch", None), ("max_commits", None), ("jobs", None),
                          ("no_tokens", False), ("cache_dir", None), ("config", None), ("locale", None),
                          ("no_open", False)):
        if not hasattr(args, name):
            setattr(args, name, default)
    return args


def _open(path, no_open):
    if not no_open:
        webbrowser.open(pathlib.Path(path).resolve().as_uri())


def _workspace_for(args, repo):
    return os.path.abspath(args.output) if args.output else paths.default_workspace(repo)


def cmd_render(args, report):
    ws = os.path.abspath(args.output)
    ident = paths.read_identity(ws)
    if ident is None:
        raise paths.WorkspaceMismatch(f"{ws} is not a clocwork workspace (no {paths.IDENTITY_FILE})")
    conf = config.load(args.config, ws, None)
    name = conf.title or ident["repo_name"]
    report.header(ident["repo_name"], ws, conf.source)
    with report.phase("Dashboard", 1, 1):
        html = render.render_workspace(ws, title=f"{name} - Full Commit History", repo_name=name,
                                       locale=args.locale or render.detect_locale(), report=report)
    report.finish(html)
    _open(html, args.no_open)


def cmd_tokens(args, report, homes):
    repo = paths.find_repo(args.repo or os.getcwd())
    ws = _workspace_for(args, repo)
    ident = paths.check_identity(ws, repo, __version__)
    report.header(ident["repo_name"], ws)
    with report.phase("Tokens", 1, 1):
        tokens.archive(repo, os.path.join(ws, "token_usage.json"), sources.SOURCES, homes=homes, report=report)
    report.finish()


def cmd_run(args, report, homes):
    cloc.require_cloc()
    repo = paths.find_repo(args.repo or os.getcwd())
    ws = _workspace_for(args, repo)
    ident = paths.check_identity(ws, repo, __version__)
    conf = config.load(args.config, ws, repo)
    report.header(ident["repo_name"], ws, conf.source)
    archive = os.path.join(ws, "token_usage.json")
    with report.phase("Tokens", 1, 3):
        if args.no_tokens:
            report.done("skipped (--no-tokens)")
        else:
            tokens.archive(repo, archive, sources.SOURCES, homes=homes, report=report)
    with report.phase("History", 2, 3):
        analyse.analyse(repo, os.path.join(ws, "full_commit_data.json"), paths.cache_path(repo, args.cache_dir),
                        archive, config=conf, branch=args.branch, max_commits=args.max_commits,
                        jobs=args.jobs or os.cpu_count() or 1, report=report)
    name = conf.title or ident["repo_name"]
    with report.phase("Dashboard", 3, 3):
        html = render.render_workspace(ws, title=f"{name} - Full Commit History", repo_name=name,
                                       locale=args.locale or render.detect_locale(), report=report)
    report.finish(html)
    _open(html, args.no_open)


def main(argv=None, homes=None):
    """`homes` maps a token source's key to the directories to read instead
    of its defaults; the tests use it to keep real agent logs out."""
    args = parse_args(sys.argv[1:] if argv is None else argv)
    report = ui.choose(args.quiet, args.verbose)
    try:
        if args.command == "render":
            cmd_render(args, report)
        elif args.command == "tokens":
            cmd_tokens(args, report, homes)
        else:
            cmd_run(args, report, homes)
    except KeyboardInterrupt:
        # The phase has already finished its line; the cloc cache is saved.
        report.error("interrupted")
        return EXIT_INTERRUPTED
    except (cloc.ClocMissing, cloc.ClocError, paths.NotARepository, paths.WorkspaceMismatch,
            config.ConfigError, analyse.NoCommits, tokens.ArchiveError, OSError) as e:
        report.error(str(e))
        return EXIT_ERROR
    return 0
