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
address's local part, or a whole label of its domain. The domain is the strict
one because it is where the name of whoever owns the address sits: "Antigravity"
is a common enough word that a contributor at a company called Antigravity
Drones would otherwise be credited to an agent. A display name is the agent's
own announcement, so a word in it counts. An unrecognised trailer stays
unmatched rather than being guessed at: a wrong attribution is worse than a
missing one, which is also why a name glued to a version ("Antigravity2") is
left alone.

A workspace's own rows are matched by the same rule, which is what keeps a
short needle from spreading - "code" reaches no OpenCode trailer, because it
is no whole word of "opencode". The built-in rows are tried first, so
`[agents].extra` names what the table does not rather than renaming what it
does.
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
# An ASCII letter or digit either side of a vendor's name makes it part of a
# longer word, and a longer word is a different name: "Codexterous" is not
# Codex, and "Antigravity2" is not Antigravity - it may be a product of its
# own, and a missing attribution is the cheaper mistake. Every other
# character is a boundary, so "opencode-go" and "gemini-code-assist[bot]"
# still name their agents.
WORD_EDGE = "(?<![0-9a-z]){}(?![0-9a-z])"

UNKNOWN_CLAUDE = "Claude (unknown version)"

# (the agent's name in a trailer, what to report it as)
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
    cased.

    Anything outside the angle brackets is the name, on either side of them,
    so a note after the address still names its agent. A trailer written
    without brackets is an address when it holds an `@` - a bare address is
    the form a hand-written trailer most often takes, and reading it as a
    name would put its domain under the looser rule that a domain must not
    have. An address with no `@` is nobody's domain, so it is read as a local
    part instead.
    """
    lowered = trailer.lower()
    before, bracket, rest = lowered.partition("<")
    address, _, after = rest.partition(">")
    name = (before + " " + after).strip()
    if not bracket and "@" in before:
        name, address = "", before
    local, at, domain = address.strip().rpartition("@")
    if not at:
        return name, address.strip(), []
    return name, local.strip(), [label.strip() for label in domain.split(".")]


def names_agent(needle, name, local, labels):
    """Whether a vendor's name is the one this trailer credits.

    It counts as a whole word in the display name, or in the address's local
    part, which the agent chooses for itself. In the domain it has to be a
    whole label: a domain is where the name of whoever owns the address sits,
    and `antigravity-drones.example` is not Antigravity.
    """
    needle = needle.lower()
    word = re.compile(WORD_EDGE.format(re.escape(needle)))
    return bool(word.search(name) or word.search(local)) or needle in labels


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
