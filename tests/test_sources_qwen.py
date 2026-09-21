import json
import os
import shutil
import tempfile
import unittest

from clocwork import agents
from clocwork.sources import qwen
from tests import agent_logs

# The four mock-backed runs in tests/fixtures/qwen, computed by hand from the
# counts the mock sent, without the reader: each call's input less its cache
# read, its output as it stands (every total there is input + output, so the
# reasoning is already inside), and its cache read.
#   mock-model:  0.24.2 openai, 1,001/21/300 and 1,002/22/300 (the memory
#                extractor's call); 0.4.0 openai, 1,007/27/300; 0.3.0's
#                Gemini-format message, 1,006/26/300.
#   mock-claude: 0.24.2 anthropic, twice 840/25/300 -- 840 being Qwen's sum of
#                500 uncached, 300 read and 40 written.
RECORDED = {"2026-09-21": {"turns": 6, "models": {
    "mock-model": {"input": 2_816, "output": 96, "cache_read": 1_200, "cache_write": 0},
    "mock-claude": {"input": 1_080, "output": 50, "cache_read": 600, "cache_write": 0}}}}
MODERN = "5cc0ed4c-6bfa-43a3-9632-1d87397171b2.jsonl"


def counts(input=0, output=0, cache_read=0, cache_write=0):
    return {"input": input, "output": output, "cache_read": cache_read, "cache_write": cache_write}


def api_response(cwd, uuid="u1", ts="2026-08-05T10:00:00.000Z", model="m", auth="openai",
                 input=0, output=0, cached=0, thoughts=0, total=None):
    """One api_response telemetry record, as Qwen Code 0.4.0 and later log it."""
    ev = {"event.name": "qwen-code.api_response", "event.timestamp": ts, "model": model,
          "auth_type": auth, "status_code": 200, "input_token_count": input,
          "output_token_count": output, "cached_content_token_count": cached,
          "thoughts_token_count": thoughts,
          "total_token_count": input + output if total is None else total}
    return {"uuid": uuid, "sessionId": "s1", "timestamp": ts, "type": "system", "cwd": cwd,
            "version": "0.24.2", "subtype": "ui_telemetry", "systemPayload": {"uiEvent": ev}}


class TestHomes(unittest.TestCase):
    def test_the_default_is_the_qwen_directory(self):
        self.assertEqual(qwen.default_homes({}), [os.path.expanduser(os.path.join("~", ".qwen"))])

    def test_qwen_home_replaces_it(self):
        self.assertEqual(qwen.default_homes({"QWEN_HOME": "/q"}), ["/q"])

    def test_a_home_given_with_a_tilde_is_expanded(self):
        self.assertEqual(qwen.default_homes({"QWEN_HOME": "~/q"}), [os.path.expanduser("~/q")])

    def test_a_runtime_directory_is_read_beside_the_global_one(self):
        # QWEN_RUNTIME_DIR moves the chats; sessions written before it was set
        # stay in the global directory.
        self.assertEqual(qwen.default_homes({"QWEN_RUNTIME_DIR": "/r", "QWEN_HOME": "/q"}), ["/r", "/q"])

    def test_a_runtime_directory_that_is_the_global_one_is_read_once(self):
        home = os.path.expanduser(os.path.join("~", ".qwen"))
        for runtime in (home + os.sep, os.path.join(home, ".")):
            with self.subTest(runtime=runtime):
                self.assertEqual(qwen.default_homes({"QWEN_RUNTIME_DIR": runtime}), [home])


