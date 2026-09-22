"""What a run reports, and how it looks.

The modules report events -- a phase, its result, details, warnings,
progress, the closing summary -- through a Reporter, and never lay out text.
Three renderers draw them:

- Terminal, for a TTY: colour, glyphs, and a live line redrawn with \\r;
- Plain, for anything else (a log file, a pipe, NO_COLOR, TERM=dumb): lines
  that read on their own, with no escape codes and no redraws. The daily
  token job greps its `Archive now` line, and the end-to-end check its
  `Test code at` line, so both keep their wording;
- the base Reporter, for -q: nothing but errors.

choose() picks one.
"""

import contextlib
import os
import shutil
import sys
import textwrap
import time
from collections import namedtuple

from clocwork import __version__

# A summary line: the terminal shows label, value and rest in columns; plain
# output prints `plain`, one or more whole lines.
Row = namedtuple("Row", "label value rest plain")

LABEL_WIDTH = 10                       # "Dashboard" and a space
INDENT = " " * (2 + LABEL_WIDTH + 1)   # where a phase's text starts: glyph, space, label, space


def duration(seconds):
    """0.2s, 4m02s, 1h03m."""
    if round(seconds, 1) < 60:
        return f"{seconds:.1f}s"
    minutes, secs = divmod(int(round(seconds)), 60)
    if minutes < 60:
        return f"{minutes}m{secs:02d}s"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h{minutes:02d}m"


def size(n):
    """A file size: 115 KB, 1.2 MB."""
    return f"{n / 1024:.0f} KB" if n < 1024 * 1024 else f"{n / 1024 / 1024:.1f} MB"


def compact(n):
    """A large count at a glance: 950, 12.3K, 1.2M, 1.2B."""
    for limit, suffix in ((10 ** 9, "B"), (10 ** 6, "M"), (10 ** 3, "K")):
        if n >= limit:
            return f"{n / limit:.1f}{suffix}"
    return f"{n:,}"


def short_path(path, home=None):
    """A path under the home directory as ~/..., any other as it is."""
    home = os.path.expanduser("~") if home is None else home.rstrip(os.sep)
    if path == home:
        return "~"
    if home and path.startswith(home + os.sep):
        return "~" + path[len(home):]
    return path


def joined(parts, sep):
    """A result's parts joined for this renderer; a string is one part."""
    return parts if isinstance(parts, str) else sep.join(parts)


def bar(fraction, width, unicode=True):
    """(done, rest): the two halves of a progress bar `width` cells wide."""
    fraction = min(max(fraction, 0.0), 1.0)
    cells = fraction * width
    full = int(cells)
    fill, half, empty = ("━", "╸", "━") if unicode else ("#", "#", "-")
    head = fill * full + (half if full < width and cells - full >= 0.5 else "")
    return head, empty * (width - len(head))


def columns(header, rows):
    """A table as aligned lines: the first column left, the rest right."""
    table = [tuple(header)] + [tuple(r) for r in rows]
    widths = [max(len(r[i]) for r in table) for i in range(len(header))]
    return ["  ".join(c.ljust(w) if i == 0 else c.rjust(w) for i, (c, w) in enumerate(zip(r, widths))).rstrip()
            for r in table]


def summary_rows(summary, first_appearances, branch):
    """The closing summary of a run, from full_commit_data.json's summary."""
    total, ai = summary["total_commits"], summary["ai_assisted_commits"]
    human, misc = summary["human_only_commits"], summary["misc_commits"]
    share = f" ({ai / total:.0%})" if total else ""
    rows = [Row("Commits", f"{total:,}", f"{ai:,} AI-assisted{share} · {human:,} human · {misc:,} misc",
                f"Commits: {total:,} ({ai:,} AI-assisted, {human:,} human, {misc:,} misc)")]
    t = summary["tokens"]
    if t["measured_total"]:
        rest = f"lifetime · {compact(t['measured_total'])} measured over {t['measured_days']} days"
        plain = (f"Tokens: {t['lifetime_total']:,} lifetime ({t['measured_total']:,} measured over "
                 f"{t['measured_days']} days, {t['estimated_total']:,} estimated at {t['ratio']:,.0f} per AI line)")
        if t["unmeasured_agent_commits"]:
            n = t["unmeasured_agent_commits"]
            rest += f" · {n:,} AI commits carry none"
            plain += (f"\n{n} AI commits carry no token figure ({', '.join(t['unmeasured_agents'])}): "
                      "no token logs from their agent cover their work")
        rows.append(Row("Tokens", compact(t["lifetime_total"]), rest, plain))
    else:
        rows.append(Row("Tokens", "none", "no agent token archive for this repository",
                        "Tokens: none (no agent token archive for this repository)"))
    snapshot = summary["head_snapshot"]
    tests = sum(v["code"] for v in snapshot["tests"].values())
    code = sum(v["code"] for v in snapshot["all"].values())
    if code:
        rows.append(Row("Tests", f"{tests / code:.1%}", f"{tests:,} of {code:,} code lines at {branch}",
                        f"Test code at {branch}: {tests:,} of {code:,} code lines ({tests / code:.1%})"))
    else:
        rows.append(Row("Tests", "none", f"no code at {branch}", f"Test code at {branch}: none"))
    firsts = sorted(first_appearances.items(), key=lambda item: item[1]["index"])
    if firsts:
        rows.append(Row("Agents", "", " · ".join(f"{a} from {i['date']}" for a, i in firsts),
                        "First appearances: " + ", ".join(f"{a} {i['date']} ({i['hash']})" for a, i in firsts)))
    return rows
