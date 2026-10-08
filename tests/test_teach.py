"""The teacher step, with a scripted teacher and a scripted student. Proposals are tried in the
real sandbox."""
import copy
import json
import os
import shutil
import urllib.request
from unittest import mock

from los import cases, judge, plugins, sandbox, state, teach
from los.models import ModelUnavailable
from los.shell import Shell
from tests.helpers import NONE, Folders, Scripted, call, needs_sandbox


def args(**given):
    return [{"name": name, "value": value} for name, value in given.items()]


DELETE = {
    "plugin": "fs", "verb": "delete", "effect": "destructive",
    "descriptions": ["Delete one file for good", "Remove (erase) a single named file; not for folders"],
    "params": [{"name": "path", "hint": "the file to delete, such as old-report.txt", "path": "write"}],
    "code": '''"""Delete one file."""
import os

from los import CommandError, remove


def do_delete(path=None):
    if not path:
        raise CommandError("needs --path")
    if not os.path.exists(path):
        raise CommandError(f"{path} does not exist")
    if os.path.isdir(path):
        raise CommandError(f"{path} is a directory, and this deletes one file")
    remove(path)
    return f"Deleted {path}"
''',
    "lines": [{"line": "delete old-report.txt", "args": args(path="old-report.txt")},
              {"line": "get rid of draft.md", "args": args(path="draft.md")}],
    "others": [{"line": "rename a.txt to b.txt", "command": "fs.move"}, {"line": "empty the bin", "command": "none"}],
    "checks": [
        {"args": args(path="old.txt"), "files": [{"path": "old.txt", "content": "x"}], "expect": "output",
         "contains": ["deleted"], "then": [{"path": "old.txt", "state": "absent"}]},
        {"args": args(path="missing.txt"), "expect": "error", "contains": ["does not exist"]},
        {"args": [], "expect": "error", "contains": ["--path"]},
        {"args": args(path="folder"), "files": [{"path": "folder/", "content": ""}, {"path": "kept.txt", "content": "k"}],
         "expect": "error", "contains": ["directory"],
         "then": [{"path": "folder", "state": "present"}, {"path": "kept.txt", "state": "present", "content": "k"}]},
    ],
}
COPY = {
    "plugin": "fs", "verb": "copy", "effect": "write",
    "descriptions": ["Copy a file, or make a backup copy of it beside the original"],
    "params": [{"name": "source", "hint": "the file to copy", "path": "read"},
               {"name": "dest", "hint": "name of the copy; left out, the same name with .bak", "path": "create",
                "default": "{source}.bak"}],
    "code": '''import os
import shutil

from los import CommandError


def do_copy(source=None, dest=None):
    if not source:
        raise CommandError("needs --source")
    if not os.path.isfile(source):
        raise CommandError(f"{source} is not a file")
    if os.path.lexists(dest):
        raise CommandError(f"{dest} already exists; nothing was copied")
    shutil.copy2(source, dest)
    return f"Copied {source} to {dest}"
''',
    "lines": [{"line": "make a backup copy of config.yaml", "args": args(source="config.yaml")}],
    "others": [{"line": "move config.yaml to old", "command": "fs.move"}],
    "checks": [
        {"args": args(source="config.yaml"), "files": [{"path": "config.yaml", "content": "a: 1\n"}], "expect": "output",
         "contains": ["Copied"], "then": [{"path": "config.yaml.bak", "state": "present", "content": "a: 1\n"},
                                          {"path": "config.yaml", "state": "present", "content": "a: 1\n"}]},
        {"args": args(source="config.yaml", dest="other.yaml"),
         "files": [{"path": "config.yaml", "content": "a"}, {"path": "other.yaml", "content": "b"}], "expect": "error",
         "contains": ["already exists"], "then": [{"path": "other.yaml", "state": "present", "content": "b"}]},
    ],
}
WEATHER = {
    "plugin": "weather", "verb": "forecast", "effect": "read", "hosts": ["api.example.org"],
    "descriptions": ["Show the weather forecast for a town"],
    "params": [{"name": "place", "hint": "town"}],
    "code": '''from los import CommandError, fetch


def do_forecast(place=None):
    if not place:
        raise CommandError("needs --place")
    return fetch("https://api.example.org/forecast?place=" + place)
''',
    "lines": [{"line": "what's the weather in Lyon", "args": args(place="Lyon")}],
    "others": [{"line": "is the laptop running hot", "command": "sys.status"}],
    "checks": [{"args": [], "expect": "error", "contains": ["--place"]},
               {"args": args(place="Lyon"), "expect": "output", "contains": ["°C"]}],
}