class TestAttribution(unittest.TestCase):
    def test_the_trailer_qwen_code_appends_names_it(self):
        # Qwen Code itself appends this to a commit it makes (Config's
        # gitCoAuthor), recorded in public commits, QwenLM/qwen-code's own
        # 642c1a55d4 among them.
        name = agents.detect_agent("Fix\n\nCo-authored-by: Qwen-Coder <qwen-coder@alibabacloud.com>\n")
        self.assertEqual(name, "Qwen Code")
        self.assertTrue(qwen.AGENT.search(name))

    def test_the_product_s_own_name_names_it_too(self):
        self.assertEqual(agents.detect_agent("Fix\n\nCo-Authored-By: Qwen Code <x@y>"), "Qwen Code")

    def test_alibaba_s_own_coder_models_are_not_qwen_code(self):
        # qwen-coder-plus and qwen-coder-turbo are models Alibaba serves, and a
        # hyphen after the name makes it a longer one.
        for text in ("Cline (qwen-coder-plus) <noreply@cline.bot>", "Roo Code (qwen-coder-turbo)",
                     "OpenHands <openhands@all-hands.dev> (qwen-coder-plus-latest)",
                     "Continue <qwen-coder-plus@x.com>"):
            with self.subTest(text=text):
                self.assertIsNone(agents.detect_agent(f"Fix\n\nCo-authored-by: {text}"))

    def test_a_qwen_model_run_through_another_tool_is_not_qwen_code(self):
        # "Qwen" names the model as well as the product, so a trailer from
        # another tool that ran one belongs to that tool, or to nobody.
        for text, name in (("opencode (qwen/qwen3-coder) <x@y>", "OpenCode"),
                           ("aider (qwen/qwen3-coder) <x@y>", "aider"),
                           ("Cline (qwen/qwen3-coder) <x@y.com>", None),
                           ("Qwen 2.5 Coder via Roo Code <noreply@roocode.com>", None),
                           ("Continue (Qwen-2.5-coder) <x@y.com>", None),
                           ("Qwen <noreply@qwen.ai>", None),
                           ("Qwen3-Coder <noreply@x.com>", None)):
            with self.subTest(text=text):
                self.assertEqual(agents.detect_agent("Fix\n\nCo-Authored-By: " + text), name)


