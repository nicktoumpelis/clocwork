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

# A summary line: the terminal shows label, value and rest (its parts, joined
# with the renderer's separator) in columns; plain output prints `plain`, one
# or more whole lines.
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
    rows = [Row("Commits", f"{total:,}", [f"{ai:,} AI-assisted{share}", f"{human:,} human", f"{misc:,} misc"],
                f"Commits: {total:,} ({ai:,} AI-assisted, {human:,} human, {misc:,} misc)")]
    t = summary["tokens"]
    if t["measured_total"]:
        rest = ["lifetime", f"{compact(t['measured_total'])} measured over {t['measured_days']} days"]
        plain = (f"Tokens: {t['lifetime_total']:,} lifetime ({t['measured_total']:,} measured over "
                 f"{t['measured_days']} days, {t['estimated_total']:,} estimated at {t['ratio']:,.0f} per AI line)")
        if t["unmeasured_agent_commits"]:
            n = t["unmeasured_agent_commits"]
            rest.append(f"{n:,} AI commits carry none")
            plain += (f"\n{n} AI commits carry no token figure ({', '.join(t['unmeasured_agents'])}): "
                      "no token logs from their agent cover their work")
        rows.append(Row("Tokens", compact(t["lifetime_total"]), rest, plain))
    else:
        rows.append(Row("Tokens", "none", ["no agent token archive for this repository"],
                        "Tokens: none (no agent token archive for this repository)"))
    snapshot = summary["head_snapshot"]
    tests = sum(v["code"] for v in snapshot["tests"].values())
    code = sum(v["code"] for v in snapshot["all"].values())
    if code:
        rows.append(Row("Tests", f"{tests / code:.1%}", [f"{tests:,} of {code:,} code lines at {branch}"],
                        f"Test code at {branch}: {tests:,} of {code:,} code lines ({tests / code:.1%})"))
    else:
        rows.append(Row("Tests", "none", [f"no code at {branch}"], f"Test code at {branch}: none"))
    firsts = sorted(first_appearances.items(), key=lambda item: item[1]["index"])
    if firsts:
        rows.append(Row("Agents", "", [f"{a} from {i['date']}" for a, i in firsts],
                        "First appearances: " + ", ".join(f"{a} {i['date']} ({i['hash']})" for a, i in firsts)))
    return rows


class Reporter:
    """The calls a run makes, doing nothing: -q's renderer and the base of
    the others. Errors always reach standard error."""

    verbose = False

    def __init__(self):
        self.rows, self.lines = [], None

    def header(self, name, workspace, config=None):
        pass

    @contextlib.contextmanager
    def phase(self, label, index, count):
        yield

    def status(self, parts):
        pass

    def done(self, parts, *more):
        pass

    def detail(self, label, value):
        pass

    def warn(self, text):
        pass

    def progress(self, done, total, elapsed):
        pass

    def summary(self, rows):
        """Kept for finish(), which prints them after the last phase."""
        self.rows = list(rows)

    def table(self, title, header, rows):
        """Kept for finish(); shown with -v only."""
        self.lines = (title, tuple(header), [tuple(r) for r in rows])

    def finish(self, path=None):
        pass

    def error(self, text):
        sys.stderr.write(f"clocwork: {text}\n")
        sys.stderr.flush()


