"""Where things are: the repository, the workspace, the cache, and identity.

Two path encodings live here and must not be merged. claude_project_dir()
mirrors Claude Code's own directory naming so transcripts can be found; it
tracks an external tool and may have to change when that tool changes.
cache_key() is clocwork's own, so an upstream change to Claude Code's scheme
cannot silently relocate every cache directory and trigger hour-long
re-analyses across every repository.
"""

import hashlib
import json
import os
import re
import subprocess
import tempfile
from datetime import datetime, timezone

IDENTITY_FILE = "clocwork.json"

_HOSTS = ("github.com", "gitlab.com", "bitbucket.org")
# scp-like (git@host:path) and URL (scheme://[user@]host[:port]/path) remotes.
_SCP = re.compile(r"^(?:[^@/]+@)?(?P<host>[^:/]+):(?P<path>[^/].*)$")
_URL = re.compile(r"^(?:https?|ssh|git)://(?:[^@/]+@)?(?P<host>[^/:]+)(?::\d+)?/(?P<path>.+)$")


class NotARepository(RuntimeError):
    pass


class WorkspaceMismatch(RuntimeError):
    pass


# What git clears before it runs in another repository (`git rev-parse
# --local-env-vars`), less the `git -c` settings, which it passes on to a
# submodule too. Inherited from a hook or a wrapper, GIT_DIR and its kin name
# a repository of their own and override `git -C`, and cloc's working
# directory, so every git and cloc call runs without them.
REPOSITORY_ENV = ("GIT_ALTERNATE_OBJECT_DIRECTORIES", "GIT_CONFIG", "GIT_OBJECT_DIRECTORY", "GIT_DIR",
                  "GIT_WORK_TREE", "GIT_IMPLICIT_WORK_TREE", "GIT_GRAFT_FILE", "GIT_INDEX_FILE",
                  "GIT_NO_REPLACE_OBJECTS", "GIT_REPLACE_REF_BASE", "GIT_PREFIX", "GIT_SHALLOW_FILE",
                  "GIT_COMMON_DIR")


def git_env(**extra):
    """This process's environment for a git or cloc run against a repository
    named by path, plus `extra`."""
    env = {k: v for k, v in os.environ.items() if k not in REPOSITORY_ENV}
    env.update(extra)
    return env


def _git(cwd, *args):
    result = subprocess.run(["git", "-C", cwd] + list(args), capture_output=True, text=True, env=git_env())
    return result.returncode, result.stdout.strip()


def build():
    """Which clocwork is running: its version, and its commit when the
    package is `src/clocwork` in a clone (the shim's case), with "-dirty"
    when tracked files have changed. An installed build (wheel, zipapp,
    Homebrew) has no commit of its own to name, and a checkout that merely
    contains an installed package, such as a project's virtualenv, is not
    clocwork's, so both report None."""
    from clocwork import __version__
    package = os.path.dirname(os.path.realpath(__file__))
    commit = None
    try:
        code, top = _git(package, "rev-parse", "--show-toplevel")
        # samefile, not a string comparison: macOS paths match whatever
        # their letter case, and realpath does not normalise it.
        if code == 0 and top and os.path.samefile(os.path.join(top, "src", "clocwork"), package):
            code, sha = _git(top, "rev-parse", "--short", "HEAD")
            if code == 0 and sha:
                # No optional locks: the checkout may be in iCloud Drive, and a
                # status that refreshes the index writes to it.
                code, changed = _git(top, "--no-optional-locks", "status", "--porcelain",
                                     "--untracked-files=no", "--ignore-submodules")
                if code == 0:
                    commit = sha + ("-dirty" if changed else "")
    # OSError: no git, or no src/clocwork beside the top level. ValueError:
    # git output that is not text in this locale. Neither may stop a run.
    except (OSError, ValueError):
        pass
    return {"version": __version__, "commit": commit}


def find_repo(start):
    """The top-level directory of the repository containing `start`."""
    start = os.path.abspath(start)
    if not os.path.isdir(start):
        raise NotARepository(f"{start} is not a directory")
    code, top = _git(start, "rev-parse", "--show-toplevel")
    if code != 0 or not top:
        raise NotARepository(f"no git repository found at or above {start}")
    return os.path.realpath(top)


def default_workspace(repo):
    """A sibling of the repository, never inside it: ~/code/foo -> ~/code/foo-stats."""
    repo = os.path.abspath(repo).rstrip(os.sep)
    return os.path.join(os.path.dirname(repo), os.path.basename(repo) + "-stats")


