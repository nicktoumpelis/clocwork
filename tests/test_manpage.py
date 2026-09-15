import os
import re
import shutil
import subprocess
import unittest

from clocwork import __version__, cli, manpage

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PAGE = os.path.join(ROOT, "man", "clocwork.1")
MACRO = re.compile(r'^\.(TH|SH|SS|TP|B|BR|BI|I|IR|IP|PP|br|RS|RE|nf|fi|\\")(\s|$)')


class TestRender(unittest.TestCase):
    def setUp(self):
        self.page = manpage.render(date="2026-09-15")

    def test_header_names_the_command_section_date_and_version(self):
        self.assertTrue(self.page.startswith('.TH CLOCWORK 1 "2026-09-15" "clocwork ' + __version__ + '"'), self.page[:80])

    def test_standard_sections_in_order(self):
        names = re.findall(r"^\.SH (.+)$", self.page, re.M)
        self.assertEqual(names[:5], ["NAME", "SYNOPSIS", "DESCRIPTION", "OPTIONS", "COMMANDS"])
        for section in ("ENVIRONMENT", "FILES", "EXIT STATUS", "SEE ALSO"):
            self.assertIn(section, names)

    def section(self, name):
        """The text of one .SS subsection, up to the next .SS or .SH."""
        m = re.search(rf"^\.SS {name}\n(.*?)(?=^\.S[SH] |\Z)", self.page, re.M | re.S)
        self.assertIsNotNone(m, name)
        return m.group(1)

    def sh_section(self, name):
        m = re.search(rf"^\.SH {name}\n(.*?)(?=^\.SH |\Z)", self.page, re.M | re.S)
        self.assertIsNotNone(m, name)
        return m.group(1)

    @staticmethod
    def tag_of(action):
        return ", ".join(o.replace("-", "\\-") for o in action.option_strings)

    def test_shared_options_appear_once_and_commands_list_only_their_own(self):
        parser = cli.build_parser()
        subs = next(a for a in parser._actions if a.choices).choices
        seen = {}
        for name, sub in subs.items():
            for action in sub._actions:
                if action.option_strings and "--help" not in action.option_strings:
                    seen.setdefault((tuple(action.option_strings), action.help), []).append(name)
        shared = {k: v for k, v in seen.items() if len(v) > 1}
        options = self.sh_section("OPTIONS")
        option_tags = re.findall(r"^\.TP\n\.B (.+)$", options, re.M)
        self.assertEqual(len(option_tags), len(shared))
        for (flags, help), names in shared.items():
            tag = ", ".join(o.replace("-", "\\-") for o in flags)
            self.assertTrue(any(t.startswith(tag) for t in option_tags), (tag, option_tags))
            self.assertIn(manpage.escape(help.split("(")[0].strip()), options)
            # Which commands take it is stated unless every command does.
            listed = names[0] if len(names) == 1 else ", ".join(names[:-1]) + " and " + names[-1]
            note = f"Taken by {listed}."
            self.assertEqual(note in options, len(names) < len(subs), (tag, note))
        for name, sub in subs.items():
            body = self.section(name)
            tags = re.findall(r"^\.TP\n\.[BI] (.+)$", body, re.M)
            own = [a for a in sub._actions if "--help" not in a.option_strings
                   and (not a.option_strings or (tuple(a.option_strings), a.help) not in shared)]
            self.assertEqual(len(tags), len(own), (name, tags))
            for action in own:
                if action.option_strings:
                    self.assertTrue(any(t.startswith(self.tag_of(action)) for t in tags), (name, tags))
                else:
                    self.assertIn(manpage.escape(action.metavar or action.dest.upper()), tags, (name, tags))
                if action.help:
                    self.assertIn(manpage.escape(action.help.split("(")[0].strip()), body, (name, action.help))
            # A shared option's help never repeats inside a command section
            # (a command may re-declare the same flags with its own meaning).
            for (_flags, help) in shared:
                self.assertNotIn(manpage.escape(help), body, (name, help))

    def test_the_real_split(self):
        options = self.sh_section("OPTIONS")
        self.assertRegex(options, r"\.B \\-q, \\-\\-quiet\nprint nothing but errors\n")     # all commands: no note
        self.assertIn("explicit clocwork.toml. Taken by run and render.", options)
        self.assertIn("(default: <repo\\-parent>/<repo\\-name>\\-stats). Taken by run and tokens.", options)
        option_tags = re.findall(r"^\.TP\n\.B (.+)$", options, re.M)
        self.assertEqual(option_tags, ["\\-q, \\-\\-quiet", "\\-\\-config PATH", "\\-\\-locale TAG",
                                       "\\-\\-no\\-open", "\\-o, \\-\\-output DIR"])    # run's declaration order
        run, tokens, render = (self.section(n) for n in ("run", "tokens", "render"))
        run_tags = re.findall(r"^\.TP\n\.[BI] (.+)$", run, re.M)
        self.assertEqual(run_tags, ["REPO", "\\-\\-branch REF", "\\-\\-max\\-commits N", "\\-j, \\-\\-jobs N",
                                    "\\-\\-no\\-tokens", "\\-\\-cache\\-dir DIR"])
        self.assertEqual(re.findall(r"^\.TP\n\.[BI] (.+)$", tokens, re.M), ["REPO"])
        self.assertIn(".B \\-o, \\-\\-output DIR\nthe workspace to render", render)

    def test_render_requires_its_workspace_and_tokens_takes_no_page_options(self):
        render = self.section("render")
        self.assertNotIn("(default: <repo", render)
        self.assertIn(".B \\-o, \\-\\-output DIR\nthe workspace to render", render)
        synopsis = re.search(r"^\.B clocwork tokens\n(.+)$", self.page, re.M).group(1)
        for absent in ("\\-\\-config", "\\-\\-locale", "\\-\\-no\\-open"):
            self.assertNotIn(absent, synopsis, absent)

    def test_environment_files_and_exit_status_are_documented(self):
        for text in ("CLOCWORK_LOCALE", "XDG_CACHE_HOME", "clocwork.json", "token_usage.json", "clocwork.toml"):
            self.assertIn(text, self.page, text)
        self.assertRegex(self.page, r"\.TP\n\.B 2\n")

    def test_roff_safe(self):
        # A line starting with . or ' is a request; only known macros may start one.
        for line in self.page.splitlines():
            if line.startswith((".", "'")):
                self.assertTrue(MACRO.match(line), line)
        self.assertNotIn("\\-\\-max-commits", self.page)      # hyphens escaped consistently
        self.assertNotIn("[\\-h]", self.page)                  # -h is noise in a synopsis
        self.assertNotIn("\n\n", self.page)                    # no blank lines: roff treats them as breaks
        self.assertTrue(self.page.endswith("\n"))

    def test_escape(self):
        self.assertEqual(manpage.escape("a-b"), "a\\-b")
        self.assertEqual(manpage.escape("back\\slash"), "back\\\\slash")
        self.assertEqual(manpage.escape(".dot first"), "\\&.dot first")
        self.assertEqual(manpage.escape("'quote first"), "\\&'quote first")

    def test_files_tags_are_one_line_each(self):
        # A .TP tag is exactly one line; a second line of the tag becomes body text.
        for tag in re.findall(r"\.TP\n(.+)\n(.+)\n", self.page):
            self.assertFalse(tag[1].startswith((".I ", ".IR ", ".B ", ".BR ")), tag)
        self.assertIn('.IR index.html ", " commit_bodies.js\n', self.page)

    def test_note_is_a_sentence_even_without_help(self):
        import argparse
        p = argparse.ArgumentParser(prog="x")
        p.add_argument("--nohelp")
        p.add_argument("--paren", help="ends with a bracket (like this)")
        nohelp, paren = p._actions[1], p._actions[2]
        self.assertEqual(manpage._entry(nohelp, "Taken by a, b and c."), ".TP\n.B \\-\\-nohelp NOHELP\nTaken by a, b and c.\n")
        self.assertIn("(like this). Taken by a.", manpage._entry(paren, "Taken by a."))

    def test_options_fall_back_to_the_dest_and_keep_positional_order(self):
        import argparse
        p = argparse.ArgumentParser(prog="x")
        p.add_argument("first")
        p.add_argument("second", nargs="?")
        p.add_argument("--flag", action="store_true", help="a switch")
        p.add_argument("--value", help="takes one")
        text = manpage._options(p)
        self.assertLess(text.index(".I FIRST"), text.index(".I SECOND"))
        self.assertIn(".B \\-\\-flag\na switch", text)
        self.assertIn(".B \\-\\-value VALUE\ntakes one", text)

    def test_date_defaults_to_today(self):
        self.assertRegex(manpage.render(), r'^\.TH CLOCWORK 1 "\d{4}-\d{2}-\d{2}"')


