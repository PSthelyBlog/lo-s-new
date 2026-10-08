"""Plain language: what the student chooses, what the user says about it, and what is remembered."""
import os

from los import cases, plugins, state
from los.models import ModelUnavailable
from tests.helpers import NONE, TABLE, ShellCase, call, table


def recorded():
    return [(case["question"], case["answer"]["command"], case["by"], case["verdict"]) for case in state.read("cases")]


class StudentTest(ShellCase):
    def test_the_choice_is_shown_as_typed_and_enter_runs_a_command_that_only_reads(self):
        shell = self.shell(call("fs.list", path="~", sort_by="size"), answers=[""])
        shell.handle("what are the biggest things in my home folder")
        self.assertEqual(self.shown, ["→ fs.list --path ~ --sort-by size", "ran fs.list"])
        self.assertEqual(self.asked, ["Run it? [Y/n] "])
        self.assertEqual(self.ran.calls, [("fs.list", {"path": "~", "sort_by": "size"})])
        self.assertEqual(recorded(), [("what are the biggest things in my home folder", "fs.list", "student", "accepted")])
        self.assertEqual((state.read("cases")[0]["seconds"], state.read("cases")[0]["model"]), (1.5, "scripted"))

    def test_anything_that_changes_something_needs_an_explicit_yes(self):
        self.shell(call("note.add", text="milk"), answers=[""]).handle("jot down milk")
        self.assertEqual((self.ran.calls, self.asked), ([], ["Run it? [y/N] "]))
        self.assertEqual(self.shown[-1], "Not run. If that was the wrong command for what you typed, say wrong, "
                                         "or say the right one with means.")
        self.shell(call("fs.move", source="a", dest="b"), answers=["y"]).handle("rename a to b")
        self.assertEqual(self.asked, ["It makes changes that cannot be undone. Run it? [y/N] "])
        self.assertEqual(self.ran.calls, [("fs.move", {"source": "a", "dest": "b"})])
        self.assertEqual([verdict for *_, verdict in recorded()], ["declined", "accepted"])

    def test_nobody_to_ask_means_no(self):
        self.shell(call("fs.list")).handle("list it")       # the question hits end of input
        self.assertEqual((self.ran.calls, recorded()[0][3]), ([], "declined"))

    def test_a_line_nothing_fits_is_queued_and_keeps_its_number(self):
        shell = self.shell(NONE, NONE, NONE)
        shell.handle("order a large pizza")
        shell.handle("book a flight")
        self.assertEqual(self.shown[-1], "Nothing here does that yet. It is queued as need 2. needs lists the queue, "
                                         "and forget 2 drops it.")
        self.assertEqual((self.ran.calls, self.asked), ([], []))
        shell.handle("forget 1")
        self.assertEqual(self.shown[-1], "Forgotten: order a large pizza")
        shell.handle("needs")
        self.assertRegex(self.shown[-1], r"^2\. book a flight  \(\d{4}-\d\d-\d\d\)$")
        shell.handle("compress the archive folder")
        self.assertEqual(sorted(cases.waiting()), [2, 3])
        for wrong_use in ("forget", "forget 1", "forget two", "forget 9"):
            shell.handle(wrong_use)
            self.assertEqual(self.shown[-1], "Usage: forget NUMBER, where NUMBER is one of those listed by needs.")
        shell.handle("forget 2")
        shell.handle("forget 3")
        shell.handle("needs")
        self.assertEqual(self.shown[-1], "No needs are waiting.")

    def test_without_a_student_structured_commands_still_work(self):
        shell = self.shell(ModelUnavailable("no answer from http://127.0.0.1:8080/v1"))
        shell.handle("what is in this folder")
        self.assertIn("did not answer: no answer from", self.shown[0])
        shell.student = None
        shell.handle("what is in this folder")
        self.assertIn("no model is set up to read plain language", self.shown[1])
        self.assertEqual((self.ran.calls, state.read("cases"), cases.waiting()), ([], [], {}))
        shell.handle("fs.list")
        self.assertEqual(self.ran.calls, [("fs.list", {})])

    def test_an_answer_that_fits_no_command_is_not_used(self):
        shell = self.shell(*[call("fs.list", colour="red")] * 3)
        shell.handle("list it in red")
        self.assertIn("The student's answer could not be used", self.shown[0])
        self.assertEqual((self.student.calls, self.ran.calls, state.read("cases")), (3, [], []))


