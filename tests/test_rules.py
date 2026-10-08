"""Rules: which cases can become one, what the teacher is shown, how its code is tried, and the
`rule` word. The teacher is scripted. Its code runs in the real sandbox."""
from los import cases, plugins, rules, sandbox, state
from los.models import ModelUnavailable
from los.shell import Shell
from tests.helpers import Folders, Scripted, needs_sandbox

QUESTION, LEVELS = "Is this temperature fine or worrying?", ["fine", "worrying"]
HEALTH = plugins.Command("sys.health", "Say whether the machine looks healthy", {}, judges=("temperature", "memory"))
RULE = '''def rule(value):
    degrees = int(value.split()[0])
    if degrees < 75:
        return "fine"
    return "worrying" if degrees >= 80 else None'''
GOOD = {"decision": "write", "reason": "The answers turn\nbetween 70 and 90 °C.", "code": RULE}


def judged(value, answer, by="student", question=QUESTION, name="temperature"):
    cases.record("judgement", {"command": "sys.health", "name": name, "ask": question, "choices": LEVELS, "value": value},
                 answer, by, "accepted" if by == "user" else "", **({} if by == "user" else {"run": "a run"}))


def degrees(*readings, **more):
    for reading in readings:
        judged(f"{reading} °C", "fine" if reading < 80 else "worrying", **more)


class RecordTest(Folders):
    def test_a_rule_needs_enough_different_values_and_two_answers(self):
        with self.assertRaisesRegex(rules.Unsuitable, "nothing is on record for it yet"):
            rules.recorded("sys.health", "temperature")
        degrees(40, 50, 60, 60, 60, 60, 90)
        with self.assertRaisesRegex(rules.Unsuitable, r"only 4 different value\(s\) are on record for it, and a rule needs 6"):
            rules.recorded("sys.health", "temperature")
        degrees(41, 42, name="memory")                 # another judgement of the same command does not count
        degrees(45, 55)
        self.assertEqual(len(rules.recorded("sys.health", "temperature")[2]), 6)

    def test_answers_that_are_all_the_same_draw_no_line(self):
        degrees(40, 45, 50, 55, 60, 65)
        with self.assertRaisesRegex(rules.Unsuitable, "every recorded answer is the same"):
            rules.recorded("sys.health", "temperature")

    def test_one_answer_for_each_value_in_the_order_of_the_values_and_the_users_first(self):
        degrees(100, 9, 60, 70, 85, 95)
        judged("70 °C", "worrying", "user")
        judged("70 °C", "fine", "memory")               # an answer used again is not a new one
        judged("9 °C", "worrying", "rule")              # and what a rule said is not a case
        question, choices, listed = rules.recorded("sys.health", "temperature")
        self.assertEqual((question, choices), (QUESTION, LEVELS))
        self.assertEqual(listed, [("9 °C", "fine", "student"), ("60 °C", "fine", "student"), ("70 °C", "worrying", "user"),
                                  ("85 °C", "worrying", "student"), ("95 °C", "worrying", "student"),
                                  ("100 °C", "worrying", "student")])

    def test_only_answers_to_the_question_as_it_is_asked_now_count(self):
        degrees(40, 50, 60, 70, 85, 95, question="Is this fine for a server room?")
        degrees(41, 91)
        with self.assertRaisesRegex(rules.Unsuitable, "only 2 different"):
            rules.recorded("sys.health", "temperature")

    def test_a_quarter_is_held_back_spread_over_the_values_and_never_one_the_user_set(self):
        listed = [(f"{n} °C", "fine" if n < 80 else "worrying", "user" if n == 60 else "student") for n in range(40, 120, 10)]
        shown, held = rules.split(listed)
        self.assertEqual(([value for value, _, _ in held], len(shown)), (["100 °C"], 7))    # 60 °C is the user's, and shown
        shown, held = rules.split([(value, answer, "student") for value, answer, _ in listed])
        self.assertEqual([value for value, _, _ in held], ["60 °C", "100 °C"])
        one_sided = [("1", "fine", "student"), ("2", "fine", "student"), ("3", "worrying", "student"), ("4", "fine", "student")]
        self.assertEqual(rules.split(one_sided), (one_sided, []))      # holding back would hide the only other answer