class Plain(Reporter):
    """Lines that read on their own, for a log file or a pipe: no escape
    codes, no redraws, full paths and exact numbers."""

    EVERY = 50     # a progress line per this many commits, as the cache is saved

    def __init__(self, stream, verbose=False, clock=time.monotonic):
        super().__init__()
        self.stream, self.verbose, self.clock = stream, verbose, clock
        self.prefix, self.result = "", None

    def say(self, text):
        self.stream.write(text + "\n")
        # Per line: an hour-long run piped to a log file (cron, nohup) would
        # otherwise show nothing until it ends.
        self.stream.flush()

    def tagged(self, text):
        self.say(f"{self.prefix}: {text}" if self.prefix else text)

    def header(self, name, workspace, config=None):
        self.say(f"clocwork {__version__}: {name} -> {workspace}")
        if config:
            self.say(f"Config: {config}")

    @contextlib.contextmanager
    def phase(self, label, index, count):
        self.prefix, self.result, started = f"[{index}/{count}] {label}", None, self.clock()
        if self.verbose:
            self.say(self.prefix)
        try:
            yield
        except BaseException:
            self.tagged(f"stopped after {duration(self.clock() - started)}")
            self.prefix = ""
            raise
        text, more = self.result or ("done", ())
        self.tagged(f"{text} ({duration(self.clock() - started)})")
        for line in more:
            self.say(f"  {line}")
        self.prefix = ""

    def status(self, parts):
        self.tagged(joined(parts, ", "))

    def done(self, parts, *more):
        self.result = (joined(parts, ", "), more)

    def detail(self, label, value):
        if self.verbose:
            self.say(f"  {label}: {value}")

    def warn(self, text):
        self.say(f"WARNING: {text}")

    def progress(self, done, total, elapsed):
        if done % self.EVERY == 0 and done < total:
            left = (total - done) * elapsed / done
            self.tagged(f"measured {done:,}/{total:,}, {duration(elapsed)} elapsed, ~{duration(left)} left")

    def finish(self, path=None):
        for row in self.rows:
            for line in row.plain.splitlines():
                self.say(line)
        if self.verbose and self.lines:
            title, header, rows = self.lines
            self.say(f"{title}:")
            for line in columns(header, rows):
                self.say(f"  {line}")
        if path:
            self.say(f"Open: {path}")


