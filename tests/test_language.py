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
        shell = self.shell(NONE, NONE, NONE, NONE)
        shell.handle("order a large pizza")
        shell.handle("book a flight")
        self.assertEqual(self.shown[-1], "Nothing here does that yet. It is queued as need 2. needs lists the queue, "
                                         "and forget 2 drops it.")
        self.assertEqual((self.ran.calls, self.asked), ([], []))
        shell.handle("book a flight")                           # asked again: it keeps its one place in the queue
        self.assertEqual(self.shown[-1], "Nothing here does that yet. It is already queued as need 2. needs lists the "
                                         "queue, and forget 2 drops it.")
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

    def test_a_command_to_correct_is_offered_as_the_model_gave_it(self):
        # What the user leaves is what gets remembered, so the folder they happen to be in is not written into it.
        shell = self.shell(call("fs.usage", path="docs"), answers=["e"], edits=["fs.usage --path docs --depth 2"],
                           commands=self.real)
        shell.handle("how big is docs")
        self.assertEqual((self.shown[0], self.offered), (f"→ fs.usage --path {self.files}/docs",
                                                         [("Correct it: ", "fs.usage --path docs")]))
        self.assertEqual(state.read("cases")[-1]["answer"], {"command": "fs.usage", "args": {"path": "docs", "depth": "2"}})

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


class CorrectTest(ShellCase):
    """At a terminal, the command a model chose can be corrected on the line in place of a yes or no."""

    def test_the_command_is_put_on_the_line_and_what_the_user_leaves_is_remembered(self):
        shell = self.shell(call("fs.list", path="home"), answers=["e"], edits=["fs.list --path ~ --sort-by size"])
        shell.handle("what is in my home folder")
        self.assertEqual(self.asked, ["Run it? [Y/n/edit] "])
        self.assertEqual((self.shown[0], self.offered), ("→ fs.list --path home", [("Correct it: ", "fs.list --path home")]))
        self.assertEqual(self.shown[1:], ['Remembered: "what is in my home folder" means fs.list --path ~ --sort-by size.',
                                          "ran fs.list"])
        self.assertEqual(self.ran.calls, [("fs.list", {"path": "~", "sort_by": "size"})])
        self.assertEqual(recorded(), [("what is in my home folder", "fs.list", "student", "declined"),
                                      ("what is in my home folder", "fs.list", "user", "accepted")])
        shell.handle("what is in my home folder")
        self.assertEqual((self.student.calls, self.shown[-2]), (1, "→ fs.list --path ~ --sort-by size  (remembered)"))

    def test_a_command_left_as_it_was_counts_as_a_yes(self):
        shell = self.shell(call("fs.list", path="docs", sort_by="size"), answers=["edit"],
                           edits=["fs.list  --sort-by size --path docs "])
        shell.handle("what is in docs")
        self.assertEqual((self.ran.calls, self.shown[1:]), ([("fs.list", {"path": "docs", "sort_by": "size"})], ["ran fs.list"]))
        self.assertEqual(recorded(), [("what is in docs", "fs.list", "student", "accepted")])

    def test_what_is_left_must_be_a_command(self):
        for left, said in ((["the pizza place"], "That is not one of the commands help lists."),
                           ([""], "That is not one of the commands help lists."),
                           (["fs.list --colour red"], "fs.list has no parameter --colour\n"
                                                      "Usage: fs.list [--path VALUE] [--sort-by VALUE]"),
                           ([], "→ fs.list")):          # the line was closed without an answer
            shell = self.shell(call("fs.list"), answers=["e"], edits=left)
            shell.handle("list it")
            self.assertEqual(self.shown[-2], said)
            self.assertTrue(self.shown[-1].startswith("Not run."))
            self.assertEqual((self.ran.calls, recorded()[-1][2:]), ([], ("student", "declined")))

    def test_a_corrected_command_that_changes_something_still_asks(self):
        shell = self.shell(call("note.add", text="a to b"), answers=["e", "y"], edits=["fs.move --source a --dest b"])
        shell.handle("rename a to b")
        self.assertEqual(self.asked, ["Run it? [y/N/edit] ", "It makes changes that cannot be undone. Run it? [y/N] "])
        self.assertEqual(self.ran.calls, [("fs.move", {"source": "a", "dest": "b"})])

    def test_a_remembered_command_can_be_corrected_too(self):
        shell = self.shell(call("note.add", text="milk"), answers=["y", "e"], edits=["note.add --text 'oat milk'"])
        shell.handle("jot down milk")
        shell.handle("jot down milk")
        self.assertEqual(self.shown[-3:], ["→ note.add --text milk  (remembered)",
                                           'Remembered: "jot down milk" means note.add --text \'oat milk\'.', "ran note.add"])
        self.assertEqual([case[2:] for case in recorded()], [("student", "accepted"), ("memory", "declined"), ("user", "accepted")])

    def test_where_no_line_can_be_edited_it_is_not_offered(self):
        shell = self.shell(call("fs.list"), answers=["e", ""])
        shell.handle("list it")
        self.assertEqual(self.asked, ["Run it? [Y/n] "] * 2)
        self.assertEqual((self.shown[1], self.ran.calls), ("Answer y or n.", [("fs.list", {})]))

    def test_an_answer_that_is_none_of_them_says_what_the_answers_are(self):
        shell = self.shell(call("fs.list"), answers=["list the other one", "n"], edits=[])
        shell.handle("list it")
        self.assertEqual(self.shown[1], "Answer y or n, or e to correct the command first.")
        self.assertEqual((self.ran.calls, self.offered), ([], []))