CHAT = {
    "plugin": "chat", "verb": "ask", "effect": "read", "asks": ["student", "teacher"], "judges": ["tone"],
    "ranges": [{"name": "tone", "low": "0", "high": "10.5"}],
    "descriptions": ["Put a question to the student or the teacher; only for lines that name one of them"],
    "params": [{"name": "to", "hint": "student or teacher"}, {"name": "message", "hint": "the question"}],
    "code": '''"""Put a question to one of the models."""
from los import CommandError, ask, judge


def do_ask(to=None, message=None):
    if not message:
        raise CommandError("Give the question with --message.")
    if to == "tone":
        return judge("tone", "Is this message polite or curt?", message, ["polite", "curt"])
    return ask(to or "student", message)
''',
    "lines": [{"line": "ask the student what a mutex is", "args": args(to="student", message="what is a mutex")}],
    "others": [{"line": "what is a mutex", "command": "none"}],
    "checks": [{"args": [], "expect": "error", "contains": ["--message"]},
               {"args": args(to="student", message="what is a mutex"), "expect": "output", "contains": []},
               {"args": args(to="teacher", message="what is a mutex"), "expect": "output", "contains": []},
               {"args": args(to="tone", message="Do it now."), "expect": "output", "contains": ["curt"]}],
}


def write(proposal, reason="Nothing does this yet, and a small command can."):
    return {"answer": "write", "reason": reason, "write": copy.deepcopy(proposal)}


class Case(Folders):
    """Gives each test the starter plugins in a plugin folder of its own."""

    def setUp(self):
        super().setUp()
        self.plugin_dir = self.root / "plugins"
        for name in ("fs", "note", "sys"):
            shutil.copytree(state.ROOT / "plugins" / name, self.plugin_dir / name)
        self.table, _ = plugins.load(self.plugin_dir)
        self.teacher = Scripted()
        self.teacher.model = "scripted-teacher"

    def staged(self, proposal, words="what the user said"):
        return teach.stage(copy.deepcopy(proposal), words, self.teacher, self.table, teach.scratch())


