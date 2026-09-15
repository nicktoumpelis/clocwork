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
        self.assertEqual(names[:4], ["NAME", "SYNOPSIS", "DESCRIPTION", "COMMANDS"])
        for section in ("ENVIRONMENT", "FILES", "EXIT STATUS", "SEE ALSO"):
            self.assertIn(section, names)

    def section(self, name):
        """The text of one .SS subsection, up to the next .SS or .SH."""
        m = re.search(rf"^\.SS {name}\n(.*?)(?=^\.S[SH] |\Z)", self.page, re.M | re.S)
        self.assertIsNotNone(m, name)
        return m.group(1)

    def test_every_command_and_option_from_the_parser_appears_in_its_own_section(self):
        parser = cli.build_parser()
        subparsers = next(a for a in parser._actions if a.choices)
        for name, sub in subparsers.choices.items():
            body = self.section(name)
            tags = re.findall(r"^\.TP\n\.[BI] (.+)$", body, re.M)
            for action in sub._actions:
                if "--help" in action.option_strings:
                    continue
                if action.option_strings:
                    tag = ", ".join(o.replace("-", "\\-") for o in action.option_strings)
                    self.assertTrue(any(t.startswith(tag) for t in tags), (name, tag, tags))
                else:
                    self.assertIn(manpage.escape(action.metavar or action.dest.upper()), tags, (name, tags))
                if action.help:
                    self.assertIn(manpage.escape(action.help.split("(")[0].strip()), body, (name, action.help))
            # Nothing the parser does not know sneaks into the list.
            self.assertEqual(len(tags), sum(1 for a in sub._actions if "--help" not in a.option_strings))

    def test_render_requires_its_workspace_and_tokens_takes_no_page_options(self):
        render = self.section("render")
        self.assertNotIn("(default: <repo", render)
        self.assertIn(".B \\-o, \\-\\-output DIR\nthe workspace to render", render)
        tokens = self.section("tokens")
        for absent in ("\\-\\-config", "\\-\\-locale", "\\-\\-no\\-open"):
            self.assertNotIn(absent, tokens, absent)

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