class MemoryTest(ShellCase):
    def test_an_accepted_line_is_answered_from_memory_and_reading_runs_at_once(self):
        shell = self.shell(call("fs.list", path="~"), answers=[""])
        shell.handle("what is in my home folder")
        shell.handle("what is in my home folder")
        self.assertEqual((self.student.calls, len(self.asked)), (1, 1))
        self.assertEqual(self.ran.calls, [("fs.list", {"path": "~"})] * 2)
        self.assertEqual(self.shown[-2], "→ fs.list --path ~  (remembered)")
        self.assertEqual([(by, verdict) for *_, by, verdict in recorded()], [("student", "accepted"), ("memory", "accepted")])

    def test_a_remembered_line_that_changes_something_still_asks(self):
        shell = self.shell(call("note.add", text="milk"), answers=["y", "y", ""])
        shell.handle("jot down milk")
        shell.handle("jot down milk")
        self.assertEqual((self.student.calls, len(self.ran.calls), self.asked[1]), (1, 2, "Run it? [y/N] "))
        shell.handle("jot down milk")                               # Enter: not run, and still remembered
        self.assertEqual((self.student.calls, len(self.ran.calls)), (1, 2))
        shell.handle("jot down milk")
        self.assertEqual(self.shown[-2], "→ note.add --text milk  (remembered)")

    def test_a_declined_line_is_not_remembered(self):
        shell = self.shell(call("note.add", text="milk"), call("note.add", text="milk"), answers=["", ""])
        shell.handle("jot down milk")
        shell.handle("jot down milk")
        self.assertEqual(self.student.calls, 2)

    def test_memory_does_not_depend_on_which_other_commands_exist(self):
        self.shell(call("fs.list", path="~"), answers=[""]).handle("what is in my home folder")
        bigger = {**TABLE, **table(("weather.forecast", ["place", "day"], "read"), ("fs.delete", ["path"], "destructive"))}
        smaller = {name: command for name, command in TABLE.items() if name != "fs.move"}
        for other in (bigger, smaller):
            self.shell(commands=other).handle("what is in my home folder")
            self.assertEqual((self.student.calls, self.ran.calls), (0, [("fs.list", {"path": "~"})]))
            self.assertIn("(remembered)", self.shown[0])

    def test_memory_ends_when_the_command_is_gone_or_has_lost_a_parameter(self):
        self.shell(call("fs.list", path="~"), answers=[""]).handle("what is in my home folder")
        gone = {name: command for name, command in TABLE.items() if name != "fs.list"}
        changed = {**TABLE, **table(("fs.list", ["folder"], "read"))}
        for other in (gone, changed):
            self.shell(NONE, commands=other).handle("what is in my home folder")
            self.assertEqual((self.student.calls, self.ran.calls), (1, []))

    def test_wrong_takes_the_latest_choice_back(self):
        shell = self.shell(call("fs.list"), call("fs.list"), answers=["", "", ""])
        shell.handle("wrong")
        self.assertEqual(self.shown[-1], "There is no plain-language choice to take back.")
        shell.handle("show the big files")
        shell.handle("wrong")
        self.assertEqual(self.shown[-1], 'Taken back: "show the big files" does not mean fs.list, and is not '
                                         'remembered that way.\nIf a command does fit, say which: means COMMAND '
                                         '--parameter value.')
        self.assertEqual(self.asked[-1], "Or queue it as a need for a new command? [y/N] ")
        self.assertEqual(cases.waiting(), {})
        shell.handle("show the big files")
        self.assertEqual(self.student.calls, 2)                     # asked again
        shell.handle("wrong")
        shell.handle("wrong")
        self.assertEqual(self.shown[-1], "There is no plain-language choice to take back.")

    def test_wrong_can_queue_the_line_as_a_need(self):
        shell = self.shell(call("fs.move", source="tmp", dest="tmp2"), answers=["n", "y"])
        shell.handle("delete the tmp directory")
        shell.handle("wrong")
        self.assertEqual(self.ran.calls, [])
        self.assertEqual([(need["line"], need["by"]) for need in cases.waiting().values()],
                         [("delete the tmp directory", "user")])
        self.assertEqual([verdict for *_, verdict in recorded()], ["declined", "wrong"])

    def test_accepting_again_after_wrong_is_remembered_again(self):
        shell = self.shell(call("fs.list"), call("note.add", text="x"), answers=["", "n", "y"])
        shell.handle("keep x")
        shell.handle("wrong")
        shell.handle("keep x")
        shell.handle("keep x")
        self.assertEqual((self.student.calls, self.shown[-2]), (2, "→ note.add --text x  (remembered)"))

    def test_an_answer_taken_back_is_doubted_when_the_student_gives_it_again(self):
        shell = self.shell(*[call("fs.list", path="home")] * 3, answers=["n", "", "", "y"])
        shell.handle("what is in my home folder")
        shell.handle("wrong")
        shell.handle("what is in my home folder")
        self.assertEqual(self.shown[-2:], ["→ fs.list --path home  (you said this was wrong)",
                                           "Not run. If a command does fit, say which: means COMMAND --parameter value."])
        self.assertEqual((self.asked[-1], self.ran.calls), ("Run it? [y/N] ", []))     # Enter no longer runs it
        shell.handle("what is in my home folder")                                      # yes still does, and settles it
        self.assertEqual(self.ran.calls, [("fs.list", {"path": "home"})])
        shell.handle("what is in my home folder")
        self.assertEqual((self.student.calls, self.shown[-2]), (3, "→ fs.list --path home  (remembered)"))

    def test_only_the_answer_taken_back_is_doubted(self):
        shell = self.shell(call("fs.list", path="home"), call("fs.list", path="~"), call("fs.list", path="home"),
                           answers=["n", "", "n", "n"])
        shell.handle("what is in my home folder")
        shell.handle("wrong")
        shell.handle("what is in my home folder")           # another value: not what was taken back
        self.assertEqual((self.shown[-2], self.asked[-1]), ("→ fs.list --path ~", "Run it? [Y/n] "))
        shell.handle("what do I keep at home")              # another line: nothing is known about it
        self.assertEqual((self.shown[-2], self.asked[-1]), ("→ fs.list --path home", "Run it? [Y/n] "))

    def test_stats_count_what_each_source_answered(self):
        shell = self.shell(call("fs.list"), NONE, call("note.add", text="x"), answers=["", "", "n"])
        for line in ("list it", "list it", "list it", "order a pizza", "keep x", "wrong"):
            shell.handle(line)
        shell.handle("stats")
        self.assertEqual(self.shown[-1], "Plain-language lines: 5\n"
                                         "Answered from memory: 2, saving about 3.0 s of model time\n"
                                         "Answered by the student: 3, taking 4.5 s "
                                         "(1 accepted, 1 declined, 1 where nothing fitted)\n"
                                         "Settled by you with means: 0\n"
                                         "Taken back with wrong: 1\n"
                                         "Calls to the teacher: 0\n"
                                         "Needs waiting: 1")

    def test_what_memory_saved_is_counted_at_the_usual_time_for_a_line(self):
        shell = self.shell(answers=["", "", ""])
        shell.student.complete = lambda *_: (call("fs.list", path=str(len(state.read("cases")))),
                                             {"seconds": 9.0 if not state.read("cases") else 1.0})
        for line in ("first after the table changed", "second", "third", "first after the table changed"):
            shell.handle(line)
        shell.handle("stats")
        self.assertIn("Answered from memory: 1, saving about 1.0 s of model time", self.shown[-1])

    def test_wrong_says_what_was_taken_back_in_full(self):
        shell = self.shell(call("fs.list", path="home"), answers=["n", ""])
        shell.handle("what is in my home folder")
        shell.handle("wrong")
        self.assertIn('does not mean fs.list --path home, and', self.shown[-1])


