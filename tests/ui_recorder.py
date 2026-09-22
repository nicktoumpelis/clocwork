"""A reporter that keeps every call, for tests to assert on what a module
reported rather than on how a renderer laid it out."""

from clocwork import ui


class Recorder(ui.Reporter):
    verbose = True

    def __init__(self):
        super().__init__()
        self.events = []

    def status(self, parts):
        self.events.append(("status", ui.joined(parts, " · ")))

    def done(self, parts, *more):
        self.events.append(("done", ui.joined(parts, " · "), more))

    def detail(self, label, value):
        self.events.append(("detail", label, value))

    def warn(self, text):
        self.events.append(("warn", text))

    def progress(self, done, total, elapsed):
        self.events.append(("progress", done, total))

    def of(self, kind):
        """The arguments of every call of one kind, in order."""
        return [e[1:] if len(e) > 2 else e[1] for e in self.events if e[0] == kind]
