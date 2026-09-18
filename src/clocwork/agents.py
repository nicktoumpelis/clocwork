"""Which AI agent, if any, a commit credits.

Attribution is read from "Co-Authored-By:" trailer lines only, so a human
commit that merely mentions CLAUDE.md or a claude-* branch name is not
counted as AI-assisted.

Claude model names are parsed generically rather than listed one by one, so
any Claude model - past, present, or future - is recognised without a code
change. Two naming schemes are handled:

  family-first (Claude 4+):  "Claude Opus 4.6", "Claude Fable 5.1",
                             "Claude Opus 5 (1M context)"
  version-first (Claude 3.x): "Claude 3.5 Sonnet", "Claude 3 Opus"

Both normalise to "Claude <Family> <version>", with " (1M)" appended for the
1M-context variants, so the dashboard sees one consistent naming scheme. The
version is captured greedily, which is what keeps "Fable 5.1" from being read
as "Fable 5".

Other agents are matched by name, from a vendor table a workspace can extend.
A vendor's name has to be a whole word in the trailer's display name or the
address's local part, or a whole label of its domain - "Antigravity" is a
common enough word that a contributor at a company called Antigravity Drones
would otherwise be credited to an agent. An unrecognised trailer stays
unmatched rather than being guessed at: a wrong attribution is worse than a
missing one.

A workspace's own rows are matched the same way, and the built-in rows are
tried first, so `[agents].extra` names what the table does not rather than
renaming what it does. That is also what keeps a short needle from claiming
trailers it was never meant to.
"""

import re

CLAUDE_FAMILIES = r"(?:Fable|Opus|Sonnet|Haiku|Mythos)"
CLAUDE_VERSION = r"\d+(?:\.\d+)?"
CLAUDE_CONTEXT = r"(?:\s*\((\d+[KM]) context\))?"

MODEL_FAMILY_FIRST = re.compile(
    rf"Claude\s+({CLAUDE_FAMILIES})\s+({CLAUDE_VERSION}){CLAUDE_CONTEXT}",
    re.IGNORECASE,
)
MODEL_VERSION_FIRST = re.compile(
    rf"Claude\s+({CLAUDE_VERSION})\s+({CLAUDE_FAMILIES}){CLAUDE_CONTEXT}",
    re.IGNORECASE,
)
COAUTHOR_TRAILER = re.compile(r"^\s*Co-Authored-By:\s*(.+)$", re.IGNORECASE | re.MULTILINE)
# Letters and digits either side of a vendor's name make it part of a longer
# word, and a longer word is a different thing: "Codexterous" is not Codex.
# Every other character is a boundary, so "opencode-go" and
# "gemini-code-assist[bot]" still name their agents.
WORD_EDGE = "(?<![0-9a-z]){}(?![0-9a-z])"

UNKNOWN_CLAUDE = "Claude (unknown version)"

# (substring of the trailer, reported name)
VENDORS = (
    # OpenCode's GitHub Actions agent commits as opencode-agent[bot], and its
    # logs stay on the runner, so it is a separate agent from the OpenCode
    # whose tokens this machine can read. It comes before the next two rows,
    # which would otherwise claim it.
    ("opencode-agent", "OpenCode GitHub agent"),
    # OpenCode has added no trailer since v0.4.20; this catches the ones it
    # wrote before that and the ones people add, which name it in many ways
    # ("opencode", "GLM-5.3 via OpenCode", "opencode-go/mimo-v2.5"). It comes
    # before Copilot, which a trailer naming an OpenCode model would hit.
    ("opencode", "OpenCode"),
    ("Copilot", "Copilot"),
    ("Cursor", "Cursor"),
    ("Codex", "Codex"),
    ("Devin", "Devin"),
    ("aider", "aider"),
    # GitHub credits accepted review suggestions to gemini-code-assist[bot]. It
    # comes before the next row, which would otherwise claim it.
    ("gemini-code-assist", "Gemini Code Assist"),
    # Antigravity writes no trailer of its own either, and the ones people add
    # vary in everything but the word itself ("Antigravity AI", "DeepMind
    # Antigravity", "AGY <noreply@antigravity.dev>"). It names the Gemini model
    # it ran ("Antigravity CLI (Gemini 3.8 Flash)"), and its address is
    # sometimes gemini@google.com, so this row comes before the Gemini one.
    ("Antigravity", "Antigravity"),
    # Gemini CLI adds no trailer of its own; this catches the one a person adds.
    ("Gemini", "Gemini"),
)


def normalise_model(family, version, context):
    name = f"Claude {family.capitalize()} {version}"
    if context:
        name += f" ({context.upper()})"
    return name


def parse_claude_model(text):
    """Return the normalised Claude model name found in a co-author trailer, or None."""
    m = MODEL_FAMILY_FIRST.search(text)
    if m:
        return normalise_model(m.group(1), m.group(2), m.group(3))
    m = MODEL_VERSION_FIRST.search(text)
    if m:
        return normalise_model(m.group(2), m.group(1), m.group(3))
    if re.search(r"\bClaude\b", text, re.IGNORECASE):
        return UNKNOWN_CLAUDE
    return None


def trailer_parts(trailer):
    """(display name, address local part, domain labels) of a trailer, lower
    cased. A trailer without an address is all name, which is how a person
    who wrote one by hand may have left it."""
    lowered = trailer.lower()
    name, _, rest = lowered.partition("<")
    local, _, domain = rest.partition(">")[0].rpartition("@")
    return name.strip(), local, domain.split(".")


def names_agent(needle, name, local, labels):
    """Whether a vendor's name is the one this trailer credits.

    It counts as a whole word in the display name, or in the address's local
    part, which the agent chooses for itself. In the domain it has to be a
    whole label: a domain is where the name of whoever owns the address sits,
    and `antigravity-drones.example` is not Antigravity.
    """
    needle = needle.lower()
    word = re.compile(WORD_EDGE.format(re.escape(needle)))
    return bool(word.search(name)) or bool(local and word.search(local)) or needle in labels


class AgentTable:
    """The vendor table plus a workspace's [agents].extra rows."""

    def __init__(self, extra=()):
        self.rules = list(VENDORS) + [(e["match"], e["name"]) for e in extra]

    def match(self, trailer):
        model = parse_claude_model(trailer)
        if model:
            return model
        parts = trailer_parts(trailer)
        for needle, name in self.rules:
            if names_agent(needle, *parts):
                return name
        return None

    def detect(self, body):
        """The agent credited in a commit body via its Co-Authored-By trailers.

        The first recognised trailer wins, matching the previous first-match
        behaviour for commits that credit more than one model.
        """
        if not body:
            return None
        for trailer in COAUTHOR_TRAILER.findall(body):
            name = self.match(trailer)
            if name:
                return name
        return None


DEFAULT_AGENTS = AgentTable()


def detect_agent(body, table=DEFAULT_AGENTS):
    return table.detect(body)
