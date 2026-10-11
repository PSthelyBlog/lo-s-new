import contextlib
import io
from unittest import mock

from los import cases, sandbox, shell
from los.sandbox import Result
from los.say import Aside, Exact, Fault, Warn, voices
from tests.helpers import NONE, Folders, ShellCase, needs_sandbox


class ShellTest(ShellCase):
    def test_a_structured_command_runs_as_typed(self):
        self.shell().handle("fs.list --path /tmp")
        self.assertEqual((self.ran.calls, self.asked, self.shown), ([("fs.list", {"path": "/tmp"})], [], ["ran fs.list"]))
        self.shell().handle("note.add --text 'buy oat milk'")       # writing is not asked about when typed in full
        self.assertEqual((self.ran.calls, self.asked), ([("note.add", {"text": "buy oat milk"})], []))

    def test_a_typed_destructive_command_needs_an_explicit_yes(self):
        self.shell(answers=[""]).handle("fs.move --source a --dest b")
        self.assertEqual((self.ran.calls, self.shown), ([], ["→ fs.move --source a --dest b", "Not run."]))
        self.assertEqual(self.asked, ["It makes changes that cannot be undone. Run it? [y/N] "])
        self.shell(answers=["y"]).handle("fs.move --source a --dest b")
        self.assertEqual(self.ran.calls, [("fs.move", {"source": "a", "dest": "b"})])

    def test_nobody_to_ask_means_no(self):
        self.shell().handle("fs.move --source a --dest b")      # the question hits end of input
        self.assertEqual(self.ran.calls, [])

    def test_only_a_clear_yes_or_no_is_an_answer(self):
        # A line typed too soon is neither, even when it starts with a y.
        self.shell(answers=["yes but in ~/work", "fs.list", "YES"]).handle("fs.move --source a --dest b")
        self.assertEqual(self.asked, ["It makes changes that cannot be undone. Run it? [y/N] "] * 3)
        self.assertEqual(self.shown, ["→ fs.move --source a --dest b", "Answer y or n.", "Answer y or n.", "ran fs.move"])
        for answers in (["nope", "n"], ["No"], ["yep"]):       # the last one ends with nobody left to ask
            self.shell(answers=answers).handle("fs.move --source a --dest b")
            self.assertEqual((self.ran.calls, self.shown[-1]), ([], "Not run."))

    def test_wrong_use_shows_how_to_type_it(self):
        self.shell().handle("fs.move --from a")
        self.assertEqual(self.shown, ["fs.move has no parameter --from\nUsage: fs.move [--source VALUE] [--dest VALUE]"])
        self.assertEqual(self.ran.calls, [])

    def test_a_refusal_and_a_fault_read_differently(self):
        self.shell(result=Result("/nope is not a directory", ok=False)).handle("fs.list --path /nope")
        self.assertEqual(self.shown, ["fs.list: /nope is not a directory"])
        self.shell(result=Result("Traceback ...", ok=False, broke=True)).handle("fs.list")
        self.assertEqual(self.shown, ["fs.list broke. The fault is in the command, not in what you typed.\nTraceback ..."])
        self.shell(result=Result("")).handle("fs.list")
        self.assertEqual(self.shown, [])

    def test_builtins(self):
        shell = self.shell()
        self.assertFalse(shell.handle("exit"))
        self.assertTrue(shell.handle("   "))
        shell.handle("help")
        self.assertEqual(self.shown[0].splitlines()[1], "fs.move   Test command fs.move")
        shell.handle("help help nope")
        self.assertEqual(self.shown[-2:], ["help lists the commands. help NAME explains one and says what it may touch.",
                                           "There is no command named nope."])
        shell.handle("help wrong means needs forget delegate trace rule stats exit")
        self.assertEqual(len(self.shown), 13)


class HelpTest(Folders):
    def test_help_says_what_a_command_may_touch(self):
        shown = []
        table, _ = shell.plugins.load(shell.state.ROOT / "plugins")
        shell.Shell(table, out=shown.append).handle("help fs.move sys.status note.add")
        self.assertEqual(shown, [
            "Move or rename a file or directory\nUsage: fs.move [--source VALUE] [--dest VALUE]\n"
            "  --source  what to move\n  --dest    new name, or the directory to move it into",
            "It can change or remove what you name, so it asks before it runs.\n"
            "It may change, move or remove what you give as --source, --dest.\n"
            "It sees no other file of yours and has no network.",
            "Show battery, CPU, memory or temperature status\nUsage: sys.status [--what VALUE]\n"
            "  --what  battery, cpu, memory or temperature; default all",
            "It only reads, so it runs as soon as you type it.\nIt may read /proc, /sys.\n"
            "It sees no other file of yours and has no network.",
            "Save a short text note\nUsage: note.add [--text VALUE] [--tag VALUE]\n"
            "  --text  the note\n  --tag   one word to file it under",
            "It can add something new and cannot change what exists, so it runs as soon as you type it.\n"
            "It may read and change the data lo-s keeps for the note commands.\n"
            "It sees no other file of yours and has no network."])