class AskTest(Folders):
    SHOWN = [("60 °C", "fine", "student"), ("70 °C", "worrying", "user"), ("95 °C", "worrying", "student")]

    def test_the_teacher_is_shown_the_question_and_the_cases_and_asked_once(self):
        teacher = Scripted(GOOD)
        output, meta = rules.ask(teacher, HEALTH, "temperature", QUESTION, LEVELS, self.SHOWN)
        self.assertEqual((output, meta["seconds"], teacher.system), (GOOD, 1.5, rules.BRIEF))
        self.assertEqual(teacher.user, "Command: sys.health, which is described as: Say whether the machine looks healthy\n"
                                       "Judgement: temperature\nQuestion: Is this temperature fine or worrying?\n"
                                       "Allowed answers: fine | worrying\n\nRecorded cases:\n"
                                       '"60 °C" => fine\n"70 °C" => worrying   (set by the user)\n"95 °C" => worrying')
        teacher = Scripted({"decision": "maybe", "reason": "r"}, GOOD)
        with self.assertRaisesRegex(RuntimeError, "no valid output after 1 tries"):
            rules.ask(teacher, HEALTH, "temperature", QUESTION, LEVELS, self.SHOWN)
        with self.assertRaisesRegex(RuntimeError, "it chose to write a rule and returned none"):
            rules.ask(Scripted({"decision": "write", "reason": "r"}), HEALTH, "temperature", QUESTION, LEVELS, self.SHOWN)

    def test_a_rule_sent_back_goes_with_what_was_found_wrong(self):
        teacher = Scripted(GOOD)
        rules.ask(teacher, HEALTH, "temperature", QUESTION, LEVELS, self.SHOWN, ("def rule(value):\n    return 'fine'\n",
                                                                                  ['"95 °C" should give \'worrying\'']))
        self.assertTrue(teacher.user.endswith(
            "You wrote this rule for it:\ndef rule(value):\n    return 'fine'\n\nlo-s tried it, and this is what went "
            "wrong:\n- \"95 °C\" should give 'worrying'\n\nGive the whole rule again with that put right."))

    def test_code_that_cannot_be_a_rule_is_refused_unread(self):
        self.assertEqual(rules.check(RULE), [])
        self.assertEqual(rules.check("def rule(value):\n    return (\n"), ["the code does not parse: '(' was never closed on line 2"])
        self.assertEqual(rules.check("def decide(value):\n    return 'fine'\n"), ["the code does not define rule"])
        for signature in ("reading", "value, unit", "value, *more", "*, value", ""):
            self.assertEqual(rules.check(f"def rule({signature}):\n    return 'fine'\n"),
                             ["rule must take exactly one argument, named value"], signature)


@needs_sandbox
class TrialTest(Folders):
    SHOWN = [("60 °C", "fine", "student"), ("70 °C", "fine", "student"), ("90 °C", "worrying", "student")]
    HELD = [("77 °C", "worrying", "student"), ("95 °C", "worrying", "student")]

    def test_a_rule_must_give_every_answer_it_was_shown_and_may_leave_a_held_back_one_alone(self):
        self.assertEqual(rules.failures(RULE, self.SHOWN, self.HELD), ([], 1))      # 77 °C is left to the student

    def test_what_a_rule_gets_wrong_is_said_in_sentences(self):
        careless = "def rule(value):\n    return 'fine' if int(value.split()[0]) < 85 else 'worrying'\n"
        self.assertEqual(rules.failures(careless, self.SHOWN, self.HELD),
                         (['"77 °C" should give \'worrying\', and the rule gives \'fine\''], 1))
        timid = "def rule(value):\n    return 'fine' if value == '60 °C' else None\n"
        self.assertEqual(rules.failures(timid, self.SHOWN, self.HELD)[0],
                         ['"70 °C" should give \'fine\', and the rule gives None',
                          '"90 °C" should give \'worrying\', and the rule gives None'])
        broken, _ = rules.failures("def rule(value):\n    return int(value)\n", self.SHOWN[:1], self.HELD[:1])
        self.assertEqual(broken, ['"60 °C" should give \'fine\', and the rule gives an error (ValueError: invalid literal '
                                  "for int() with base 10: '60 °C')",
                                  '"77 °C" should give \'worrying\', and the rule gives an error (ValueError: invalid '
                                  "literal for int() with base 10: '77 °C')"])

    def test_the_rule_in_force_is_the_latest_whose_file_exists(self):
        self.assertEqual(rules.installed(), {})
        first = rules.install("sys.health", "temperature", QUESTION, LEVELS, RULE, Scripted(), 8)
        rules.install("sys.health", "temperature", QUESTION, LEVELS, RULE + "\n# again", Scripted(), 12)
        record = rules.installed()[("sys.health", "temperature")]
        self.assertEqual((record["cases"], record["written_by"], first.name, first.read_text().endswith("# again\n")),
                         (12, "scripted", "sys.health.temperature.py", True))
        asked = {"command": "sys.health", "name": "temperature", "ask": QUESTION, "choices": LEVELS, "value": "30 °C"}
        self.assertEqual((rules.answer(asked), rules.answer({**asked, "value": "77 °C"})), ("fine", None))
        first.unlink()
        self.assertEqual((rules.installed(), rules.answer(asked)), ({}, None))