class Terminal(Reporter):
    """Colour, glyphs and a live line, for a TTY. A phase's warnings and
    details are held until its line is finished, so they print under it."""

    GLYPHS = {True: {"ok": "✓", "fail": "✗", "warn": "⚠", "open": "→", "sep": "·", "spin": "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"},
              False: {"ok": "+", "fail": "x", "warn": "!", "open": ">", "sep": "-", "spin": "|/-\\"}}
    SGR = {"bold": "1", "dim": "2", "red": "31", "green": "32", "yellow": "33", "cyan": "36"}
    FRAME = 0.1    # seconds between redraws of the live line

    def __init__(self, stream, verbose=False, unicode=True, width=80, clock=time.monotonic):
        super().__init__()
        self.stream, self.verbose, self.unicode, self.width, self.clock = stream, verbose, unicode, width, clock
        self.g = self.GLYPHS[unicode]
        self.sep = f" {self.g['sep']} "
        self.label, self.live, self.frame, self.drawn = None, False, 0, None
        self.result, self.after, self.state = None, [], ("", "")

    def paint(self, text, *styles):
        return f"\x1b[{';'.join(self.SGR[s] for s in styles)}m{text}\x1b[0m" if text else text

    def write(self, text):
        self.stream.write(text)
        self.stream.flush()

    def clear(self):
        if self.live:
            self.write("\r\x1b[2K")
            self.live = False

    def line(self, text=""):
        self.clear()
        self.write(text + "\n")

    def emit(self, lines):
        if self.label is not None:
            self.after.extend(lines)
        else:
            for text in lines:
                self.line(text)

    def redraw(self):
        frames = self.g["spin"]
        self.frame += 1
        spin, name = frames[self.frame % len(frames)], f"{self.label:<{LABEL_WIDTH}}"
        visible, styled = self.state
        plain = f"{spin} {name} {visible}"
        if len(plain) >= self.width:
            text = plain[:self.width - 1]           # a cut line loses its styling
        else:
            text = f"{self.paint(spin, 'cyan')} {self.paint(name, 'bold')} {styled}"
        self.write("\r\x1b[2K" + text)
        self.live, self.drawn = True, self.clock()

    def header(self, name, workspace, config=None):
        self.line(f"{self.paint('clocwork', 'bold')} {__version__}{self.sep}{self.paint(name, 'bold')} "
                  f"{self.g['open']} {short_path(workspace)}")
        if config:
            self.line(self.paint(f"  config {short_path(config)}", "dim"))
        self.line()

    @contextlib.contextmanager
    def phase(self, label, index, count):
        self.label, self.result, self.after, self.state = label, None, [], ("", "")
        started, ok = self.clock(), False
        self.redraw()
        try:
            yield
            ok = True
        finally:
            elapsed = duration(self.clock() - started)
            text, more = self.result or ("", ())
            mark = self.paint(self.g["ok"], "green") if ok else self.paint(self.g["fail"], "red")
            name = f"{label:<{LABEL_WIDTH}}"
            gap = max(2, self.width - 1 - 2 - len(name) - 1 - len(text) - len(elapsed))
            self.label = None
            self.line(f"{mark} {self.paint(name, 'bold')} {text}{' ' * gap}{self.paint(elapsed, 'dim')}")
            for extra in more:
                self.line(INDENT + extra)
            for extra in self.after:
                self.line(extra)

    def status(self, parts):
        text = joined(parts, self.sep)
        self.state = (text, text)
        if self.label is not None:
            self.redraw()

    def done(self, parts, *more):
        self.result = (joined(parts, self.sep), more)

    def detail(self, label, value):
        if not self.verbose:
            return
        lead = " " * 6 + f"{label:<13} "
        wrapped = textwrap.wrap(str(value), max(20, self.width - len(lead) - 1)) or [""]
        self.emit([self.paint(lead + wrapped[0], "dim")]
                  + [self.paint(" " * len(lead) + more, "dim") for more in wrapped[1:]])

    def warn(self, text):
        self.emit([f"  {self.paint(self.g['warn'], 'yellow')} {text}"])

    def progress(self, done, total, elapsed):
        if self.label is None or not total:
            return
        if done < total and self.drawn is not None and self.clock() - self.drawn < self.FRAME:
            return
        left = (total - done) * elapsed / done if done else 0.0
        count = f"{done:,}/{total:,}{self.sep}{duration(elapsed)}{self.sep}~{duration(left)} left"
        cells = min(30, self.width - 50)
        if cells >= 10:
            head, tail = bar(done / total, cells, self.unicode)
            self.state = (f"{head}{tail}  {count}", f"{self.paint(head, 'green')}{self.paint(tail, 'dim')}  {count}")
        else:
            self.state = (count, count)
        self.redraw()

    def finish(self, path=None):
        if self.rows:
            self.line()
            width = max(len(r.value) for r in self.rows)
            for r in self.rows:
                lead = f"  {r.label:<{LABEL_WIDTH}} "
                value = f"{r.value:<{width}}   " if width else ""
                rest = textwrap.wrap(joined(r.rest, self.sep), max(20, self.width - len(lead) - len(value) - 1)) or [""]
                self.line(lead + self.paint(value, "bold") + rest[0])
                for more in rest[1:]:
                    self.line(" " * (len(lead) + len(value)) + more)
        if self.verbose and self.lines:
            title, header, rows = self.lines
            table = columns(header, rows)
            self.line()
            self.line(f"  {self.paint(title, 'bold')}")
            self.line(self.paint(f"    {table[0]}", "dim"))
            for text in table[1:]:
                self.line(f"    {text}")
        if path:
            self.line()
            self.line(f"{self.paint(self.g['open'], 'cyan')} {short_path(path)}")

    def error(self, text):
        self.clear()
        message = f"clocwork: {text}"
        sys.stderr.write((self.paint(message, "red") if sys.stderr.isatty() else message) + "\n")
        sys.stderr.flush()


def choose(quiet=False, verbose=False, stream=None, environ=None):
    """The renderer for this run: nothing for -q, Terminal for a TTY that
    NO_COLOR (set and not empty, per no-color.org) or TERM=dumb does not
    rule out, Plain otherwise."""
    stream = sys.stdout if stream is None else stream
    environ = os.environ if environ is None else environ
    if quiet:
        return Reporter()
    isatty = getattr(stream, "isatty", None)
    if isatty and isatty() and not environ.get("NO_COLOR") and environ.get("TERM") != "dumb":
        encoding = (getattr(stream, "encoding", None) or "").lower().replace("-", "").replace("_", "")
        return Terminal(stream, verbose, unicode=encoding == "utf8",
                        width=shutil.get_terminal_size((80, 24)).columns)
    return Plain(stream, verbose)
