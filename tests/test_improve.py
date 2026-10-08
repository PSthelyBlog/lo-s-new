"""Looking for improvements: what each finder sees in the records, in what order, and the word
that lists it. Nothing here calls a model that is not scripted."""
import datetime
import json

from los import cases, improve, plugins, rules, state
from los.models import ModelUnavailable
from los.shell import Shell
from tests.helpers import NONE, Folders, Scripted, call, needs_sandbox, table

QUESTION, LEVELS = "Is this fine or worrying?", ["fine", "worrying"]
HEALTH = plugins.Command("sys.health", "Say whether the machine looks healthy", {}, judges=("temperature", "memory"),
                         ranges={"temperature": (20, 110)})
TABLE = {**table(("fs.list", ["path"], "read"), ("note.add", ["text"], "write")), "sys.health": HEALTH}
RUN = "2026-10-08T10:00:00.000000"
RULE = "def rule(value):\n    degrees = int(value.split()[0])\n    return None if 70 <= degrees < 85 else 'fine' if degrees < 70 else 'worrying'\n"


def judged(value, answer="fine", by="student", name="temperature", run=RUN, seconds=0.6):
    more = {"run": run, "seconds": seconds} if by == "student" and run else {}
    cases.record("judgement", {"command": "sys.health", "name": name, "ask": QUESTION, "choices": LEVELS, "value": value},
                 answer, by, "accepted" if by == "user" else "", **more)


def said(line, command, verdict="declined", by="student", **args):
    cases.record("line", line, {"command": command, "args": args}, by, verdict, **({"seconds": 1.0} if by == "student" else {}))


class JudgementsTest(Folders):
    def test_a_judgement_the_student_keeps_being_asked_is_worth_a_rule(self):
        for value in ("50 °C", "55 °C"):
            judged(value)
            judged(value, name="memory")
        self.assertEqual(improve.judgements(TABLE), [])                 # twice is not often
        judged("60 °C")
        judged("60 °C", name="memory")
        found, = improve.judgements(TABLE)                              # memory has no range, so nothing can be typed for it
        self.assertEqual(found, improve.Found(
            "sys.health has asked the student about temperature 3 times, 1.8 s in all. A rule could answer in its place, "
            "but only 3 different values are on record for it, and a rule needs 6. rule sys.health temperature first puts "
            "values from across its range to the student, which is free.",
            "rule sys.health temperature", "one call to the teacher, after the free part", seconds=found.seconds))
        self.assertAlmostEqual(found.seconds, 1.8)
        for value, answer in (("30 °C", "fine"), ("70 °C", "fine"), ("90 °C", "worrying"), ("100 °C", "worrying")):
            judged(value, answer, run=None)                             # asked on purpose, in no run
        found, = improve.judgements(TABLE)
        self.assertEqual((found.text, found.cost), (
            "sys.health has asked the student about temperature 3 times, 1.8 s in all. 7 answers are on record, enough "
            "for a rule to answer in its place.", "one call to the teacher"))

    def test_one_ask_is_enough_when_a_rule_can_be_made_at_once(self):
        for value, answer in (("30 °C", "fine"), ("50 °C", "fine"), ("70 °C", "fine"), ("90 °C", "worrying"),
                              ("95 °C", "worrying"), ("100 °C", "worrying")):
            judged(value, answer, run=None)
        self.assertEqual(improve.judgements(TABLE), [])                 # nothing was asked in a run, so nothing to save
        judged("60 °C")
        self.assertIn("about temperature 1 time, 0.6 s in all. 7 answers are on record", improve.judgements(TABLE)[0].text)

    def test_a_rule_that_leaves_much_to_the_student_may_be_made_again(self):
        judged("50 °C")
        rules.install("sys.health", "temperature", QUESTION, LEVELS, RULE, Scripted(), 1)
        self.assertEqual(improve.judgements(TABLE), [])
        later = (datetime.datetime.now() + datetime.timedelta(seconds=5)).isoformat(timespec="microseconds")
        for value in ("72 °C", "76 °C", "81 °C"):
            judged(value, run=later)
        found, = improve.judgements(TABLE)
        self.assertEqual((found.text, found.do, found.times), (
            "The rule for temperature in sys.health has left it to the student 3 times since it was made, 1.8 s in all. "
            "4 answers are on record now, against 1 then, so a new rule may cover more.", "rule sys.health temperature", 0))

    @needs_sandbox
    def test_a_rule_the_user_overruled_comes_before_what_only_took_time(self):
        rules.install("sys.health", "temperature", QUESTION, LEVELS, RULE, Scripted(), 6)
        judged("60 °C", "worrying", by="user")      # the rule says fine
        judged("95 °C", "worrying", by="user")      # the rule agrees
        judged("75 °C", "worrying", by="user")      # the rule leaves it alone
        found, = improve.judgements(TABLE)
        self.assertEqual((found.times, found.seconds, found.do), (1, 0, "rule sys.health temperature"))
        self.assertTrue(found.text.startswith("You set 1 answer for temperature in sys.health that its rule gives otherwise."))