class FullFormTest(ShellCase):
    """What is shown before a question is the command as it will run."""

    def setUp(self):
        super().setUp()
        self.real, _ = plugins.load(state.ROOT / "plugins")
        self.addCleanup(os.chdir, os.getcwd())
        os.chdir(self.files)

    def test_a_path_left_out_or_relative_is_shown_in_full(self):
        shell = self.shell(call("fs.list"), call("fs.usage", path="docs"), call("fs.find", path="~/Music", name="*.mp3"),
                           answers=["n", "n", "n"], commands=self.real)
        for line in ("what is here", "how big is docs", "find my mp3s"):
            shell.handle(line)
        self.assertEqual(self.shown[0::2], [f"→ fs.list --path {self.files}", f"→ fs.usage --path {self.files}/docs",
                                            "→ fs.find --path ~/Music --name *.mp3"])

    def test_a_typed_destructive_command_is_shown_in_full_before_the_question(self):
        self.shell(answers=["n"], commands=self.real).handle("fs.move --source draft.txt --dest ~/final.txt")
        self.assertEqual(self.shown, [f"→ fs.move --source {self.files}/draft.txt --dest ~/final.txt", "Not run."])

    def test_what_is_remembered_is_what_was_said_not_where_it_pointed(self):
        shell = self.shell(call("fs.list", path="docs"), answers=[""], commands=self.real)
        shell.handle("what is in docs")
        self.assertEqual(state.read("cases")[0]["answer"], {"command": "fs.list", "args": {"path": "docs"}})
        (self.root / "elsewhere").mkdir()
        os.chdir(self.root / "elsewhere")
        shell.handle("what is in docs")
        self.assertEqual(self.shown[-2], f"→ fs.list --path {self.root}/elsewhere/docs  (remembered)")