@needs_sandbox
class RuleWordTest(Folders):
    def shell(self, *teacher_says, answers=()):
        self.shown, self.asked, self.teacher = [], [], Scripted(*teacher_says)
        self.teacher.model = "scripted-teacher"
        replies = list(answers)

        def ask(question):
            self.asked.append(question)
            if not replies:
                raise EOFError
            return replies.pop(0)

        return Shell({"sys.health": HEALTH}, ask, self.shown.append, teacher=self.teacher)

    def test_a_rule_is_tried_on_every_answer_shown_and_used_once_the_user_agrees(self):
        degrees(40, 50, 60, 70, 80, 90, 95, 100)
        shell = self.shell(GOOD, answers=["y"])
        shell.handle("rule sys.health temperature")
        self.assertEqual(self.shown[:2], ["Asking scripted-teacher for a rule from 6 answer(s) on record for temperature in "
                                          "sys.health. 2 more are held back to test it.", "Trying it on all 8 in the sandbox."])
        self.assertEqual(self.shown[2], RULE + "\n\nWhy: The answers turn between 70 and 90 °C.\nIt gives the answer on "
                         "record for all 6 it was shown. Of the 2 held back, it gives the answer on record for 2 and "
                         "leaves 0 to the student.")
        self.assertEqual(self.asked, ["Use this rule for temperature in sys.health? [y/N] "])
        path = state.directory() / "rules" / "sys.health.temperature.py"
        self.assertEqual(self.shown[3], "Installed. sys.health now asks the rule for temperature before the student, and "
                                        f"the student only when the rule has no answer.\nDelete {path} to remove it.")
        self.assertEqual((path.read_text(), rules.installed()[("sys.health", "temperature")]["cases"]), (RULE + "\n", 8))
        call, = state.read("rule_calls")
        self.assertEqual((call["command"], call["name"], call["model"], call["answer"]),
                         ("sys.health", "temperature", "scripted-teacher", GOOD))
        self.assertNotIn("(set by the user)", self.teacher.user)
        shell.handle("help sys.health")
        self.assertRegex(self.shown[-1], r"\nA rule answers temperature where it can, made from 8 answers on [\d-]+\.$")
        shell.handle("rule sys.health temperature")     # asking again says what it would replace
        self.assertIn("A rule for it is in use already, made from 8 answers on ", self.shown[6])

    def test_a_rule_that_gets_an_answer_wrong_is_not_offered_and_can_be_sent_back(self):
        degrees(40, 50, 60, 70, 80, 90, 95, 100)
        careless = {"decision": "write", "reason": "Hot is hot.", "code": "def rule(value):\n    return 'worrying'"}
        shell = self.shell(careless, GOOD, answers=["y", "n"])
        shell.handle("rule sys.health temperature")
        self.assertIn("\n\nWhy: Hot is hot.\nThis rule cannot be used:\n  - \"40 °C\" should give 'fine', and the rule gives "
                      "'worrying'\n", self.shown[2])
        self.assertEqual(self.asked[0], "Have scripted-teacher put it right? That is one more call to it. [y/N] ")
        self.assertTrue(self.shown[3].startswith("Asking scripted-teacher again for a rule from 6 answer(s)"))
        self.assertIn("lo-s tried it, and this is what went wrong:\n- \"40 °C\" should give 'fine'", self.teacher.user)
        self.assertEqual(self.shown[-1], "Not installed. What it wrote is kept in the state folder, in rule_calls.jsonl.")
        self.assertEqual((self.teacher.calls, len(state.read("rule_calls")), rules.installed()), (2, 2, {}))

    def test_nothing_is_asked_twice_unless_the_user_says_so(self):
        degrees(40, 50, 60, 70, 80, 90, 95, 100)
        for said, expected in (({"decision": "write", "reason": "r", "code": "def decide(value): pass"},
                                "Not installed. What it wrote is kept in the state folder, in rule_calls.jsonl."),
                               ({"decision": "decline", "reason": "The answers contradict each other."},
                                "It declined: The answers contradict each other."),
                               (ModelUnavailable("the claude program is not installed"),
                                "No rule came back: the claude program is not installed")):
            shell = self.shell(said, GOOD)
            shell.handle("rule sys.health temperature")
            self.assertEqual((self.shown[-1], self.teacher.calls), (expected, 1))
        self.assertEqual(["failed" in call for call in state.read("rule_calls")], [False, False, True])

    def test_the_teacher_is_not_asked_when_no_rule_could_come_of_it(self):
        shell = self.shell(GOOD)
        for wrong_use in ("rule", "rule sys.health", "rule sys.health mood", "rule fs.list size"):
            shell.handle(wrong_use)
            self.assertEqual(self.shown[-1], "Usage: rule COMMAND NAME, for a judgement a command asks for: "
                                             "sys.health temperature, sys.health memory.")
        shell.handle("rule sys.health temperature")
        self.assertEqual(self.shown[-1], "No rule for temperature in sys.health yet: nothing is on record for it yet.")
        degrees(40, 50, 60)
        shell.handle("rule sys.health temperature")
        self.assertEqual(self.shown[-1], "No rule for temperature in sys.health yet: only 3 different value(s) are on "
                                         "record for it, and a rule needs 6.")
        shell.teacher = None
        shell.handle("rule sys.health temperature")
        self.assertEqual(self.shown[-1], "No model is set up as the teacher. Give the teacher role a provider in los.toml.")
        self.assertEqual(self.teacher.calls, 0)