HOME = "what is in my home folder"


class CorrectionAgainTest(ShellCase):
    """What the user put in place of the student's answer for one line is shown when the student
    gives that very answer for another."""

    def corrected(self, *student_says, answers=()):
        """A shell in which the user has said once that fs.list --path home should be --path ~."""
        shell = self.shell(call("fs.list", path="home"), *student_says, answers=["n", *answers])
        shell.handle(HOME)
        shell.handle("means fs.list --path ~")
        return shell

    def test_the_users_correction_is_shown_in_place_of_the_answer_they_corrected(self):
        shell = self.corrected(call("fs.list", path="home"), answers=[""])
        shell.handle("show me my home folder")
        self.assertEqual(self.shown[-3:], [f'The student gave fs.list --path home. You corrected that for "{HOME}".',
                                           "→ fs.list --path ~  (your correction)", "ran fs.list"])
        self.assertEqual((self.asked[-1], self.ran.calls[-1]), ("Run it? [Y/n] ", ("fs.list", {"path": "~"})))
        self.assertEqual(recorded()[-2:], [("show me my home folder", "fs.list", "student", "declined"),
                                           ("show me my home folder", "fs.list", "correction", "accepted")])
        said, shown = state.read("cases")[-2:]          # what the student said is kept as it was
        self.assertEqual((said["answer"]["args"], said["seconds"]), ({"path": "home"}, 1.5))
        self.assertEqual((shown["answer"]["args"], shown["from"]), ({"path": "~"}, HOME))
        shell.handle("show me my home folder")          # settled now, so the student is not asked again
        self.assertEqual((self.student.calls, self.shown[-2]), (2, "→ fs.list --path ~  (remembered)"))

    def test_a_correction_made_on_the_line_counts_and_another_answer_is_left_as_it_is(self):
        shell = self.shell(call("fs.list", path="home"), call("fs.list", path="home"), call("fs.list", path="house"),
                           answers=["e", "n", "n"], edits=["fs.list --path ~"])
        shell.handle(HOME)
        shell.handle("show me my home folder")
        self.assertEqual((self.shown[-2], self.asked[-1]), ("→ fs.list --path ~  (your correction)", "Run it? [Y/n/edit] "))
        shell.handle("what is in my house folder")
        self.assertEqual((self.shown[-2], recorded()[-1][2:]), ("→ fs.list --path house", ("student", "declined")))

    def test_an_answer_that_was_right_as_it_stands_for_a_line_is_shown_as_the_student_gave_it(self):
        shell = self.shell(*[call("fs.list", path="home")] * 3, answers=["", "n", "n"])
        shell.handle("what is in the folder called home")       # here home is a folder's name, and the user agrees
        shell.handle(HOME)
        shell.handle("means fs.list --path ~")
        shell.handle("show me my home folder")                  # so the answer may be right, and nothing is put in its place
        self.assertEqual((self.shown[-2], recorded()[-1][2:]), ("→ fs.list --path home", ("student", "declined")))

    def test_putting_the_students_answer_back_says_it_was_right_as_it_stands(self):
        shell = self.shell(*[call("fs.list", path="home")] * 3, answers=["e", "e", "n"],
                           edits=["fs.list --path ~", "fs.list --path home"])
        shell.handle(HOME)
        shell.handle("what is in the folder called home")       # the correction is shown, and it is wrong here
        self.assertEqual(self.offered[-1], ("Correct it: ", "fs.list --path ~"))
        self.assertEqual(self.shown[-2], 'Remembered: "what is in the folder called home" means fs.list --path home.')
        shell.handle("show me my home folder")
        self.assertEqual(self.shown[-2], "→ fs.list --path home")

    def test_a_correction_taken_back_is_not_shown_again(self):
        shell = self.corrected(*[call("fs.list", path="home")] * 3, answers=["", "n", "n", "n", "n"])
        shell.handle("show me my home folder")                  # the correction is shown, and Enter runs it
        shell.handle("wrong")                                   # which was wrong for this line
        shell.handle("show me my home folder")
        self.assertEqual(self.shown[-2], "→ fs.list --path home")
        shell.handle(HOME)                                      # remembered, so it is the latest choice
        shell.handle("wrong")                                   # and with it goes the correction itself
        shell.handle("what do I keep in my home folder")
        self.assertEqual(self.shown[-2], "→ fs.list --path home")

    def test_of_two_corrections_of_one_answer_the_one_for_the_line_most_alike_is_shown(self):
        shell = self.corrected(*[call("fs.list", path="home")] * 3, answers=["n", "n", "n"])
        shell.handle("what are the biggest things at home")
        shell.handle("means fs.list --path ~ --sort-by size")
        shell.handle("biggest things at my home")
        self.assertEqual(self.shown[-3:-1], ['The student gave fs.list --path home. You corrected that for '
                                             '"what are the biggest things at home".',
                                             "→ fs.list --path ~ --sort-by size  (your correction)"])
        shell.handle("what do I keep in my home folder")
        self.assertEqual(self.shown[-2], "→ fs.list --path ~  (your correction)")

    def test_a_correction_gets_the_care_any_choice_gets(self):
        shell = self.shell(*[call("note.add", text="milk")] * 3, answers=["n", "", "e"], edits=["note.add --text 'soy milk'"])
        shell.handle("jot down milk")
        shell.handle("means note.add --text 'oat milk'")
        shell.handle("note down milk please")                   # it adds something, so Enter does not run it
        self.assertEqual((self.asked[-1], self.shown[-2]),
                         ("Run it? [y/N/edit] ", "→ note.add --text 'oat milk'  (your correction)"))
        self.assertTrue(self.shown[-1].startswith("Not run."))
        self.assertEqual(recorded()[-2:], [("note down milk please", "note.add", "student", "declined"),
                                           ("note down milk please", "note.add", "correction", "declined")])
        shell.handle("note down milk please")                   # nothing was settled, and it can be corrected in turn
        self.assertEqual(self.offered, [("Correct it: ", "note.add --text 'oat milk'")])
        self.assertEqual(self.shown[-2:], ['Remembered: "note down milk please" means note.add --text \'soy milk\'.',
                                           "ran note.add"])

    def test_stats_count_what_was_offered_from_another_line(self):
        shell = self.corrected(call("fs.list", path="home"), NONE, answers=["", ""])
        for line in ("show me my home folder", "whats in my home folder", "stats"):
            shell.handle(line)
        self.assertIn("Answered by the student: 3, taking 4.5 s (0 accepted, 2 declined, 1 where nothing fitted)\n"
                      "Offered from another line of yours: 2 (1 as your correction of the student's answer, 1 where it "
                      "found nothing; 1 accepted)\nSettled by you with means: 1\n", self.shown[-1])


