"""Kilo Code: an OpenCode fork, reading an OpenCode store from its own
directory.

The store is OpenCode's, and the clearest evidence is a migration Kilo
inherited **unchanged**: OpenCode's 20260510033149_session_usage, whose blob
is byte for byte the one in sst/opencode, back-fills session totals by
summing `$.tokens.input`, `$.tokens.output`, `$.tokens.reasoning`,
`$.tokens.cache.read` and `$.tokens.cache.write` out of each assistant
`message.data`. That is the JSON `sources.opencode` reads, in the same
tables, with the same `step-finish` parts and the same `session_message`
projection -- and a fork that ships the migration untouched is a fork whose
store has not moved. So everything here is opencode's, through the
`opencode.KILO` descriptor, and only four things do move: the data
directory, the names its databases take, the file a project id is cached in,
and the counter era its records are read at.

Those session totals are a roll-up over the session's own messages. Counting
them as well would double every token, and counting them instead would lose
the per-day, per-model breakdown the archive is built on, so they are not
read.

Kilo adds no `Co-Authored-By:` trailer of its own -- the one its GitHub agent
writes credits the person who dispatched the workflow -- so, as for OpenCode
and Gemini CLI, its measured tokens reach a commit only where the author
wrote a trailer naming it.
"""

import os
import re

from clocwork import tokens
from clocwork.sources import opencode

KEY = "kilo"
LABEL = "Kilo Code"
# agents.VENDORS reports every spelling of the name as "Kilo Code".
AGENT = re.compile(r"^Kilo Code$")
SKIPPED = opencode.SKIPPED
MALFORMED_UNIT = opencode.MALFORMED_UNIT


def default_homes(env):
    """Kilo's data directory, plus the database KILO_DB names.

    `global.ts` joins `xdgData` with "kilo", and xdg-basedir does not look at
    the platform, so this is ~/.local/share/kilo on macOS and Windows too.
    `KILO_DB` takes an absolute path or a name relative to that directory,
    exactly as OPENCODE_DB does; `:memory:` holds nothing a later run could
    read.
    """
    data = env.get("XDG_DATA_HOME") or os.path.join(os.path.expanduser("~"), ".local", "share")
    homes = [os.path.join(data, "kilo")]
    db = tokens.text(env.get("KILO_DB"))
    if db and db != ":memory:":
        homes.append(db if os.path.isabs(db) else os.path.join(homes[0], db))
    return homes


def known_ids(repo):
    """Every project id Kilo could have given this repository. It hashes a
    remote exactly as OpenCode does, and caches an id under its own name."""
    return opencode.known_ids(repo, opencode.KILO)


def scan(repo, homes):
    """The repository's Kilo Code usage, or None when no session in the homes
    belongs to it and nothing was unreadable."""
    return opencode.scan(repo, homes, opencode.KILO)