def claude_project_dir(repo):
    """Claude Code's directory name for a repository: the absolute path with
    every non-alphanumeric character replaced by a hyphen, one for one."""
    return re.sub(r"[^a-zA-Z0-9]", "-", os.path.abspath(repo))


def cache_key(repo):
    """<basename>-<sha256(abspath)[:12]>: readable, and unique across same-named repositories."""
    path = os.path.abspath(repo).rstrip(os.sep)
    digest = hashlib.sha256(path.encode("utf-8")).hexdigest()[:12]
    return f"{os.path.basename(path)}-{digest}"


def cache_root(override=None, env=os.environ):
    if override:
        return override
    xdg = env.get("XDG_CACHE_HOME")
    if xdg:
        return os.path.join(xdg, "clocwork")
    return os.path.expanduser("~/.cache/clocwork")


def cache_path(repo, override=None, env=os.environ):
    return os.path.join(cache_root(override, env), cache_key(repo), "cloc_cache.json")


def parse_remote(remote):
    """(host, path) from a git remote in scp or URL form, or None.

    The host is lower-cased and a trailing .git or slash is dropped, so the
    same repository reached two ways compares equal. GitLab subgroup paths
    are kept whole.
    """
    m = _URL.match(remote) or _SCP.match(remote)
    if not m:
        return None
    path = m.group("path").rstrip("/").removesuffix(".git").rstrip("/")
    if "/" not in path:
        return None          # a repository is owner/name at least
    return m.group("host").lower(), path


def remote_key(repo):
    """host/path of origin for any host, or None: the identity of a repository."""
    code, remote = _git(repo, "remote", "get-url", "origin")
    parsed = parse_remote(remote) if code == 0 and remote else None
    return f"{parsed[0]}/{parsed[1]}" if parsed else None


def remote_url(repo):
    """The https URL of origin when it is on a host whose commit URLs the
    page knows, else None: commit links are omitted rather than broken."""
    key = remote_key(repo)
    if key and key.split("/", 1)[0] in _HOSTS:
        return "https://" + key
    return None


def identity(repo, version):
    repo = os.path.realpath(repo)
    return {
        "version": version,
        "repo_remote": remote_url(repo) or remote_key(repo),
        "repo_path": repo,
        "repo_name": os.path.basename(repo),
        "generated": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    }


