import http.server
import threading
import unittest
from unittest import mock

from los import plugins, route
from los.models import ClaudeCli, ModelUnavailable, OpenAICompat, complete_valid, validate
from tests.helpers import NONE, TABLE, Scripted, call


class RouteTest(unittest.TestCase):
    def test_schema_allows_only_a_command_s_own_parameters(self):
        schema = route.schema(TABLE)
        self.assertEqual(validate(call("fs.list", path="."), schema), [])
        self.assertEqual(validate(call("fs.list"), schema), [])
        self.assertEqual(validate(NONE, schema), [])
        for wrong in (call("fs.list", text="x"), call("fs.list", **{"*.pdf": "*.pdf"}), call("fs.delete"),
                      {"call": {"command": "fs.list"}}, {"command": "fs.list", "args": {}}):
            self.assertTrue(validate(wrong, schema), wrong)

    def test_the_table_lists_commands_by_name_with_hints(self):
        table = dict(TABLE)
        table["fs.list"] = plugins.Command("fs.list", "List", {"path": plugins.Param("a directory", "read", "."),
                                                               "sort_by": plugins.Param()})
        rows = route.system_prompt(table).split("parameters\n")[1].splitlines()
        self.assertEqual(rows[0], "fs.list | List | path (a directory), sort_by")
        self.assertEqual([row.split(" | ")[0] for row in rows], sorted(table))

    def test_what_changes_from_line_to_line_comes_last(self):
        student = Scripted(NONE, NONE)
        route.ask(student, TABLE, "order a pizza")
        first = student.system
        route.ask(student, TABLE, "book a flight")
        self.assertEqual((student.system, student.user), (first, "book a flight"))
        self.assertTrue(first.startswith(route.INSTRUCTIONS) and first.endswith(route.table_text(TABLE)))

    def test_ask_returns_the_choice(self):
        choice = route.ask(Scripted(call("fs.list", path="~")), TABLE, "what is in my home folder")
        self.assertEqual((choice.command, choice.args, choice.meta["seconds"]), ("fs.list", {"path": "~"}, 1.5))
        self.assertIsNone(route.ask(Scripted(NONE), TABLE, "order a pizza").command)

    def test_a_parameter_left_empty_is_not_passed_on(self):
        choice = route.ask(Scripted(call("fs.list", path="~", sort_by=" ")), TABLE, "what is in my home folder")
        self.assertEqual(choice.args, {"path": "~"})

    def test_invalid_output_is_asked_again(self):
        student = Scripted(call("fs.list", colour="red"), call("fs.list", path="."))
        self.assertEqual(route.ask(student, TABLE, "list things").args, {"path": "."})
        self.assertEqual(student.calls, 2)

    def test_unreachable_model_is_not_retried(self):
        student = Scripted(ModelUnavailable("down"), NONE)
        with self.assertRaises(ModelUnavailable):
            complete_valid(student, "", "", route.schema(TABLE))
        self.assertEqual(student.calls, 1)


class ReachTest(unittest.TestCase):
    def test_a_server_that_answers_is_there_whatever_it_says_and_nothing_at_the_address_is_not(self):
        server = http.server.HTTPServer(("127.0.0.1", 0), http.server.BaseHTTPRequestHandler)   # it answers 501 to all
        server.RequestHandlerClass.log_message = lambda *args: None
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        self.assertIsNone(OpenAICompat(f"http://127.0.0.1:{server.server_port}/v1", "m").down())
        self.assertEqual(OpenAICompat("http://127.0.0.1:9/v1/", "m").down(), "nothing answers at http://127.0.0.1:9/v1")

    def test_the_claude_program_is_there_or_not(self):
        with mock.patch("shutil.which", return_value=None):
            self.assertEqual(ClaudeCli().down(), "the claude program is not installed")
            with self.assertRaisesRegex(ModelUnavailable, "the claude program is not installed"):
                ClaudeCli().complete("", "", {})
        with mock.patch("shutil.which", return_value="/usr/bin/claude"):
            self.assertIsNone(ClaudeCli().down())
