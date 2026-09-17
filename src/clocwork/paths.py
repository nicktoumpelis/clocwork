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
