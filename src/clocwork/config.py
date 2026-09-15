"""clocwork.toml: page title, test-path rules and extra agents.

Search order, first hit wins: an explicit --config path, then
<workspace>/clocwork.toml, then <repo>/.clocwork.toml. The last is read and
never written, so a repository can commit its own answer while a third party
analysing it can still override from their workspace. Absent config is the
normal case and never an error.

    title = "MyApp"                         # page heading; default is the repo basename

    [tests]
    include = ["integration/**", "e2e/**"]  # added to the built-ins
    exclude = ["tests/fixtures/**"]         # applied last, wins over everything
    replace = false                         # true drops the built-ins entirely

    [agents]
    extra = [{ match = "Jules", name = "Jules" }]
"""

import os
import tomllib

from clocwork.agents import AgentTable
from clocwork.classify import TestRules


class ConfigError(RuntimeError):
    pass


class Config:
    def __init__(self, title=None, rules=None, agents=None, source=None):
        self.title = title
        self.rules = rules or TestRules()
        self.agents = agents or AgentTable()
        self.source = source


def _string_list(section, key, source):
    value = section.get(key, [])
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise ConfigError(f"{source}: [tests].{key} must be a list of strings")
    return value


def parse(text, source):
    try:
        data = tomllib.loads(text)
    except tomllib.TOMLDecodeError as e:
        raise ConfigError(f"{source}: invalid TOML: {e}") from None
    title = data.get("title")
    if title is not None and not isinstance(title, str):
        raise ConfigError(f"{source}: title must be a string")
    tests = data.get("tests", {})
    if not isinstance(tests, dict):
        raise ConfigError(f"{source}: [tests] must be a table")
    rules = TestRules(include=_string_list(tests, "include", source),
                      exclude=_string_list(tests, "exclude", source),
                      replace=bool(tests.get("replace", False)))
    agents = data.get("agents", {})
    extra = agents.get("extra", []) if isinstance(agents, dict) else None
    if extra is None or not isinstance(extra, list) or not all(
            isinstance(e, dict) and isinstance(e.get("match"), str) and isinstance(e.get("name"), str)
            for e in extra):
        raise ConfigError(f"{source}: [agents].extra must be a list of {{ match, name }} tables")
    return Config(title=title, rules=rules, agents=AgentTable(extra=extra), source=source)


def load(explicit=None, workspace=None, repo=None):
    candidates = []
    if explicit:
        if not os.path.isfile(explicit):
            raise ConfigError(f"{explicit}: no such config file")
        candidates.append(explicit)
    if workspace:
        candidates.append(os.path.join(workspace, "clocwork.toml"))
    if repo:
        candidates.append(os.path.join(repo, ".clocwork.toml"))
    for path in candidates:
        if os.path.isfile(path):
            with open(path, encoding="utf-8") as f:
                return parse(f.read(), path)
    return Config()