class AskTest(Case):
    def ask(self, *outputs, **more):
        self.teacher.outputs = list(outputs)
        return teach.ask(self.teacher, "make a backup copy of config.yaml", self.table,
                         {"student": Scripted(), "teacher": self.teacher}, state.ROOT / "plugins" / "fs", **more)

    def test_the_teacher_is_told_how_lo_s_works_what_exists_and_what_models_there_are(self):
        advice, meta = self.ask({"answer": "cannot", "reason": "It  needs\na payment."})
        self.assertEqual((advice.answer, advice.reason, meta["seconds"]), ("cannot", "It needs a payment.", 1.5))
        told = self.teacher.system
        self.assertTrue(told.startswith(teach.BRIEF))
        for part in ("student: a scripted model", "teacher: a scripted model",
                     "fs.move | Move or rename a file or directory | source (what to move), dest (",
                     'source = { hint = "what to move", path = "write" }', "def do_move(source=None, dest=None):"):
            self.assertIn(part, told)
        self.assertEqual(self.teacher.user, "What the user wants: make a backup copy of config.yaml")

    def test_a_command_to_run_must_exist_with_those_parameters(self):
        advice, _ = self.ask({"answer": "run", "reason": "r", "command": "fs.list", "args": args(**{"sort-by": "size"})})
        self.assertEqual((advice.command, advice.args), ("fs.list", {"sort_by": "size"}))
        for wrong in ({"command": "fs.copy", "args": []}, {"command": "fs.list", "args": args(colour="red")}, {}):
            with self.assertRaises(RuntimeError):
                self.ask({"answer": "run", "reason": "r", **wrong})
        for wrong in ({"answer": "ask", "reason": "r"}, {"answer": "write", "reason": "r"}):
            with self.assertRaises(RuntimeError):
                self.ask(wrong)

    def test_an_answer_of_the_wrong_shape_is_not_asked_for_again(self):
        with self.assertRaises(RuntimeError):
            self.ask({"answer": "maybe", "reason": "r"}, {"answer": "cannot", "reason": "r"})
        self.assertEqual(self.teacher.calls, 1)     # asking again is another call, and the user's to decide

    def test_what_it_asked_and_what_went_wrong_go_back_with_the_words(self):
        self.ask({"answer": "cannot", "reason": "r"}, exchange=[("Which folder?", "the current one")],
                 earlier=(COPY, ["The check fs.copy --source a should have worked and gave an error: boom"]))
        said = self.teacher.user
        self.assertTrue(said.startswith("What the user wants: make a backup copy of config.yaml\n\n"
                                        "You asked: Which folder?\nThe user answered: the current one\n\n"
                                        "You proposed this command for it:\n{"))
        self.assertIn('"default": "{source}.bak"', said)
        self.assertIn("this is what went wrong:\n- The check fs.copy --source a should have worked", said)


