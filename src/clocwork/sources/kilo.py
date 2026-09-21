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
`STORE` descriptor below, and only four things do move: the data directory,
the names its databases take, the file a project id is cached in, and how a
version is turned into the counter era its records are read at.

Those session totals are a roll-up over the session's own messages. Counting
them as well would double every token, and counting them instead would lose
the per-day, per-model breakdown the archive is built on, so they are not
read.

Kilo adds no `Co-Authored-By:` trailer of its own -- the one its GitHub agent
writes credits the person who dispatched the workflow -- so, as for OpenCode
and Gemini CLI, its measured tokens reach a commit only where the author
wrote a trailer naming it.
"""

import bisect
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

# The OpenCode release each Kilo release carried, from the first Kilo release
# that carried it. OpenCode's counter eras are OpenCode versions, and Kilo
# numbers its own: 1.0.0 to 1.0.25, then 7.0.26 on. As bare numbers those
# land in the wrong era both ways -- a 1.0.x below ERA_B, an early 7.x above
# ERA_E -- while what they carried runs from v1.1.36 to past v1.18.
#
# The fork merges OpenCode's history, so each row is the newest OpenCode
# release tag that is an ancestor of the Kilo tag, with OpenCode's tags
# fetched beside the fork's:
#
#   git tag --merged v7.2.5 'upstream/v[0-9]*' | sort -V | tail -1
#
# over every Kilo tag whose commit is not OpenCode's own. The fork also
# carries OpenCode's tags, so its v1.0.0 to v1.0.12 name OpenCode's commits;
# Kilo's own 1.0.0 to 1.0.12 went to npm untagged, 2026-01-29 to 2026-02-03.
# Every commit on the fork's main line from the one that first wrote to the
# "kilo" directory (2026-01-26) to v1.0.13 descends from v1.1.36 and from no
# later release, so the first row starts at 1.0.0. The 0.x releases on npm
# are Kilo's earlier CLI, which never wrote this store. The sync commits
# ("kilo compat for v1.3.13") agree with every row that decides an era. Where
# they name a later release than the ancestry, as around v1.0.13 and v7.4.8,
# the ancestry is kept, because it is the one that is a lower bound -- and no
# such difference crosses an era.
#
# Kilo never released a build that carried era A or era C: its first release
# carried v1.1.36, past ERA_B, and it went from v1.2.25 (v7.2.4) to v1.3.13
# (v7.2.5) in one step, past era C's two releases.
RELEASES = tuple((opencode.version_of(kilo), opencode.version_of(upstream))
                 for kilo, upstream in (
    ("1.0.0", "1.1.36"),      # 2026-01-29, npm only
    ("1.0.16", "1.1.51"),     # 2026-02-05
    ("1.0.17", "1.1.57"),     # 2026-02-12
    ("1.0.24", "1.1.65"),     # 2026-02-20
    ("7.0.26", "1.2.2"),      # 2026-02-23
    ("7.0.27", "1.2.3"),      # 2026-02-23
    ("7.0.28", "1.2.10"),     # 2026-02-25
    ("7.0.31", "1.2.14"),     # 2026-02-27
    ("7.0.34", "1.2.15"),     # 2026-03-03
    ("7.0.47", "1.2.16"),     # 2026-03-13
    ("7.0.48", "1.2.17"),     # 2026-03-17
    ("7.0.51", "1.2.21"),     # 2026-03-19
    ("7.1.0", "1.2.24"),      # 2026-03-20
    ("7.2.4", "1.2.25"),      # 2026-04-10
    ("7.2.5", "1.3.13"),      # 2026-04-13
    ("7.2.6", "1.3.17"),      # 2026-04-14
    ("7.2.7", "1.4.3"),       # 2026-04-15
    ("7.2.17", "1.4.6"),      # 2026-04-21
    ("7.2.21", "1.4.9"),      # 2026-04-23
    ("7.2.23", "1.14.17"),    # 2026-04-24
    ("7.2.26", "1.14.22"),    # 2026-04-27
    ("7.2.30", "1.14.23"),    # 2026-04-29
    ("7.2.35", "1.14.29"),    # 2026-05-04
    ("7.2.44", "1.14.33"),    # 2026-05-07
    ("7.3.2", "1.14.34"),     # 2026-05-20
    ("7.3.8", "1.14.41"),     # 2026-05-22
    ("7.3.22", "1.14.42"),    # 2026-06-02
    ("7.3.29", "1.14.46"),    # 2026-06-04
    ("7.3.41", "1.14.48"),    # 2026-06-09
    ("7.3.44", "1.14.51"),    # 2026-06-12
    ("7.3.46", "1.15.4"),     # 2026-06-15
    ("7.3.48", "1.15.9"),     # 2026-06-18
    ("7.3.52", "1.15.13"),    # 2026-06-22
    ("7.4.13", "1.17.4"),     # 2026-07-20
    ("7.4.16", "1.17.5"),     # 2026-07-24
    ("7.4.17", "1.17.9"),     # 2026-07-29
    ("7.4.21", "1.17.13"),    # 2026-08-11
    ("7.4.22", "1.18.13"),    # 2026-08-13
))
FIRSTS = [first for first, _ in RELEASES]


def carried(version):
    """The OpenCode release a Kilo version carried, or () when no Kilo release
    of this store had that version: "local", a build from source, and the 0.x
    releases of the CLI that came before the fork. A release newer than the
    table carried at least its last row, because each release carried at
    least what the one before it did."""
    at = bisect.bisect_right(FIRSTS, version)
    return RELEASES[at - 1][1] if at else ()


# `opencode-<channel>.db` comes first because it is the name Kilo wrote
# before its rename, and its copy of a record must give way to the current
# one. A plain `opencode.db` here is not Kilo's: the fork renamed the data
# directory as well, so a store from before the rename sits in OpenCode's
# own directory, where its own reader owns it.
#
# Kilo does read the file generations. Its database arrived in v7.0.26; up
# to v1.0.25 it shipped OpenCode's JSON store, already writing to its own
# directory (`const app = "kilo"` is there at v1.0.25), and that release
# carries the J0-to-J1 migration, so both layouts can sit in it.
#
# The floor is for a version carried() cannot place. It lands such a record
# on ERA_B, which input_cache() reads without subtracting: era A's rule needs
# a version below ERA_B or none at all, and era C's needs one in
# [ERA_C, ERA_D). Era A is the rule a version-less record would otherwise
# reach, and a rule no Kilo release carried. If such a record did come from
# era-A code -- a build from source can be cut from anywhere -- the floor
# leaves its cache read in `input` as well as in `cache_read`, for a
# non-Anthropic provider, so a sum over the two counts it twice (1,400 rather
# than 1,000, for a 1,000-token prompt with 400 served from cache). That is
# the preferred error: the tokens stay visible in a labelled counter instead
# of prompt tokens silently disappearing. A record's own `total` is asked
# first, and the floor only decides where there is none.
STORE = opencode.Store(("opencode-*.db", "kilo*.db"), "kilo", opencode.ERA_B, True, carried)


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
    return opencode.known_ids(repo, STORE)


def scan(repo, homes):
    """The repository's Kilo Code usage, or None when no session in the homes
    belongs to it and nothing was unreadable."""
    return opencode.scan(repo, homes, STORE)