def read_identity(workspace):
    path = os.path.join(workspace, IDENTITY_FILE)
    if not os.path.exists(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            ident = json.load(f)
    except ValueError as e:
        raise WorkspaceMismatch(f"{path} is not valid JSON ({e}); fix or remove it") from None
    if not isinstance(ident, dict) or not isinstance(ident.get("repo_name"), str):
        raise WorkspaceMismatch(f"{path} does not name a repository (no repo_name); fix or remove it")
    return ident


def _norm_remote(value):
    return re.sub(r"^https?://", "", value).lower() if value else None


def _same(existing, current):
    if existing.get("repo_remote") and current["repo_remote"]:
        return _norm_remote(existing["repo_remote"]) == _norm_remote(current["repo_remote"])
    return existing.get("repo_path") == current["repo_path"]


def worktrees(repo):
    """Every working tree git lists for the repository, the main one first,
    as absolute paths; [] when git cannot list them."""
    code, out = _git(repo, "worktree", "list", "--porcelain")
    if code != 0:
        return []
    return [line[len("worktree "):] for line in out.splitlines() if line.startswith("worktree ")]


def worktree_created(repo, path):
    """The UTC date the repository's linked worktree at `path` was added, or
    None when it cannot be told. git writes the worktree's `commondir` file
    once, when the worktree is added, so its modification time is the
    creation time. The worktree's admin directory is found from the
    repository's side, by the `gitdir` file naming `path`, so a worktree
    whose directory is already gone still has its date."""
    code, common = _git(repo, "rev-parse", "--git-common-dir")
    if code != 0:
        return None
    admin_root = os.path.join(repo, common, "worktrees")   # join keeps an absolute `common` as it is
    target = os.path.realpath(path)
    try:
        names = os.listdir(admin_root)
    except OSError:
        return None
    for name in names:
        try:
            with open(os.path.join(admin_root, name, "gitdir"), encoding="utf-8") as f:
                listed = os.path.dirname(f.read().strip())
            if os.path.realpath(listed) == target:
                mtime = os.stat(os.path.join(admin_root, name, "commondir")).st_mtime
                return datetime.fromtimestamp(mtime, timezone.utc).strftime("%Y-%m-%d")
        except OSError:
            continue
    return None


def _session_entry(value):
    """A valid session_paths entry, or None: an absolute path with an
    optional first and last day, each 'YYYY-MM-DD' or null."""
    if not isinstance(value, dict) or not isinstance(value.get("path"), str) or not os.path.isabs(value["path"]):
        return None
    bounds = {k: value.get(k) for k in ("since", "until")}
    if any(v is not None and not (isinstance(v, str) and re.fullmatch(r"[0-9]{4}-[0-9]{2}-[0-9]{2}", v))
           for v in bounds.values()):
        return None
    return {"path": value["path"], **bounds}


def _write_identity(workspace, ident):
    """Replace the identity file whole: a reader never sees half of it."""
    path = os.path.join(workspace, IDENTITY_FILE)
    fd, tmp = tempfile.mkstemp(dir=workspace, prefix=".clocwork.", suffix=".json")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(ident, f, indent=2)
            f.write("\n")
        os.chmod(tmp, 0o644)
        os.replace(tmp, path)
    except BaseException:
        os.unlink(tmp)
        raise


def remember_session_paths(workspace, repo, today=None):
    """Every directory the repository's agent sessions may have run in, with
    the days it belonged to the repository, kept in the workspace's identity
    file as `session_paths` and returned.

    Claude Code files a session under the path it was started in, so a
    session in a linked worktree, or one from before the repository moved,
    is under a path other than the repository's own. Each entry is
    {"path", "since", "until"}: the first and last UTC day whose sessions
    count, null for no bound.

    - The repository's current path, and the main checkout when run from a
      linked worktree, are unbounded.
    - A linked worktree git lists is added from the day it was created
      (worktree_created; the day it was first seen when that cannot be
      told), so its path's sessions from before then add nothing.
    - Any path, the repository's own included, that a run no longer finds
      live gets `until` set to that run's day: sessions filed there later
      add nothing, while those between the move or removal and that run
      still count.
    - A workspace without the list starts it from `repo_path`, the path it
      was made for: when that is not the current path, the repository has
      moved, and the old path counts up to today.

    Only git's own list and the recorded repo_path ever enter it, so a
    sibling directory that merely shares a name never does. An entry that is
    not an absolute path with valid days is dropped; the rest are kept. The
    file is rewritten, whole, only when the list changes.
    """
    today = today or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    ident = read_identity(workspace) or {}
    stored = ident.get("session_paths")
    entries = [e for e in map(_session_entry, stored) if e] if isinstance(stored, list) else []
    here = os.path.realpath(repo)
    if not isinstance(stored, list):
        old = ident.get("repo_path")
        if isinstance(old, str) and os.path.isabs(old) and old != here:
            entries.append({"path": old, "since": None, "until": None})   # closed below: not live
    live = {here: None}
    for i, path in enumerate(worktrees(repo)):
        if path not in live:
            # git lists the main checkout first: run from a linked worktree,
            # it is the repository itself, not a worktree with a start.
            live[path] = None if i == 0 else worktree_created(repo, path) or today
    by_path = {e["path"]: e for e in entries}
    for path, since in live.items():
        entry = by_path.get(path)
        if entry is None:
            entries.append({"path": path, "since": since, "until": None})
        elif entry["until"] is not None:
            # Back in git's list: a new worktree at an old path, or the
            # repository moved back. The days in between were not its.
            entry.update(since=since, until=None)
    for entry in entries:
        if entry["path"] not in live and entry["until"] is None:
            entry["until"] = today
    if entries != stored:
        ident["session_paths"] = entries
        _write_identity(workspace, ident)
    return entries


def check_identity(workspace, repo, version):
    """Refuse to run a workspace against a repository other than its own.

    The workspace holds token_usage.json, the one file that cannot be
    regenerated, so no ordinary mistake may overwrite it with another
    repository's data. The remote URL is compared first, the absolute path
    only when there is no remote.
    """
    current = identity(repo, version)
    existing = read_identity(workspace)
    if existing is None:
        os.makedirs(workspace, exist_ok=True)
        with open(os.path.join(workspace, IDENTITY_FILE), "w", encoding="utf-8") as f:
            json.dump(current, f, indent=2)
            f.write("\n")
        return current
    if not _same(existing, current):
        theirs = existing.get("repo_remote") or existing.get("repo_path")
        ours = current["repo_remote"] or current["repo_path"]
        raise WorkspaceMismatch(
            f"{workspace} holds data for {theirs}, not {ours}. "
            f"Pass -o DIR to use a different workspace.")
    return existing