class MainTest(Folders):
    def said(self, *argv):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            shell.main(list(argv))
        return out.getvalue()

    @needs_sandbox
    def test_one_line_from_the_command_line(self):
        self.assertTrue(self.said("-c", "sys.status --what memory").startswith("Memory: "))
        self.assertEqual(self.said("-c", "note.add --text hello"), "Noted.\n")

    def test_the_student_is_the_one_the_settings_name(self):
        settings = self.root / "los.toml"
        settings.write_text('[roles]\nstudent = "none-there"\n[providers.none-there]\nkind = "openai"\n'
                            'url = "http://127.0.0.1:9/v1"\nmodel = "m"\n')
        with mock.patch.dict("os.environ", {"LOS_CONFIG": str(settings)}):
            self.assertIn("the student, which reads plain language, did not answer: nothing answers at "
                          "http://127.0.0.1:9/v1.\n",
                          self.said("-c", "what is in this folder"))
        with mock.patch.dict("os.environ", {"LOS_CONFIG": str(self.root / "missing.toml")}):
            self.assertIn("no model is set up to read plain language", self.said("-c", "what is in this folder"))

    def test_it_says_so_when_commands_cannot_be_sandboxed(self):
        with mock.patch.object(sandbox, "unusable", lambda: "bubblewrap (the bwrap program) is not installed"):
            said = self.said("-c", "note.list")
        self.assertIn("Commands cannot be sandboxed here: bubblewrap (the bwrap program) is not installed.", said)
        self.assertTrue(said.endswith("No notes.\n"))
        with mock.patch.dict("os.environ", {"LOS_NO_SANDBOX": "1"}):
            self.assertTrue(self.said("-c", "note.list").startswith("LOS_NO_SANDBOX is set"))

    def test_a_faulty_plugin_is_reported_and_the_rest_works(self):
        self.plugin("name = ", "", folder="broken")
        self.plugin('name = "ok"\n[commands.go]\ndescription = "Go"\n', "def do_go():\n    return 'gone'\n", folder="ok")
        with mock.patch.dict("os.environ", {"LOS_PLUGINS": str(self.root / "plugins")}):
            said = self.said("-c", "ok.go")
        self.assertIn("plugins/broken was left out", said)
        self.assertTrue(said.endswith("gone\n"))


class StartTest(ShellCase):
    def test_the_greeting_says_what_is_here_what_waits_and_where_paths_are_taken_from(self):
        import os
        home = os.path.expanduser("~")
        with mock.patch("os.getcwd", return_value=home + "/work/site"):
            self.assertEqual(self.shell().greeting(), "lo-s: 3 commands, working in ~/work/site.")
            cases.queue("order a large pizza", "student")
            self.assertEqual(self.shell().greeting(), "lo-s: 3 commands, 1 need waiting, working in ~/work/site.")
        with mock.patch("os.getcwd", return_value="/srv/data"):
            self.assertTrue(self.shell(commands={}).greeting().startswith("lo-s: 0 commands, 1 need waiting, working in /srv/data."))

    def test_the_greeting_says_so_when_the_student_cannot_be_reached_and_only_then(self):
        shell = self.shell()
        self.student.down = lambda: None
        self.assertEqual(len(shell.greeting().splitlines()), 1)
        self.student.down = lambda: "nothing answers at http://127.0.0.1:8080/v1"
        self.assertEqual(shell.greeting().splitlines()[1],
                         "The student is not answering: nothing answers at http://127.0.0.1:8080/v1. If it is the local "
                         "model, scripts/serve.sh starts it. Lines you settled and typed commands work without it.")
        shell.student = None                                    # no model is set up to read plain language
        self.assertEqual(len(shell.greeting().splitlines()), 1)

    def test_a_wait_for_the_student_is_the_terminals_to_show_and_is_said_nowhere_else(self):
        shell, waits = self.shell(NONE, NONE), []

        @contextlib.contextmanager
        def watch(text, kept):
            waits.append((text, kept, len(self.shown)))
            yield

        shell.handle("order a large pizza")
        shell.watch = watch
        shell.handle("book a flight")
        self.assertEqual(waits, [("Asking scripted", False, 1)])
        self.assertFalse(any(said.startswith("Asking") for said in self.shown))


class VoicesTest(ShellCase):
    """The shell says each thing in a voice. The words are what they were."""

    def test_a_commands_own_output_is_shown_exactly_and_its_failure_is_a_fault(self):
        self.shell(result=Result("  3B  a.txt")).handle("fs.list")
        self.assertEqual(voices(self.shown[-1]), [(Exact, "  3B  a.txt")])
        self.shell(result=Result("/nope is not a directory", ok=False)).handle("fs.list --path /nope")
        self.assertEqual(voices(self.shown[-1]), [(Fault, "fs.list: /nope is not a directory")])
        self.shell(result=Result("Traceback ...", ok=False, broke=True)).handle("fs.list")
        self.assertEqual(voices(self.shown[-1]), [(Fault, "fs.list broke. The fault is in the command, not in what you "
                                                          "typed.\n"), (Exact, "Traceback ...")])

    def test_what_could_be_typed_next_is_an_aside_and_what_cannot_be_undone_is_a_warning(self):
        shell = self.shell(NONE, answers=["n"])
        shell.handle("order a large pizza")
        self.assertEqual(voices(self.shown[-1]), [(str, "Nothing here does that yet. It is queued as need 1. "),
                                                  (Aside, "needs lists the queue, and forget 1 drops it.")])
        shell.handle("fs.move --source a --dest b")
        self.assertEqual(voices(self.asked[-1]), [(Warn, "It makes changes that cannot be undone. "), (str, "Run it?"),
                                                  (str, " [y/N] ")])
        shell.handle("improve")
        self.assertEqual([voice for voice, _ in voices(self.shown[-1])], [str, Aside])
        self.assertEqual(voices(shell.greeting())[0][0], Aside)

    def test_the_help_text_is_filled_to_a_width_unless_what_shows_it_breaks_lines_itself(self):
        shell = self.shell()
        shell.handle("help")
        self.assertTrue(all(len(line) <= 88 for line in self.shown[-1].splitlines()))
        shell.width = None
        shell.handle("help")
        self.assertEqual(len(self.shown[-1].splitlines()), 2)       # an empty line, and the text as one paragraph
