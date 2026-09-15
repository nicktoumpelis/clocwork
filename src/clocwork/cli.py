"""The clocwork command.

    clocwork [REPO]          analyse, archive tokens, render, open
    clocwork tokens [REPO]   archive Claude Code transcripts only
    clocwork render -o DIR   re-render the dashboard from workspace data

A first argument that is not a subcommand is the repository, so bare
`clocwork` and `clocwork ~/code/foo` both work. `tokens` is separate because
the two halves of the pipeline have opposite economics: the cloc pass is slow
and fully regenerable, the transcript archive is cheap and irreplaceable
within Claude Code's roughly 30-day retention window.
"""

import argparse
import os
import pathlib
import sys
import webbrowser

from clocwork import __version__, analyse, cloc, config, paths, render, tokens

COMMANDS = ("run", "tokens", "render")
EXIT_ERROR = 2


def non_negative(text):
    value = int(text)
    if value < 0:
        raise argparse.ArgumentTypeError(f"must be 0 or more, not {value}")
    return value


def build_parser():
    p = argparse.ArgumentParser(
        prog="clocwork",
        description="Lines per language, AI co-authored commits and token cost over a repository's history.")
    p.add_argument("--version", action="version", version=f"clocwork {__version__}")
    # Each command accepts only the options it acts on, so --help and the
    # manual page cannot promise an option that is silently ignored.
    quiet = argparse.ArgumentParser(add_help=False)
    quiet.add_argument("-q", "--quiet", action="store_true", help="print nothing but errors")
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
    run.add_argument("--no-tokens", action="store_true", help="skip the transcript scan")
    run.add_argument("--cache-dir", metavar="DIR",
                     help="cache location (default: $XDG_CACHE_HOME/clocwork, else ~/.cache/clocwork; wins over both)")
    tok = sub.add_parser("tokens", parents=[quiet], help="archive Claude Code transcripts only")
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
    for name, default in (("repo", None), ("branch", None), ("max_commits", None), ("no_tokens", False),
                          ("cache_dir", None), ("config", None), ("locale", None), ("no_open", False)):
        if not hasattr(args, name):
            setattr(args, name, default)
    return args


def _quiet(*args, **kwargs):
    pass


def _progress(*args, **kwargs):
    # Flushed per line: an hour-long run piped to a log file (cron, nohup)
    # would otherwise show nothing until it ends.
    print(*args, **kwargs, flush=True)


def _log(quiet):
    return _quiet if quiet else _progress


def _open(path, no_open):
    if not no_open:
        webbrowser.open(pathlib.Path(path).resolve().as_uri())


def _workspace_for(args, repo):
    return os.path.abspath(args.output) if args.output else paths.default_workspace(repo)


def cmd_render(args, log):
    ws = os.path.abspath(args.output)
    ident = paths.read_identity(ws)
    if ident is None:
        raise paths.WorkspaceMismatch(f"{ws} is not a clocwork workspace (no {paths.IDENTITY_FILE})")
    conf = config.load(args.config, ws, None)
    name = conf.title or ident["repo_name"]
    html = render.render_workspace(ws, title=f"{name} - Full Commit History", repo_name=name,
                                   locale=args.locale or render.detect_locale(), log=log)
    _open(html, args.no_open)


def cmd_tokens(args, log, projects_dir):
    repo = paths.find_repo(args.repo or os.getcwd())
    ws = _workspace_for(args, repo)
    paths.check_identity(ws, repo, __version__)
    tokens.archive(repo, os.path.join(ws, "token_usage.json"), projects_dir=projects_dir, log=log)


def cmd_run(args, log, projects_dir):
    cloc.require_cloc()
    repo = paths.find_repo(args.repo or os.getcwd())
    ws = _workspace_for(args, repo)
    ident = paths.check_identity(ws, repo, __version__)
    conf = config.load(args.config, ws, repo)
    if conf.source:
        log(f"Config: {conf.source}")
    archive = os.path.join(ws, "token_usage.json")
    if args.no_tokens:
        log("Step 1/3: Skipping the transcript scan (--no-tokens)")
    else:
        log("Step 1/3: Archiving token usage from Claude Code transcripts...")
        tokens.archive(repo, archive, projects_dir=projects_dir, log=log)
    log("Step 2/3: Analysing commit history...")
    analyse.analyse(repo, os.path.join(ws, "full_commit_data.json"), paths.cache_path(repo, args.cache_dir),
                    archive, config=conf, branch=args.branch, max_commits=args.max_commits, log=log)
    log("Step 3/3: Rendering the dashboard...")
    name = conf.title or ident["repo_name"]
    html = render.render_workspace(ws, title=f"{name} - Full Commit History", repo_name=name,
                                   locale=args.locale or render.detect_locale(), log=log)
    log(f"Open: {html}")
    _open(html, args.no_open)


def main(argv=None, projects_dir=tokens.PROJECTS_DIR):
    args = parse_args(sys.argv[1:] if argv is None else argv)
    log = _log(args.quiet)
    try:
        if args.command == "render":
            cmd_render(args, log)
        elif args.command == "tokens":
            cmd_tokens(args, log, projects_dir)
        else:
            cmd_run(args, log, projects_dir)
    except (cloc.ClocMissing, cloc.ClocError, paths.NotARepository, paths.WorkspaceMismatch,
            config.ConfigError, analyse.NoCommits, OSError) as e:
        print(f"clocwork: {e}", file=sys.stderr)
        return EXIT_ERROR
    return 0