class TestCommittedPage(unittest.TestCase):
    def test_committed_page_is_current(self):
        # Regenerate with the committed page's own date: a help-text or version
        # change not followed by `PYTHONPATH=src python3 -m clocwork.manpage` fails here.
        with open(PAGE, encoding="utf-8") as f:
            committed = f.read()
        date = re.match(r'\.TH CLOCWORK 1 "([^"]+)"', committed).group(1)
        self.assertEqual(committed, manpage.render(date=date))

    def test_main_prints_the_page(self):
        out = subprocess.run(["python3", "-m", "clocwork.manpage"], capture_output=True, text=True, check=True,
                             cwd=ROOT, env=dict(os.environ, PYTHONPATH=os.path.join(ROOT, "src")))
        self.assertTrue(out.stdout.startswith(".TH CLOCWORK 1"))

    @unittest.skipUnless(shutil.which("mandoc"), "mandoc not installed")
    def test_mandoc_lint_reports_no_warnings_or_errors(self):
        # man(1) exits 0 on a malformed page; mandoc's lint is what settles syntax.
        out = subprocess.run(["mandoc", "-T", "lint", PAGE], capture_output=True, text=True)
        problems = [l for l in out.stdout.splitlines() + out.stderr.splitlines() if "STYLE:" not in l]
        self.assertEqual(problems, [])

    @unittest.skipUnless(shutil.which("man"), "man not installed")
    def test_man_renders_the_committed_page(self):
        out = subprocess.run(["man", "-P", "cat", PAGE], capture_output=True, text=True,
                             env=dict(os.environ, MANPAGER="cat", PAGER="cat", MANWIDTH="80"))
        self.assertEqual(out.returncode, 0, out.stderr)
        text = re.sub(r".\x08", "", out.stdout)            # strip overstrike bold
        self.assertIn("CLOCWORK(1)", text)
        self.assertIn("--max-commits", text)
        self.assertIn("EXIT STATUS", text)


if __name__ == "__main__":
    unittest.main()