class MeansTest(ShellCase):
    """The user says what a line means, and that settles it."""

    def test_the_user_can_say_what_a_line_means(self):
        shell = self.shell(call("fs.list", path="home"), answers=["n"])
        shell.handle("what is in my home folder")
        shell.handle("means fs.list --path ~ --sort-by size")
        self.assertEqual(self.shown[-2:], ['Remembered: "what is in my home folder" means fs.list --path ~ --sort-by size.',
                                           "ran fs.list"])
        self.assertEqual(self.ran.calls, [("fs.list", {"path": "~", "sort_by": "size"})])
        self.assertEqual(recorded()[-1], ("what is in my home folder", "fs.list", "user", "accepted"))
        shell.handle("what is in my home folder")
        self.assertEqual((self.student.calls, self.shown[-2]), (1, "→ fs.list --path ~ --sort-by size  (remembered)"))
        shell.handle("stats")
        self.assertIn("Settled by you with means: 1", self.shown[-1])

    def test_a_line_nothing_fitted_can_be_settled_and_leaves_the_queue(self):
        shell = self.shell(NONE, answers=["y"])
        shell.handle("put that somewhere else")
        shell.handle("means fs.move --source a --dest b")
        self.assertEqual(self.shown[-3], "That answers need 1, so it left the queue.")
        self.assertEqual(self.asked, ["It makes changes that cannot be undone. Run it? [y/N] "])
        self.assertEqual((cases.waiting(), self.ran.calls), ({}, [("fs.move", {"source": "a", "dest": "b"})]))

    def test_wrong_can_take_back_what_the_user_said_too(self):
        shell = self.shell(NONE, call("note.add", text="x"), answers=["", "n"])
        shell.handle("keep x")
        shell.handle("means fs.list")
        shell.handle("wrong")
        shell.handle("keep x")
        self.assertEqual(self.student.calls, 2)

    def test_means_needs_a_line_and_a_command(self):
        shell = self.shell(NONE)
        shell.handle("means fs.list")
        self.assertIn("There is no plain-language line to settle yet", self.shown[-1])
        shell.handle("order a pizza")
        for wrong_use, said in (("means", "Usage: means COMMAND"), ("means the pizza place", "Usage: means COMMAND"),
                                ("means fs.list --colour red", "fs.list has no parameter --colour\nUsage: means fs.list")):
            shell.handle(wrong_use)
            self.assertIn(said, self.shown[-1])
        self.assertEqual((self.ran.calls, len(state.read("cases"))), ([], 1))