class LinesAndNeedsTest(Folders):
    def test_what_the_user_keeps_asking_for_and_nothing_does(self):
        for line in ("convert report.docx to pdf", "convert report.docx to pdf", "order a large pizza", "order a large pizza",
                     "play some jazz"):
            said(line, None, verdict="")
            cases.queue(line, "student")
        self.assertEqual(sorted(cases.waiting()), [1, 2, 3])            # a line already waiting keeps its one number
        state.append("delegations", {"words": "order a large pizza", "answer": {"answer": "cannot"}})
        found, = improve.needs(TABLE)                                   # once is not keeping on; cannot stays as it is
        self.assertEqual(found, improve.Found('You have asked 2 times for something nothing does: "convert report.docx '
                                              'to pdf".', "delegate 1", "one call to the teacher", 2, 2.0))

    def test_a_line_the_student_keeps_answering_in_a_way_the_user_does_not_take(self):
        said("how big is my home folder", "fs.list", path="home")
        self.assertEqual(improve.lines(TABLE), [])
        said("how big is my home folder", "fs.list", path="home")
        found, = improve.lines(TABLE)
        self.assertEqual(found, improve.Found(
            'The student has answered "how big is my home folder" 2 times and none of its answers stands. The last was '
            "fs.list --path home. If you know the command, say the line again and then: means COMMAND --parameter value. "
            "That is free.", "delegate how big is my home folder", "one call to the teacher", 2, 2.0))
        said("how big is my home folder", "fs.list", "accepted", by="user", path="~")       # settled with means
        self.assertEqual(improve.lines(TABLE), [])
        said("how big is my home folder", "fs.list", "wrong", by="user", path="~")          # and taken back
        self.assertEqual(len(improve.lines(TABLE)), 1)

    def test_lines_that_have_grown_slow(self):
        for seconds in (0.9, 3.0, 3.2, 3.4, 9.0):
            cases.record("line", "a line", {"command": "fs.list", "args": {}}, "student", "accepted", seconds=seconds)
        found, = improve.routing(TABLE)
        self.assertTrue(found.text.startswith("A plain-language line now takes the student 3.2 s (the middle one of the "
                                              "latest 5). It took about 1 s when measured, with up to 200 commands. The "
                                              "table holds 3."))
        self.assertEqual((found.do, round(found.seconds, 1)), ("", 11.0))
        for _ in range(4):
            cases.record("line", "a line", {"command": "fs.list", "args": {}}, "student", "accepted", seconds=1.0)
        self.assertEqual(improve.routing(TABLE), [])

    def test_what_cost_the_user_something_comes_first_then_the_most_model_time(self):
        for value in ("50 °C", "55 °C", "60 °C", "65 °C"):
            judged(value, seconds=2.0)
        for _ in range(2):
            said("how big is my home folder", "fs.list", path="home")
            said("convert report.docx to pdf", None, verdict="")
        said("convert report.docx to pdf", None, verdict="")
        cases.queue("convert report.docx to pdf", "student")
        self.assertEqual([(one.times, one.seconds, one.do) for one in improve.find(TABLE)],
                         [(3, 3.0, "delegate 1"), (2, 2.0, "delegate how big is my home folder"),
                          (0, 8.0, "rule sys.health temperature")])