@needs_sandbox
class ProposalTest(Case):
    def test_a_proposal_is_read_the_way_any_plugin_is(self):
        found = self.staged(COPY, words='copy "this"')
        command = found.command
        self.assertEqual((found.fault, command.name, command.effect, command.written_by, found.folder.name),
                         ("", "fs.copy", "write", "scripted-teacher", "fs.copy"))
        self.assertEqual(command.params, {"source": plugins.Param("the file to copy", "read"),
                                          "dest": plugins.Param("name of the copy; left out, the same name with .bak",
                                                                "create", "{source}.bak")})
        self.assertIn('words = "copy \\"this\\""', (found.folder / "plugin.toml").read_text())
        self.assertEqual(json.loads((found.folder / "proposal.json").read_text())["lines"], COPY["lines"])
        weather = self.staged(WEATHER).command
        self.assertEqual((weather.hosts, weather.description), (("api.example.org",), "Show the weather forecast for a town"))

    def test_a_proposal_that_cannot_be_a_plugin_says_why(self):
        for change, said in (({"verb": "list"}, "fs.list already exists"), ({"descriptions": []}, "gave no description"),
                             ({"verb": 'x]\n[commands.y'}, "A name in it is not lower-case letters"),
                             ({"params": [{"name": "Path", "hint": ""}]}, "A name in it is not lower-case letters"),
                             ({"plugin": "file_system"}, "a plugin name is lower-case letters and digits"),
                             ({"code": "def do_delete(:\n"}, "commands.py does not parse"),
                             ({"code": "def do_delete(file=None):\n    pass\n"}, "exactly the declared parameters: path"),
                             ({"effect": "read"}, "marked read but asks to change --path"),
                             ({"hosts": ["https://example.org/"]}, "hosts is a list of host names")):
            found = self.staged({**DELETE, **change})
            self.assertIsNone(found.command, change)
            self.assertIn(said, found.fault)
            self.assertEqual(found.failures(), [found.fault])

    def test_checks_run_in_the_sandbox_and_say_what_went_wrong(self):
        command = self.staged(DELETE).command
        self.assertEqual([teach.check(command, wanted, True) for wanted in DELETE["checks"]],
                         [("fs.delete --path old.txt", ""), ("fs.delete --path missing.txt", ""), ("fs.delete", ""),
                          ("fs.delete --path folder", "")])
        wrong = {"args": args(path="old.txt"), "files": [{"path": "old.txt", "content": "x"}], "contains": []}
        for change, said in (({"expect": "error"}, "should have given an error and said: Deleted"),
                             ({"expect": "output", "contains": ["Removed"]}, "should have said 'Removed' and said: Deleted"),
                             ({"expect": "output", "then": [{"path": "old.txt", "state": "present"}]},
                              "should have left old.txt present, and it is not."),
                             ({"expect": "output", "files": []}, "should have worked and gave an error: "),
                             ({"expect": "output", "args": args(path="../old.txt")}, "was not run: a path in it leaves"),
                             ({"expect": "output", "args": args(path="/etc/hostname")}, "was not run: a path in it leaves"),
                             ({"expect": "output", "files": [{"path": "~/x", "content": ""}]}, "was not run: a path in it"),
                             ({"expect": "output", "args": args(file="old.txt")}, "names a parameter the command does not")):
            self.assertIn(said, teach.check(command, {**wrong, **change}, True)[1], change)
        self.assertEqual(list((state.directory() / "scratch").glob("*/work")), [])      # nothing is left behind

    def test_a_check_sees_what_a_command_created_and_what_it_left_alone(self):
        command = self.staged(COPY).command
        self.assertEqual([problem for _, problem in (teach.check(command, wanted, True) for wanted in COPY["checks"])], ["", ""])
        differs = copy.deepcopy(COPY["checks"][0])
        differs["then"][0]["content"] = "a: 2\n"
        self.assertIn("should have left config.yaml.bak holding 'a: 2\\n'", teach.check(command, differs, True)[1])
        broken = self.staged({**COPY, "verb": "clone", "code": COPY["code"].replace("do_copy", "do_clone")
                              .replace("shutil.copy2(source, dest)", "shutil.copy2(source, dest + '.tmp')")}).command
        self.assertIn("should have left config.yaml.bak present", teach.check(broken, COPY["checks"][0], True)[1])

    def test_a_check_that_needs_the_network_runs_only_when_allowed(self):
        command = self.staged(WEATHER).command
        with mock.patch.object(urllib.request.OpenerDirector, "open") as opened:
            self.assertEqual([problem for _, problem in (teach.check(command, wanted, False) for wanted in WEATHER["checks"])],
                             ["", "was not run: it needs the network."])
        opened.assert_not_called()

    def test_a_proposal_may_ask_for_judgements_and_put_questions_to_a_model(self):
        found = self.staged(CHAT)
        self.assertEqual((found.fault, found.command.asks, found.command.judges), ("", ("student", "teacher"), ("tone",)))
        self.assertIn('judges = ["tone"]\nasks = ["student", "teacher"]\n', (found.folder / "plugin.toml").read_text())
        self.assertEqual(found.command.ranges, {"tone": (0, 10.5)})
        careless = self.staged({**CHAT, "verb": "tell", "code": CHAT["code"].replace("do_ask", "do_tell"),
                                "ranges": [{"name": "tone", "low": "low", "high": "10"}]})
        self.assertIn("the lowest and the highest number its value can hold", careless.fault)
        self.assertIn("ask(to, message), from los, returns the answer as text.", teach.BRIEF)
        self.assertIn("judge(name, question, value, choices), from los, returns the one of choices", teach.BRIEF)

    def test_a_check_reaches_the_student_and_never_the_teacher_and_leaves_no_record(self):
        command, student = self.staged(CHAT).command, Scripted({"answer": "A lock."}, {"answer": "curt"})
        self.teacher.outputs = [{"answer": "never asked"}]
        minds = judge.Minds(student, self.teacher, lambda question, default: True).trial()
        self.assertEqual([teach.check(command, wanted, True, minds) for wanted in CHAT["checks"]],
                         [("chat.ask", ""), ("chat.ask --to student --message 'what is a mutex'", ""),
                          ("chat.ask --to teacher --message 'what is a mutex'", "was not run: it would call the teacher."),
                          ("chat.ask --to tone --message 'Do it now.'", "")])
        self.assertEqual((self.teacher.calls, student.calls, cases.judgements(), state.read("asks")), (0, 2, [], []))
        self.assertIn("no model can be asked here", teach.check(command, CHAT["checks"][1], True)[1])

    def test_each_description_is_tried_on_the_student_and_the_best_comes_first(self):
        command = self.staged(DELETE).command
        student = Scripted(call("fs.delete", path="old-report.txt"), NONE, call("fs.delete", path="a.txt"), NONE,
                           call("fs.delete", path="old-report.txt"), call("fs.delete", path="draft.md"),
                           call("fs.move", source="a.txt", dest="b.txt"), call("fs.delete"))
        tried = teach.try_descriptions(student, self.table, command, DELETE)
        self.assertEqual([(description, right, total) for description, right, total, *_ in tried],
                         [("Remove (erase) a single named file; not for folders", 3, 4), ("Delete one file for good", 2, 4)])
        self.assertEqual(tried[1][4], [("delete old-report.txt", "fs.delete"), ("get rid of draft.md", None)])  # its own lines
        self.assertEqual(tried[0][3], ['The line "empty the bin" should reach no command, and the student sent it to fs.delete.'])
        self.assertEqual(tried[1][3][0], 'The line "get rid of draft.md" should reach fs.delete, and the student sent it '
                                         'to no command.')
        self.assertIn("fs.delete | Remove (erase) a single named file; not for folders | path (the file to delete",
                      student.system)
        self.assertEqual(student.calls, 8)

    def test_the_user_is_shown_what_it_does_what_it_may_touch_how_it_fared_and_the_code(self):
        found = self.staged(DELETE)
        found.checks = [("fs.delete --path old.txt", ""), ("fs.delete", "should have given an error and said: Deleted")]
        found.tried = [("Delete one file for good", 3, 4, ["The line \"empty the bin\" should reach no command, and "
                                                           "the student sent it to fs.delete."]),
                       ("Another", 2, 4, [])]
        advice = teach.Advice("write", "Nothing deletes files yet.", write(DELETE))
        self.assertEqual(teach.show(found, advice), "\n".join([
            "fs.delete  Delete one file for good  (effect: destructive)",
            "  --path  the file to delete, such as old-report.txt",
            "Why: Nothing deletes files yet.", "",
            "It may change, move or remove what you give as --path.",
            "It sees no other file of yours and has no network.", "",
            "Checks: 1 of 2 passed.",
            "  - fs.delete should have given an error and said: Deleted",
            "Lines: with this description the student sent 3 of 4 where they belong. The other descriptions got 2 of 4.",
            '  - The line "empty the bin" should reach no command, and the student sent it to fs.delete.', "",
            DELETE["code"].rstrip(), ""]))
        self.assertEqual(found.failures(), ["The check fs.delete should have given an error and said: Deleted",
                                            'The line "empty the bin" should reach no command, and the student sent it '
                                            'to fs.delete.'])