class TestRecordings(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = os.path.realpath(tmp.name)
        self.repo = os.path.join(self.root, "agent-sample")
        os.makedirs(self.repo)
        self.home = os.path.join(self.root, "home", ".qwen")
        agent_logs.install("qwen", self.home, self.repo)

    def scan(self, repo=None):
        return qwen.scan(repo or self.repo, [self.home])

    def test_every_recorded_call(self):
        result = self.scan()
        self.assertEqual(result.days, RECORDED)
        self.assertEqual((result.malformed, result.skipped), (0, 0))

    def test_a_side_call_is_counted_like_the_main_one(self):
        # 0.24.2 logs the memory extractor's call as a second api_response;
        # only the main call has an assistant message beside it, so reading
        # the messages would miss it.
        keep = {MODERN}
        chats = os.path.join(self.home, "projects", "-work-agent-sample", "chats")
        for name in os.listdir(chats):
            if name not in keep:
                os.remove(os.path.join(chats, name))
        shutil.rmtree(os.path.join(self.home, "tmp"))
        day = self.scan().days["2026-09-21"]
        self.assertEqual((day["turns"], day["models"]["mock-model"]), (2, counts(1_403, 43, cache_read=600)))

    def test_a_repository_elsewhere_is_not_matched(self):
        self.assertIsNone(self.scan(os.path.join(self.root, "elsewhere")))


class TestRules(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.root = os.path.realpath(tmp.name)
        self.repo = os.path.join(self.root, "repo")
        os.makedirs(self.repo)
        self.home = os.path.join(self.root, "home", ".qwen")

    def write(self, records, name="s1.jsonl", project="-repo"):
        path = os.path.join(self.home, "projects", project, "chats", name)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            f.write("".join((r if isinstance(r, str) else json.dumps(r)) + "\n" for r in records))
        return path

    def scan(self):
        return qwen.scan(self.repo, [self.home])

    def day(self, date="2026-08-05"):
        return self.scan().days[date]

    def test_the_cache_read_comes_out_of_the_input(self):
        self.write([api_response(self.repo, input=1_000, output=20, cached=300)])
        self.assertEqual(self.day()["models"]["m"], counts(700, 20, cache_read=300))

    def test_reasoning_outside_a_total_is_added_to_the_output(self):
        # Gemini's convention, where the total counts the thoughts beside the
        # candidates. The record's own total decides, as in the Gemini reader.
        self.write([api_response(self.repo, auth="gemini", input=1_100, output=30, cached=300,
                                 thoughts=9, total=1_139)])
        self.assertEqual(self.day()["models"]["m"]["output"], 39)

    def test_reasoning_inside_a_total_is_not_added_again(self):
        self.write([api_response(self.repo, input=1_001, output=21, cached=300, thoughts=7, total=1_022)])
        self.assertEqual(self.day()["models"]["m"]["output"], 21)

    def test_a_record_s_total_decides_over_its_auth_type(self):
        # A total that disagrees with what the auth type would suggest is
        # still the evidence: it is what the provider sent.
        for auth, total, output in (("openai", 1_031, 30), ("gemini", 1_022, 21)):
            with self.subTest(auth=auth):
                self.write([api_response(self.repo, auth=auth, input=1_001, output=21, cached=300,
                                         thoughts=9 if auth == "openai" else 7, total=total)])
                self.assertEqual(self.day()["models"]["m"]["output"], output)

    def test_an_openai_record_with_no_total_does_not_count_its_reasoning_twice(self):
        # Some OpenAI-compatible servers send no total. The total is what
        # usually says the reasoning is inside the output; without it, the
        # auth type does.
        for auth in ("openai", "openai-responses", "qwen-oauth", "anthropic"):
            with self.subTest(auth=auth):
                self.write([api_response(self.repo, auth=auth, input=1_001, output=21, cached=300,
                                         thoughts=7, total=0)])
                self.assertEqual(self.day()["models"]["m"]["output"], 21)

    def test_a_gemini_record_with_no_total_adds_its_thoughts(self):
        self.write([api_response(self.repo, auth="gemini", input=1_100, output=30, cached=300,
                                 thoughts=9, total=0)])
        self.assertEqual(self.day()["models"]["m"]["output"], 39)

    def test_each_call_is_a_turn_on_its_own_day(self):
        self.write([api_response(self.repo, uuid="a", ts="2026-08-05T23:59:00.000Z", input=100, output=1),
                    api_response(self.repo, uuid="b", ts="2026-08-06T00:01:00.000Z", input=200, output=2)])
        days = self.scan().days
        self.assertEqual({d: (v["turns"], v["models"]["m"]) for d, v in days.items()},
                         {"2026-08-05": (1, counts(100, 1)), "2026-08-06": (1, counts(200, 2))})

    def test_a_call_in_a_directory_below_the_repository_counts(self):
        self.write([api_response(os.path.join(self.repo, "src"), input=100, output=1)])
        self.assertEqual(self.day()["models"]["m"], counts(100, 1))

    def test_a_sibling_whose_name_starts_the_same_is_not_the_repository(self):
        self.write([api_response(self.repo + "-other", input=100, output=1)])
        self.assertIsNone(self.scan())

    def test_the_same_record_in_two_files_is_counted_once(self):
        record = api_response(self.repo, input=100, output=1)
        self.write([record], name="a.jsonl")
        self.write([record], name="b.jsonl", project="-copy")
        self.assertEqual(self.day()["turns"], 1)

    def test_an_assistant_message_s_usage_is_not_counted_again(self):
        self.write([api_response(self.repo, input=100, output=1),
                    {"uuid": "m1", "type": "assistant", "cwd": self.repo, "timestamp": "2026-08-05T10:00:00.000Z",
                     "model": "m", "usageMetadata": {"promptTokenCount": 100, "candidatesTokenCount": 1,
                                                     "totalTokenCount": 101}}])
        self.assertEqual((self.day()["turns"], self.day()["models"]["m"]), (1, counts(100, 1)))

    def test_a_failed_call_is_not_counted(self):
        error = api_response(self.repo, input=100, output=1)
        error["systemPayload"]["uiEvent"]["event.name"] = "qwen-code.api_error"
        self.write([error])
        self.assertIsNone(self.scan())

    def test_another_event_that_mentions_a_response_is_not_counted(self):
        # The line filter only looks for the name; the event's own name decides.
        other = api_response(self.repo, input=100, output=1)
        other["systemPayload"]["uiEvent"]["event.name"] = "qwen-code.api_error"
        other["systemPayload"]["uiEvent"]["retried"] = "qwen-code.api_response"
        self.write([other])
        self.assertIsNone(self.scan())

    def test_a_line_that_is_not_json_is_counted(self):
        self.write(['{"subtype": "ui_telemetry", "qwen-code.api_response"', api_response(self.repo, input=100)])
        result = self.scan()
        self.assertEqual((result.days["2026-08-05"]["models"]["m"], result.malformed), (counts(100), 1))

    def test_a_call_with_no_day_is_counted(self):
        record = api_response(self.repo, input=100)
        record["systemPayload"]["uiEvent"]["event.timestamp"] = None
        record["timestamp"] = None
        self.write([record])
        result = self.scan()
        self.assertEqual((result.days, result.malformed), ({}, 1))

    def test_a_call_with_no_time_of_its_own_takes_its_record_s(self):
        record = api_response(self.repo, input=100)
        record["systemPayload"]["uiEvent"]["event.timestamp"] = None
        record["timestamp"] = "2026-08-06T10:00:00.000Z"
        self.write([record])
        self.assertEqual(list(self.scan().days), ["2026-08-06"])

    def test_a_record_of_the_wrong_shape_is_read_as_missing(self):
        for payload in ("gone", {"uiEvent": "gone"}):
            with self.subTest(payload=payload):
                record = api_response(self.repo, input=100)
                record["systemPayload"] = payload
                self.write([record])
                self.assertIsNone(self.scan())

    def test_a_call_whose_counts_are_not_numbers_belongs_but_adds_nothing(self):
        record = api_response(self.repo, input=100)
        record["systemPayload"]["uiEvent"] = {"event.name": "qwen-code.api_response", "input_token_count": "many",
                                              "event.timestamp": "2026-08-05T10:00:00.000Z"}
        self.write([record])
        result = self.scan()
        self.assertEqual((result.days, result.malformed, result.skipped), ({}, 0, 0))

    def test_a_file_that_cannot_be_read_is_skipped(self):
        path = self.write([api_response(self.repo, input=100)])
        os.remove(path)
        os.symlink(os.path.join(self.root, "gone.jsonl"), path)
        result = self.scan()
        self.assertEqual((result.days, result.skipped), ({}, 1))

    def test_a_directory_that_cannot_be_listed_is_skipped_not_raised(self):
        # One unlistable directory must not stop every other source's scan.
        self.write([api_response(self.repo, input=100)])
        chats = os.path.join(self.home, "projects", "-repo", "chats")
        os.chmod(chats, 0)
        self.addCleanup(os.chmod, chats, 0o755)
        result = self.scan()
        self.assertEqual((result.days, result.skipped), ({}, 1))

    def test_an_archived_session_is_read(self):
        self.write([api_response(self.repo, input=100)], name=os.path.join("archive", "s1.jsonl"))
        self.assertEqual(self.day()["models"]["m"], counts(100))

    def test_a_project_directory_that_cannot_be_entered_is_skipped(self):
        self.write([api_response(self.repo, input=100)])
        project = os.path.join(self.home, "projects", "-repo")
        os.chmod(project, 0)
        self.addCleanup(os.chmod, project, 0o755)
        result = self.scan()
        self.assertEqual((result.days, result.skipped), ({}, 1))

    def test_no_logs_is_none(self):
        self.assertIsNone(self.scan())


if __name__ == "__main__":
    unittest.main()