class WordTest(Folders):
    def shell(self, *student_says, commands=TABLE):
        self.shown, self.student = [], Scripted(*student_says)
        return Shell(commands, lambda question: "", self.shown.append, student=self.student)

    def test_improve_lists_what_was_found_with_what_to_type(self):
        shell, hint = self.shell(), ("improve lines puts each written command's own example lines to the student again, "
                                     "to see whether they reach it. That is free.")
        shell.handle("improve")
        self.assertEqual(self.shown, ["Nothing stands out in what is on record so far.\n" + hint])
        for value in ("50 °C", "55 °C", "60 °C"):
            judged(value)
        for seconds in (3.0, 3.0, 3.0, 3.0, 3.0):
            cases.record("line", "a line", {"command": "fs.list", "args": {}}, "student", "accepted", seconds=seconds)
        shell.handle("improve")
        self.assertTrue(self.shown[1].startswith("1. A plain-language line now takes the student 3.0 s"))
        self.assertNotIn("\n", self.shown[1])                           # nothing to type for this one
        self.assertTrue(self.shown[2].startswith("2. sys.health has asked the student about temperature 3 times"))
        self.assertTrue(self.shown[2].endswith("\n   rule sys.health temperature   (one call to the teacher, after the free part)"))
        self.assertEqual(self.shown[3], hint)
        shell.handle("improve everything")
        self.assertEqual(self.shown[-1], "Usage: improve, or improve lines.")
        shell.handle("help improve")
        self.assertIn("What cost you something comes first", self.shown[-1])

    def written(self, name, lines):
        """A command a model wrote, with the example lines it came with."""
        plugin, verb = name.split(".")
        commands, _ = self.plugin(f'name = "{plugin}"\n[origin]\nwritten_by = "some-model"\n[commands.{verb}]\n'
                                  f'description = "Test command {name}"\n[commands.{verb}.params]\npath = "a path"\n',
                                  f"def do_{verb}(path=None):\n    return 'done'\n", folder=name)
        (self.root / "plugins" / name / "proposal.json").write_text(json.dumps({"lines": [{"line": line} for line in lines]}))
        return commands

    def test_improve_lines_asks_the_student_each_written_commands_own_lines_again(self):
        self.written("fs.copy", ["copy a.txt", "back up  a.txt", "duplicate a.txt"])
        commands = self.written("fs.delete", ["delete a.txt"])
        cases.record("line", "copy a.txt", {"command": "fs.copy", "args": {}}, "student", "accepted")   # memory answers this one
        shell = self.shell(call("fs.copy"), call("fs.delete"), call("fs.delete"), commands=commands)
        self.assertEqual(improve.written(commands), {"fs.copy": ["back up a.txt", "duplicate a.txt"], "fs.delete": ["delete a.txt"]})
        shell.handle("improve lines")
        self.assertEqual(self.shown, ["Asking scripted 3 example lines of 2 commands a model wrote.",
                                      'fs.copy: 1 line of 2 reaches it.\n  "duplicate a.txt" goes to fs.delete.',
                                      "fs.delete: 1 line of 1 reaches it."])
        self.assertEqual(improve.examples(commands), [])        # a first check shows no change, so there is nothing to raise

    def test_only_a_line_that_reached_its_command_before_and_no_longer_does_is_raised(self):
        commands = self.written("fs.copy", ["back up a.txt", "duplicate a.txt", "clone a.txt"])
        improve.note("fs.copy", [("back up a.txt", "fs.copy"), ("duplicate a.txt", None), ("clone a.txt", "fs.copy")])
        earlier = state.read("line_checks")[0]["date"]
        shell = self.shell(NONE, NONE, call("fs.copy"), commands=commands)
        shell.handle("improve lines")
        self.assertEqual(self.shown[1:], [
            f'fs.copy: 1 line of 3 reaches it.\n  "back up a.txt" reached it on {earlier} and now goes to no command.\n'
            f'  "duplicate a.txt" goes to no command, and did not reach it on {earlier} either.',
            "improve lists the lines that no longer reach their command, until the next check."])
        found, = improve.examples(commands)
        self.assertEqual(found.text, f'1 example line of fs.copy no longer reaches it, as of {earlier}: "back up a.txt" reached '
                                     f"it on {earlier} and now goes to no command. If one matters to you, say it and then: "
                                     "means fs.copy --parameter value.")
        shell.student.outputs = [call("fs.copy")] * 3
        shell.handle("improve lines")                               # all back where they belong
        self.assertEqual(self.shown[-2:], ["fs.copy: 3 lines of 3 reach it.", "Every line reaches its command."])
        self.assertEqual(improve.examples(commands), [])

    def test_improve_lines_says_when_there_is_nothing_or_nobody_to_ask(self):
        shell = self.shell()
        shell.handle("improve lines")
        self.assertEqual(self.shown[-1], "No command here came with example lines that are still the student's to answer.")
        commands = self.written("fs.copy", ["copy a.txt"])
        shell = self.shell(ModelUnavailable("no answer from the server"), commands=commands)
        shell.handle("improve lines")
        self.assertEqual(self.shown[-1], "The student did not answer: no answer from the server.")
        shell.student = None
        shell.handle("improve lines")
        self.assertEqual(self.shown[-1], "No model is set up as the student, which these lines are put to.")
        self.assertEqual(state.read("line_checks"), [])