class AlikeTest(ShellCase):
    """A line the student finds no command for is offered the command of the settled line most like it."""

    def settled(self, *student_says, answers=()):
        """A shell in which the user has accepted fs.list --path ~ for one line."""
        shell = self.shell(call("fs.list", path="~"), *student_says, answers=["", *answers])
        shell.handle(HOME)
        return shell

    def test_the_command_of_the_line_most_alike_is_offered_and_needs_a_clear_yes(self):
        shell = self.settled(NONE, answers=["y"])
        shell.handle("whats in my home folder")
        self.assertEqual(self.shown[-3:], [f'The student found no command for that. It is most like your line "{HOME}".',
                                           "→ fs.list --path ~  (what that line means)", "ran fs.list"])
        self.assertEqual(self.asked[-1], "Run it? [y/N] ")      # though it only reads
        self.assertEqual(recorded()[-2:], [("whats in my home folder", None, "student", ""),
                                           ("whats in my home folder", "fs.list", "likeness", "accepted")])
        self.assertEqual(state.read("cases")[-1]["from"], HOME)
        shell.handle("whats in my home folder")
        self.assertEqual((self.student.calls, self.shown[-2]), (2, "→ fs.list --path ~  (remembered)"))

    def test_saying_no_queues_the_line_as_before(self):
        shell = self.settled(NONE, answers=[""])
        shell.handle("whats in my home folder")
        self.assertEqual(self.shown[-1], "Nothing here does that yet. It is queued as need 1. needs lists the queue, "
                                         "and forget 1 drops it.")
        self.assertEqual((len(self.ran.calls), recorded()[-1][2:]), (1, ("likeness", "declined")))
        self.assertEqual([need["line"] for need in cases.waiting().values()], ["whats in my home folder"])

    def test_a_line_unlike_any_settled_is_queued_without_a_question(self):
        shell = self.settled(NONE)
        shell.handle("order a large pizza")
        self.assertEqual((len(self.asked), self.shown[-1][:28]), (1, "Nothing here does that yet. "))
        self.assertEqual(recorded()[-1], ("order a large pizza", None, "student", ""))

    def test_its_values_can_be_corrected_on_the_line(self):
        shell = self.shell(NONE, call("fs.list", path="~"), NONE, answers=["", "e"], edits=["fs.list --path ~/docs"])
        shell.handle("what is in my docs folder")               # nothing is settled yet, so it is need 1
        shell.handle(HOME)
        shell.handle("what is in my docs folder")
        self.assertEqual((self.asked[-1], self.offered), ("Run it? [y/N/edit] ", [("Correct it: ", "fs.list --path ~")]))
        self.assertEqual(self.shown[-3:], ['Remembered: "what is in my docs folder" means fs.list --path ~/docs.',
                                           "That answers need 1, so it left the queue.", "ran fs.list"])
        self.assertEqual(cases.waiting(), {})

    def test_a_need_that_gets_its_answer_leaves_the_queue(self):
        shell = self.shell(NONE, call("fs.list", path="~"), NONE, NONE, call("fs.list"), answers=["", "y", ""])
        for line in ("whats in my home folder", HOME, "whats in my home folder"):
            shell.handle(line)
        self.assertEqual(self.shown[-2:], ["ran fs.list", "That answers need 1, so it left the queue."])
        shell.handle("list it")                                 # the same holds when the student finds the command later
        shell.handle("list it")
        self.assertEqual(self.shown[-2:], ["ran fs.list", "That answers need 2, so it left the queue."])
        self.assertEqual(cases.waiting(), {})

    def test_an_offer_taken_back_is_not_made_again(self):
        shell = self.settled(NONE, NONE, answers=["y", "n"])
        shell.handle("whats in my home folder")
        shell.handle("wrong")
        shell.handle("whats in my home folder")
        self.assertEqual((len(self.asked), self.shown[-1][:28]), (3, "Nothing here does that yet. "))
