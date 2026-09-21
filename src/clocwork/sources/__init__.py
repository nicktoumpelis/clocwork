"""Where each coding agent keeps its token usage: one module per agent.

A source module provides:

    KEY                 the key its records are archived under
    LABEL               how the log and the page name it
    AGENT               a pattern over the agent names agents.AgentTable
                        produces; the source's tokens land only on the
                        commits whose agent it matches
    default_homes(env)  the directories the agent writes its logs to
    scan(repo, homes)   a tokens.ScanResult for the repository, or None when
                        no home holds logs for it
    SKIPPED             optional: why scan() can count a file as unreadable
                        (tokens.ScanResult.skipped), appended to that count
                        in the log
    MALFORMED_UNIT      optional: what scan() counts as malformed, when it is
                        not the default "lines"

An agent name must match at most one source, or one commit's lines would be
counted against two sources' tokens. source_for() takes the first match.
"""

from clocwork.sources import claude_code, codex, copilot, gemini, opencode

SOURCES = (claude_code, codex, copilot, gemini, opencode)


def by_key(key):
    """The source archived under `key`, or None for a key this version does
    not know (an archive written by a newer clocwork)."""
    return next((s for s in SOURCES if s.KEY == key), None)


def source_for(agent):
    """The source whose tokens a commit credited to `agent` carries, or None."""
    if agent:
        for source in SOURCES:
            if source.AGENT.search(agent):
                return source
    return None
