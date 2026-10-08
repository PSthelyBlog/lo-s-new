import contextlib
import io
from unittest import mock

from los import sandbox, shell
from los.sandbox import Result
from tests.helpers import Folders, ShellCase, needs_sandbox


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
        shell.handle("help wrong needs forget stats exit")
        self.assertEqual(len(self.shown), 9)


class HelpTest(Folders):
    def test_help_says_what_a_command_may_touch(self):
        shown = []
        table, _ = shell.plugins.load(shell.state.ROOT / "plugins")
        shell.Shell(table, out=shown.append).handle("help fs.move sys.status note.add")
        self.assertEqual(shown, [
            "Move or rename a file or directory\nUsage: fs.move [--source VALUE] [--dest VALUE]\n"
            "  --source  what to move\n  --dest    new name, or the directory to move it into",
            "It can change or move what you name, so it asks before it runs.\n"
            "It may change or move what you give as --source, --dest.\n"
            "It sees no other file of yours and has no network.",
            "Show battery, CPU, memory or temperature status\nUsage: sys.status [--what VALUE]\n"
            "  --what  battery, cpu, memory or temperature; default all",
            "It only reads, so it runs as soon as you type it.\nIt may read /proc, /sys.\n"
            "It sees no other file of yours and has no network.",
            "Save a short text note\nUsage: note.add [--text VALUE] [--tag VALUE]\n"
            "  --text  the note\n  --tag   one word to file it under",
            "It changes what lo-s keeps for its plugin and no file of yours, so it runs as soon as you type it.\n"
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
            self.assertIn("the student, which reads plain language, did not answer: no answer from http://127.0.0.1:9/v1",
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
