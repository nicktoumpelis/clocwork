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

Other agents are matched by a substring of the trailer, from a vendor table a
workspace can extend. An unrecognised trailer stays unmatched rather than
being guessed at: a wrong attribution is worse than a missing one.
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

UNKNOWN_CLAUDE = "Claude (unknown version)"

# (substring of the trailer, reported name)
VENDORS = (
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


class AgentTable:
    """The vendor table plus a workspace's [agents].extra rows."""

    def __init__(self, extra=()):
        self.rules = list(VENDORS) + [(e["match"], e["name"]) for e in extra]

    def match(self, trailer):
        model = parse_claude_model(trailer)
        if model:
            return model
        lowered = trailer.lower()
        for needle, name in self.rules:
            if needle.lower() in lowered:
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