@needs_sandbox
class DelegateTest(Case):
    def shell(self, *teacher_says, student_says=(), answers=()):
        self.shown, self.asked = [], []
        self.teacher.outputs, self.student = list(teacher_says), Scripted(*student_says)
        replies = list(answers)

        def ask(question):
            self.asked.append(question)
            if not replies:
                raise EOFError
            return replies.pop(0)

        return Shell(self.table, ask, self.shown.append, sandbox.run, self.student, self.teacher, self.plugin_dir)

    def test_a_command_that_exists_is_shown_and_agreeing_settles_the_words(self):
        (self.files / "a.txt").write_text("a")
        shell = self.shell({"answer": "run", "reason": "fs.list shows a folder.", "command": "fs.list",
                            "args": args(path=str(self.files))}, answers=[""])
        shell.handle("delegate what do I have in my files folder")
        self.assertEqual(self.shown[:2], ["Asking scripted-teacher about: what do I have in my files folder",
                                          f"fs.list shows a folder.\n→ fs.list --path {self.files}"])
        self.assertTrue(self.shown[2].endswith("a.txt"))
        self.assertEqual(self.asked, ["Run it? [Y/n] "])
        case, = state.read("cases")
        self.assertEqual((case["by"], case["verdict"], case["model"]), ("teacher", "accepted", "scripted-teacher"))
        shell.handle("what do I have in my files folder")       # the same words, typed plainly: no model at all
        self.assertEqual((self.teacher.calls, self.student.calls), (1, 0))
        self.assertIn("(remembered)", self.shown[-2])
        shell.handle("stats")
        self.assertIn("Calls to the teacher: 1\n", self.shown[-1])

    def test_a_queued_need_can_be_sent_by_its_number_and_leaves_the_queue_when_answered(self):
        shell = self.shell({"answer": "cannot", "reason": "It needs an account with a pizza place."},
                           {"answer": "run", "reason": "r", "command": "note.list", "args": []},
                           student_says=[NONE, NONE], answers=[""])
        shell.handle("order a large pizza")
        self.assertIn("delegate 1 asks scripted-teacher about it, and forget 1 drops it.", self.shown[-1])
        shell.handle("show what I wrote down")
        shell.handle("delegate 1")
        self.assertEqual(self.shown[-2:], ["Asking scripted-teacher about: order a large pizza",
                                           "lo-s cannot do this: It needs an account with a pizza place.\n"
                                           "Need 1 stays queued; forget 1 drops it."])
        shell.handle("needs")                                   # asking again would cost a call, so it says so
        self.assertRegex(self.shown[-1], r"^1\. order a large pizza  \([\d-]+; the teacher said lo-s cannot do it\)\n"
                                         r"2\. show what I wrote down  \([\d-]+\)$")
        shell.handle("delegate 2")
        self.assertIn("That answers need 2, so it left the queue.", self.shown)
        self.assertEqual(sorted(cases.waiting()), [1])
        for wrong_use in ("delegate 7", "delegate"):
            shell.handle(wrong_use)
            self.assertTrue(self.shown[-1].startswith("Usage: delegate "))
        self.assertEqual(self.teacher.calls, 2)

    def test_its_question_is_put_to_the_user_and_the_answer_goes_back(self):
        shell = self.shell({"answer": "ask", "reason": "A forecast is for a place.", "question": "Which town?"},
                           {"answer": "ask", "reason": "r", "question": "Which country is that in?"}, answers=["Lyon", ""])
        shell.handle("delegate what's the weather tomorrow")
        self.assertEqual(self.shown, ["Asking scripted-teacher about: what's the weather tomorrow",
                                      "A forecast is for a place.\nscripted-teacher asks: Which town?",
                                      "Asking scripted-teacher again about: what's the weather tomorrow",
                                      "r\nscripted-teacher asks: Which country is that in?", "Left there. Nothing was sent."])
        self.assertEqual(self.teacher.user, "What the user wants: what's the weather tomorrow\n\n"
                                            "You asked: Which town?\nThe user answered: Lyon")
        self.assertEqual((self.teacher.calls, len(state.read("delegations"))), (2, 2))

    def test_a_written_command_is_tried_shown_and_installed_only_if_the_user_agrees(self):
        tried = [call("fs.delete", path="old-report.txt"), call("fs.delete", path="draft.md"), NONE, NONE,     # first description
                 call("fs.delete", path="old-report.txt"), call("fs.delete", path="draft.md"),
                 call("fs.move", source="a.txt", dest="b.txt"), NONE]                                           # second: all four
        shell = self.shell(write(DELETE), student_says=tried, answers=["n"])
        shell.handle("delegate I want to be able to delete files")
        self.assertEqual(self.shown[1:3], ["Running 4 checks of fs.delete in the sandbox.",
                                           "Trying 2 descriptions of it on scripted."])
        self.assertIn("fs.delete  Remove (erase) a single named file; not for folders  (effect: destructive)", self.shown[3])
        self.assertIn("Checks: 4 of 4 passed.\nLines: with this description the student sent 4 of 4 where they belong. "
                      "The other descriptions got 3 of 4.", self.shown[3])
        self.assertEqual(self.asked, ["Install fs.delete? [y/N] "])
        self.assertEqual(self.shown[4], "Not installed. What it wrote is kept in the state folder, in delegations.jsonl.")
        self.assertEqual(state.read("delegations")[0]["answer"]["write"]["code"], DELETE["code"])
        self.assertEqual((sorted(path.name for path in self.plugin_dir.iterdir()), list((state.directory() / "scratch").iterdir())),
                         (["fs", "note", "sys"], []))

        shell = self.shell(write(DELETE), student_says=tried, answers=["y", "y"])
        target = self.files / "old.txt"
        target.write_text("old")
        shell.handle("delegate I want to be able to delete files")
        self.assertEqual(self.shown[4], f"Installed fs.delete in {self.plugin_dir}/fs.delete. Delete that folder to remove it.")
        manifest = (self.plugin_dir / "fs.delete" / "plugin.toml").read_text()
        self.assertIn('description = "Remove (erase) a single named file; not for folders"', manifest)
        self.assertIn('[origin]\nwords = "I want to be able to delete files"\nwritten_by = "scripted-teacher"', manifest)
        self.assertTrue((self.plugin_dir / "fs.delete" / "proposal.json").exists())
        self.assertEqual([(row["command"], row["line"], row["reached"]) for row in state.read("line_checks")],
                         [("fs.delete", "delete old-report.txt", "fs.delete"), ("fs.delete", "get rid of draft.md", "fs.delete")])
        self.assertEqual(state.read("line_checks")[0]["at"], state.read("line_checks")[1]["at"])    # one check, to compare with later
        shell.handle(f"fs.delete --path {target}")        # it is a command like any other now, and asks before it runs
        self.assertEqual((self.asked[-1], self.shown[-1], target.exists()),
                         ("It makes changes that cannot be undone. Run it? [y/N] ", f"Deleted {target}", False))
        shell.handle("help fs.delete")
        self.assertIn("It may change, move or remove what you give as --path.", self.shown[-1])

    def test_words_that_were_a_request_are_carried_out_once_the_command_exists(self):
        (self.files / "config.yaml").write_text("a: 1\n")
        self.addCleanup(os.chdir, os.getcwd())
        os.chdir(self.files)
        shell = self.shell(write(COPY), student_says=[NONE, call("fs.copy", source="config.yaml"), NONE,
                                                      call("fs.copy", source="config.yaml")], answers=["y", "y", "y"])
        shell.handle("make a backup copy of config.yaml")       # nothing fits: need 1
        shell.handle("delegate 1")
        self.assertIn("Lines: with this description the student sent 1 of 2 where they belong.", "\n".join(self.shown))
        said = self.shown[self.shown.index("Now for what you asked: make a backup copy of config.yaml"):]
        self.assertEqual(said[1:], [f"→ fs.copy --source {self.files}/config.yaml --dest {self.files}/config.yaml.bak",
                                    f"Copied {self.files}/config.yaml to {self.files}/config.yaml.bak",
                                    "That answers need 1, so it left the queue."])
        self.assertEqual(((self.files / "config.yaml.bak").read_text(), cases.waiting()), ("a: 1\n", {}))
        shell.handle("make a backup copy of config.yaml")       # remembered now; the copy exists, so it refuses
        self.assertIn("already exists; nothing was copied", self.shown[-1])
        self.assertEqual(self.student.calls, 4)

    def test_what_went_wrong_can_go_back_to_the_teacher_for_one_more_call(self):
        faulty = {**DELETE, "code": DELETE["code"].replace("remove(path)", "os.remove(path)")}
        unreadable = {**DELETE, "code": "def do_delete(path=None)\n"}
        shell = self.shell(write(unreadable), write(faulty), write(DELETE, "Now it asks the core to remove the file."),
                           answers=["y", "n", "y", "y"])
        shell.student = None
        shell.handle("delegate I want to be able to delete files")
        self.assertIn("Its command, fs.delete, cannot be installed. It cannot be read as a plugin", self.shown[1])
        self.assertEqual(self.asked[0], "Not installed. Have scripted-teacher put right what went wrong? That is one "
                                        "more call to it. [y/N] ")
        self.assertIn("Checks: 3 of 4 passed.\n  - fs.delete --path old.txt should have worked and gave an error: "
                      "Read-only file system", self.shown[4])
        self.assertIn("Lines: not tried on the student. No model is set up as the student.", self.shown[4])
        self.assertEqual(self.asked[1:3], ["Install fs.delete? [y/N] ", self.asked[0]])
        self.assertIn("this is what went wrong:\n- The check fs.delete --path old.txt should have worked", self.teacher.user)
        self.assertIn('os.remove(path)', self.teacher.user)
        self.assertIn("Checks: 4 of 4 passed.", self.shown[7])
        self.assertTrue(self.shown[8].startswith("Installed fs.delete in "))
        self.assertEqual((self.teacher.calls, len(state.read("delegations"))), (3, 3))

    def test_checks_use_the_network_only_if_the_user_lets_them(self):
        shell = self.shell(write(WEATHER), student_says=[call("weather.forecast", place="Lyon"),
                                                         call("sys.status", what="temperature")], answers=["n", "n"])
        with mock.patch.object(urllib.request.OpenerDirector, "open") as opened:
            shell.handle("delegate what's the weather tomorrow")
        opened.assert_not_called()
        self.assertEqual(self.asked, ["Its checks would fetch from api.example.org. Let them? [y/N] ",
                                      "Install weather.forecast? [y/N] "])
        proposal = self.shown[3]
        self.assertIn("It may fetch pages from api.example.org.\nIt sees no other file of yours and reaches nothing "
                      "else on the network.", proposal)
        self.assertIn("Checks: 1 of 2 passed.\n  - weather.forecast --place Lyon was not run: it needs the network.", proposal)
        self.assertEqual(self.shown[4], "Not installed. What it wrote is kept in the state folder, in delegations.jsonl.")

    def test_a_remembered_line_stays_where_it_is_unless_the_user_moves_it(self):
        for line, command in (("is the laptop running hot", "sys.status"), ("what's the weather like in my notes", "note.list")):
            cases.record("line", line, {"command": command, "args": {}}, "student", "accepted")
        tried = [call("weather.forecast", place="Lyon"), call("sys.status")]
        moved = [call("weather.forecast", place="my notes"), call("weather.forecast", place="the laptop")]
        shell = self.shell(write(WEATHER), student_says=tried + moved, answers=["n", "y", "y", "n"])
        shell.handle("delegate tell me the weather")
        self.assertEqual(self.asked[2:], ["Remember it that way from now on? [y/N] "] * 2)
        self.assertEqual(self.shown[5:9], [
            '"what\'s the weather like in my notes" is remembered as note.list. With weather.forecast installed, the '
            'student would send it to:\n→ weather.forecast --place \'my notes\'', "Moved.",
            '"is the laptop running hot" is remembered as sys.status. With weather.forecast installed, the student '
            'would send it to:\n→ weather.forecast --place \'the laptop\'', "Left as it was."])
        settled = cases.settled(shell.table)
        self.assertEqual((settled["is the laptop running hot"]["answer"]["command"],
                          settled["what's the weather like in my notes"]["answer"]),
                         ("sys.status", {"command": "weather.forecast", "args": {"place": "my notes"}}))

    def test_a_teacher_that_does_not_answer_leaves_the_words_queued(self):
        shell = self.shell(ModelUnavailable("the claude program is not installed"), answers=[""])
        shell.handle("delegate convert report.docx to pdf")
        self.assertEqual(self.shown[1:], ["No answer came back that could be used: the claude program is not installed",
                                          "Queued as need 1. delegate 1 asks again."])
        self.assertEqual((cases.waiting()[1]["line"], state.read("delegations")[0]["failed"]),
                         ("convert report.docx to pdf", "the claude program is not installed"))
        shell.handle("stats")
        self.assertIn("Calls to the teacher: 1, of which 1 gave no answer\n", self.shown[-1])
        shell.teacher = None
        shell.handle("delegate 1")
        self.assertEqual(self.shown[-1], "No model is set up as the teacher. Give the teacher role a provider in los.toml.")
