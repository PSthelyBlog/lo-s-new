"""Judgements and a command's own questions: who answers, what is recorded, and what the user sees."""
from los import cases, judge, plugins, rules, sandbox, state
from los.models import ModelUnavailable
from los.sandbox import Refused
from los.shell import Shell
from tests.helpers import Folders, Scripted, needs_sandbox, table

HEALTH, = table(("sys.health", [], "read")).values()
QUESTION, LEVELS = "Is this temperature fine or worrying?", ["fine", "worrying"]
FINE, WORRYING = {"answer": "fine"}, {"answer": "worrying"}


def recorded():
    return [(case["question"]["value"], case["answer"], case["by"]) for case in cases.judgements()]


class Case(Folders):
    def minds(self, *student_says, teacher_says=(), answers=None):
        self.student, self.teacher, self.asked = Scripted(*student_says), Scripted(*teacher_says), []
        self.teacher.model = "scripted-teacher"

        def confirm(question, default):
            self.asked.append(question)
            return answers.pop(0)

        return judge.Minds(self.student, self.teacher, confirm if answers is not None else None)

    def judge(self, minds, value, run="run 1", question=QUESTION, name="temperature"):
        return minds.judge(HEALTH, run, name, question, value, LEVELS)

    def stretch(self, reach, value, answer, question=QUESTION, verdict="accepted"):
        cases.record("judgement", {"command": "sys.health", "name": "temperature", "ask": question, "choices": LEVELS,
                                   "value": value}, answer, "user", verdict, reach=reach)


class JudgementTest(Case):
    def test_the_student_is_asked_with_the_question_first_and_the_value_alone_last(self):
        minds = self.minds(WORRYING)
        self.assertEqual(self.judge(minds, "91 °C"), "worrying")
        self.assertTrue(self.student.system.startswith(f"Question: {QUESTION}\nAllowed answers: fine | worrying\n\n"))
        self.assertEqual((self.student.user, self.student.schema["properties"]["answer"]["enum"]), ("Value: 91 °C", LEVELS))
        case, = cases.judgements()
        self.assertEqual(case["question"], {"command": "sys.health", "name": "temperature", "ask": QUESTION,
                                            "choices": LEVELS, "value": "91 °C"})
        self.assertEqual((case["answer"], case["by"], case["verdict"], case["run"], case["model"], case["seconds"]),
                         ("worrying", "student", "", "run 1", "scripted", 1.5))

    def test_a_value_judged_before_is_answered_from_the_record(self):
        minds = self.minds(FINE, WORRYING)
        self.assertEqual([self.judge(minds, value) for value in ("60 °C", "60 °C", "90 °C", "60 °C")],
                         ["fine", "fine", "worrying", "fine"])
        self.assertEqual(self.student.calls, 2)
        self.assertEqual(recorded(), [("60 °C", "fine", "student"), ("60 °C", "fine", "memory"),
                                      ("90 °C", "worrying", "student"), ("60 °C", "fine", "memory")])
        self.assertEqual(cases.judgements()[1]["source"], "student")

    def test_an_answer_the_user_set_comes_before_anything_a_model_said(self):
        minds = self.minds(FINE)
        self.judge(minds, "80 °C")
        cases.record("judgement", cases.judgements()[0]["question"], "worrying", "user", "accepted")
        self.assertEqual(self.judge(minds, "80 °C"), "worrying")
        self.assertEqual((self.student.calls, cases.judgements()[-1]["source"]), (1, "user"))

    def test_an_answer_the_user_set_for_a_stretch_holds_for_every_value_in_it(self):
        minds = self.minds(FINE, FINE)
        self.stretch("from", "85 °C", "worrying")
        self.assertEqual([self.judge(minds, value) for value in ("85 °C", "99.5 °C", "84 °C", "90 degrees")],
                         ["worrying", "worrying", "fine", "fine"])
        self.assertEqual(self.student.calls, 2)         # for the one below it, and the one written another way
        self.assertEqual([(case["by"], case.get("source")) for case in cases.judgements()[1:3]], [("memory", "user")] * 2)
        self.stretch("up to", "30 °C", "worrying")
        self.assertEqual([self.judge(minds, value) for value in ("30 °C", "-5 °C")], ["worrying", "worrying"])
        self.assertEqual(self.student.calls, 2)
        self.stretch("from", "85 °C", "fine", question="Is this fine for a server room?")    # another question's stretch
        self.assertEqual(self.judge(minds, "86 °C"), "worrying")

    def test_a_stretch_comes_after_the_users_answer_for_one_value_and_before_the_students(self):
        minds = self.minds(FINE, FINE)
        self.assertEqual([self.judge(minds, value) for value in ("90 °C", "95 °C")], ["fine", "fine"])
        cases.record("judgement", cases.judgements()[1]["question"], "fine", "user", "accepted")    # 95 °C, by the user
        self.stretch("from", "85 °C", "worrying")
        self.assertEqual([self.judge(minds, value) for value in ("90 °C", "95 °C")], ["worrying", "fine"])
        self.assertEqual(self.student.calls, 2)
        self.assertEqual(minds.sample(HEALTH, "temperature", QUESTION, "88 °C", LEVELS), "worrying")
        self.assertEqual(self.student.calls, 2)         # a value asked about on purpose is not put to the student either

    def test_a_stretch_reaches_to_the_next_one_and_where_two_meet_the_last_said_holds(self):
        minds = self.minds()
        self.stretch("from", "80 °C", "fine")           # the further one is set last, and the nearer one still holds
        self.stretch("from", "60 °C", "worrying")
        self.assertEqual([self.judge(minds, value) for value in ("70 °C", "90 °C")], ["worrying", "fine"])
        self.stretch("up to", "75 °C", "fine")          # it meets the one from 60 °C, and was said last
        self.assertEqual([self.judge(minds, value) for value in ("65 °C", "50 °C", "78 °C")], ["fine", "fine", "worrying"])
        self.stretch("from", "60 °C", "worrying")       # said again, so it is the last now
        self.assertEqual([self.judge(minds, value) for value in ("65 °C", "50 °C")], ["worrying", "fine"])
        self.stretch("from", "80 °C", "worrying")       # one set again at the same value takes the other's place
        self.assertEqual(self.judge(minds, "90 °C"), "worrying")
        self.assertEqual(self.student.calls, 0)

    def test_what_the_user_took_back_counts_no_more_than_if_they_had_never_set_it(self):
        minds = self.minds(FINE, FINE)
        self.judge(minds, "80 °C")
        question = cases.judgements()[0]["question"]
        cases.record("judgement", question, "fine", "user", "accepted")
        cases.record("judgement", question, "worrying", "user", "accepted")
        cases.record("judgement", question, "worrying", "user", "taken back")
        self.assertEqual(self.judge(minds, "80 °C"), "fine")        # what the student said, and not what was set first
        self.assertEqual((self.student.calls, cases.judgements()[-1]["source"]), (1, "student"))
        self.stretch("from", "70 °C", "fine")
        self.stretch("from", "85 °C", "worrying")
        self.assertEqual(self.judge(minds, "90 °C"), "worrying")
        self.stretch("from", "85.0 °C", "worrying", verdict="taken back")       # the same start, written another way
        self.assertEqual(self.judge(minds, "90 °C"), "fine")        # the one from 70 °C reaches there now
        self.stretch("from", "70 °C", "fine", verdict="taken back")
        self.assertEqual((cases.own(question), cases.stretches(question)), (({}, []), []))
        self.assertEqual((self.judge(minds, "90 °C"), self.student.calls), ("fine", 2))     # nothing is left, so it asks
        self.stretch("from", "85 °C", "worrying")                   # set again, it holds again
        self.assertEqual((self.judge(minds, "95 °C"), self.student.calls), ("worrying", 2))

    def test_the_record_holds_for_one_question_of_one_command_only(self):
        minds = self.minds(FINE, WORRYING, WORRYING)
        self.judge(minds, "80 °C")
        self.assertEqual(self.judge(minds, "80 °C", question="Is this temperature fine or worrying for a server room?"),
                         "worrying")
        self.assertEqual(self.judge(minds, "80 °C", name="exhaust"), "worrying")
        self.assertEqual(self.student.calls, 3)

    def test_with_nobody_to_judge_the_command_is_told_so(self):
        with self.assertRaisesRegex(Refused, "no model is set up as the student, which would judge temperature"):
            self.judge(judge.Minds(), "80 °C")
        with self.assertRaisesRegex(Refused, r"the student, which would judge temperature, did not answer \(no answer"):
            self.judge(self.minds(ModelUnavailable("no answer from the server")), "80 °C")
        with self.assertRaisesRegex(Refused, "the student's judgement of temperature could not be used"):
            self.judge(self.minds({"answer": "hot"}, {"answer": "hot"}, {"answer": "hot"}), "80 °C")
        self.assertEqual(cases.judgements(), [])

    def test_the_student_can_be_asked_on_purpose_about_a_value_no_run_produced(self):
        minds = self.minds(WORRYING, FINE)
        self.assertEqual(minds.sample(HEALTH, "temperature", QUESTION, "90 °C", LEVELS), "worrying")
        case, = cases.judgements()
        self.assertEqual((case["by"], case["spread"], "run" in case, case["seconds"]), ("student", True, False, 1.5))
        self.assertEqual(minds.sample(HEALTH, "temperature", QUESTION, "90 °C", LEVELS), "worrying")   # on record: not asked
        self.assertEqual((self.student.calls, len(cases.judgements()), cases.latest_run()), (1, 1, []))
        self.assertEqual(self.judge(minds, "90 °C"), "worrying")        # and a run finds it on record like any other
        self.assertEqual((self.student.calls, cases.judgements()[-1]["by"]), (1, "memory"))

    def test_a_command_being_tried_out_leaves_no_record_and_uses_none(self):
        minds = self.minds(FINE, WORRYING, FINE)
        self.judge(minds, "80 °C")
        trial = minds.trial()
        self.assertEqual((self.judge(trial, "80 °C"), self.judge(trial, "80 °C")), ("worrying", "fine"))
        self.assertEqual(recorded(), [("80 °C", "fine", "student")])


@needs_sandbox
class RuleInTheOrderTest(Case):
    RULE = "def rule(value):\n    degrees = int(value.split()[0])\n    return None if 70 <= degrees < 85 else 'fine' if degrees < 70 else 'worrying'\n"

    def install(self, code=RULE, question=QUESTION):
        return rules.install("sys.health", "temperature", question, LEVELS, code, Scripted(), 8)

    def test_a_rule_is_asked_before_the_student_and_after_the_record(self):
        minds = self.minds(WORRYING, FINE)
        self.judge(minds, "50 °C")                      # the student says worrying, and that is on record
        self.install()
        self.assertEqual([self.judge(minds, value) for value in ("50 °C", "40 °C", "95 °C", "75 °C")],
                         ["worrying", "fine", "worrying", "fine"])
        self.assertEqual([by for _, _, by in recorded()], ["student", "memory", "rule", "rule", "student"])
        self.assertEqual(self.student.calls, 2)         # only for the value the rule leaves alone

    def test_what_a_rule_answered_is_worked_out_again_and_goes_when_the_rule_goes(self):
        minds, path = self.minds(WORRYING), self.install()
        self.assertEqual((self.judge(minds, "40 °C"), self.judge(minds, "40 °C")), ("fine", "fine"))
        self.assertEqual([by for _, _, by in recorded()], ["rule", "rule"])
        path.unlink()
        self.assertEqual((self.judge(minds, "40 °C"), rules.installed()), ("worrying", {}))

    def test_an_answer_the_user_took_back_is_the_rules_again(self):
        minds = self.minds()
        self.install()
        question = {"command": "sys.health", "name": "temperature", "ask": QUESTION, "choices": LEVELS, "value": "40 °C"}
        cases.record("judgement", question, "worrying", "user", "accepted")
        self.assertEqual(self.judge(minds, "40 °C"), "worrying")
        cases.record("judgement", question, "worrying", "user", "taken back")
        self.assertEqual((self.judge(minds, "40 °C"), cases.judgements()[-1]["by"], self.student.calls), ("fine", "rule", 0))

    def test_a_rule_made_for_another_question_is_not_asked(self):
        minds = self.minds(WORRYING)
        self.install(question="Is this temperature fine or worrying for a server room?")
        self.assertEqual(self.judge(minds, "40 °C"), "worrying")

    def test_a_rule_that_fails_or_answers_something_else_leaves_it_to_the_student(self):
        for code in ("def rule(value):\n    return 1 / 0\n", "def rule(value):\n    return 'hot'\n",
                     "def rule(value):\n    print('thinking')\n    return 'fine'\n", "rule = 3\n"):
            minds = self.minds(WORRYING)
            self.install(code)
            self.assertEqual(self.judge(minds, "40 °C", run=code), "worrying", code)

    def test_a_rule_holds_nothing_and_can_ask_for_nothing(self):
        (self.files / "secret.txt").write_text("secret")
        for attempt in (f"open({str(self.files / 'secret.txt')!r}).read()", "__import__('os').listdir('/home')",
                        "__import__('los').fetch('https://example.org/')",
                        "__import__('los').judge('temperature', 'q', 'v', ['fine', 'worrying'])"):
            got, fault = rules.apply(f"def rule(value):\n    return {attempt}\n", "40 °C")
            self.assertEqual((got, fault.startswith("an error (")), (None, True), attempt)
        self.assertIn("this code may not ask the core for anything", rules.apply(
            "def rule(value):\n    return __import__('los').fetch('https://example.org/')\n", "40 °C")[1])
        self.assertEqual(state.read("calls"), [])


class QuestionTest(Case):
    ASKS, = table(("chat.ask", ["to", "message"], "read")).values()

    def test_the_student_answers_a_question_in_free_text(self):
        minds = self.minds({"answer": "A lock that one thread holds at a time."})
        self.assertEqual(minds.ask(self.ASKS, "student", "What is a mutex?"), "A lock that one thread holds at a time.")
        self.assertEqual((self.student.user, self.student.limit, self.asked), ("What is a mutex?", judge.ROOM, []))
        record, = state.read("asks")
        self.assertEqual((record["command"], record["to"], record["model"], record["seconds"]),
                         ("chat.ask", "student", "scripted", 1.5))

    def test_a_question_to_the_teacher_is_shown_and_sent_only_on_a_yes(self):
        minds = self.minds(teacher_says=[{"answer": "It depends."}], answers=[False, True])
        with self.assertRaisesRegex(Refused, "was not sent to scripted-teacher, because you did not say yes"):
            minds.ask(self.ASKS, "teacher", "Is  Rust\nfaster than C?")
        self.assertEqual((self.teacher.calls, state.read("asks")), (0, []))
        self.assertEqual(self.asked, ["chat.ask wants to put this to scripted-teacher, which is one call to it:\n"
                                      "  Is Rust faster than C?\nSend it?"])
        self.assertEqual(minds.ask(self.ASKS, "teacher", "Is Rust faster than C?"), "It depends.")
        self.assertEqual((self.teacher.calls, state.read("asks")[0]["to"]), (1, "teacher"))

    def test_a_long_question_to_the_teacher_is_shown_in_part_with_its_length(self):
        minds = self.minds(teacher_says=[{"answer": "Yes."}], answers=[True])
        minds.ask(self.ASKS, "teacher", "word " * 200)
        self.assertTrue(self.asked[0].endswith(" ... (1000 characters in all)\nSend it?"))

    def test_the_teacher_is_not_called_with_nobody_to_ask_or_in_a_trial_and_gets_one_try(self):
        with self.assertRaisesRegex(Refused, "did not say yes"):
            self.minds(teacher_says=[{"answer": "x"}]).ask(self.ASKS, "teacher", "Anything?")
        with self.assertRaisesRegex(Refused, judge.TRIAL):
            self.minds(teacher_says=[{"answer": "x"}], answers=[True]).trial().ask(self.ASKS, "teacher", "Anything?")
        self.assertEqual(self.teacher.calls, 0)
        minds = self.minds(teacher_says=[{"reply": "wrong shape"}, {"answer": "x"}], answers=[True])
        with self.assertRaisesRegex(Refused, "the teacher gave no answer"):
            minds.ask(self.ASKS, "teacher", "Anything?")
        self.assertEqual((self.teacher.calls, "failed" in state.read("asks")[0]), (1, True))

    def test_a_role_nobody_fills_cannot_be_asked(self):
        with self.assertRaisesRegex(Refused, "no model is set up as the student"):
            judge.Minds().ask(self.ASKS, "student", "Anything?")


MANIFEST = '''
name = "probe"

[commands.judge]
description = "Ask for a judgement"
judges = ["size"]
[commands.judge.params]
name = "the judgement to ask for"
value = "what to judge"
choices = "the answers allowed, separated by commas"

[commands.ask]
description = "Put a question to a model"
asks = ["student"]
[commands.ask.params]
to = "student or teacher"
message = "the question"

[commands.neither]
description = "Try both with nothing declared"
[commands.neither.params]
what = "judge or ask"
'''
CODE = '''
from los import ask, judge


def do_judge(name="size", value="3 GB", choices="small,large"):
    return judge(name, "Is this file small or large?", value, choices.split(",") if choices else [])


def do_ask(to="student", message="What is a mutex?"):
    return ask(to, message)


def do_neither(what=None):
    return judge("size", "q", "v", ["a", "b"]) if what == "judge" else ask("student", "Anything?")
'''


@needs_sandbox
class ThroughTheSandboxTest(Case):
    def setUp(self):
        super().setUp()
        self.table, problems = self.plugin(MANIFEST, CODE)
        self.assertEqual(problems, [])

    def run_it(self, command, minds, /, **args):
        result = sandbox.run(self.table[command], args, minds=minds)
        self.assertFalse(result.broke, result.text)
        return result.text

    def test_a_command_gets_its_judgement_from_the_core(self):
        minds = self.minds({"answer": "large"})
        self.assertEqual((self.run_it("probe.judge", minds), self.run_it("probe.judge", minds)), ("large", "large"))
        self.assertEqual((self.student.calls, self.student.user), (1, "Value: 3 GB"))
        first, second = cases.judgements()
        self.assertEqual((first["question"]["command"], first["by"], second["by"]), ("probe.judge", "student", "memory"))
        self.assertNotEqual(first["run"], second["run"])
        call = state.read("calls")[0]
        self.assertEqual((call["call"], call["name"], call["choices"], call["outcome"]), ("judge", "size", ["small", "large"], "done"))

    def test_only_a_judgement_the_manifest_names_and_a_real_choice_are_answered(self):
        minds = self.minds()
        self.assertEqual(self.run_it("probe.judge", minds, name="mood"),
                         "probe.judge may ask for a judgement of size, and 'mood' is not that")
        for choices in ("only", "same,same", "a, ,b", ",".join(map(str, range(13)))):
            self.assertEqual(self.run_it("probe.judge", minds, choices=choices),
                             "a judgement needs 2 to 12 different answers to choose from", choices)
        self.assertIn("a value of at most 2000", self.run_it("probe.judge", minds, value="x" * 2001))
        self.assertEqual(self.run_it("probe.neither", minds, what="judge"),
                         "probe.neither may ask for a judgement of nothing, and 'size' is not that")
        self.assertEqual((self.student.calls, cases.judgements()), (0, []))

    def test_a_command_puts_its_question_only_to_a_model_the_manifest_lists(self):
        minds = self.minds({"answer": "A lock."}, teacher_says=[{"answer": "never asked"}], answers=[True])
        self.assertEqual(self.run_it("probe.ask", minds), "A lock.")
        self.assertEqual(self.run_it("probe.ask", minds, to="teacher"),
                         "probe.ask may put a question to student, and 'teacher' is not that")
        self.assertEqual(self.run_it("probe.neither", minds), "probe.neither may put a question to no model, and 'student' is not that")
        self.assertIn("at most 12000 characters, and this one has 12001", self.run_it("probe.ask", minds, message="x" * 12001))
        self.assertEqual((self.teacher.calls, self.asked), (0, []))
        self.assertEqual([call["outcome"] == "done" for call in state.read("calls")], [True, False, False, False])

    def test_without_anything_to_answer_no_model_is_reached(self):
        self.assertEqual(self.run_it("probe.judge", None), "no model can be asked here")
        self.assertEqual(self.run_it("probe.ask", None), "no model can be asked here")


USAGE = ("Usage: trace sys.health temperature VALUE is ANSWER, with one of its answers: fine or worrying. from VALUE or "
         "up to VALUE sets every value above it or below it as well. forget VALUE takes back what you set, with from or "
         "up to for a stretch.")


class TraceTest(Folders):
    def shell(self, answers=()):
        self.shown, replies = [], list(answers)
        health = plugins.Command("sys.health", "Test command sys.health", {}, judges=("memory", "temperature"))
        return Shell({"sys.health": health}, lambda question: replies.pop(0), self.shown.append)

    def judged(self, run, name, value, answer, by, **more):
        cases.record("judgement", {"command": "sys.health", "name": name, "ask": f"Is this {name} fine or worrying?",
                                   "choices": LEVELS, "value": value}, answer, by, run=run, **more)

    def test_trace_shows_the_latest_run_and_where_each_answer_came_from(self):
        shell = self.shell()
        shell.handle("trace")
        self.assertEqual(self.shown, ["No command has asked for a judgement yet."])
        self.judged("run 1", "memory", "70% of 31 GB available", "fine", "student", seconds=0.62)
        self.judged("run 2", "memory", "70% of 31 GB available", "fine", "memory", source="student")
        self.judged("run 2", "temperature", "91 °C", "worrying", "rule")
        self.judged("run 2", "fan", "2400 rpm", "fine", "student", seconds=0.58)
        shell.handle("trace")
        self.assertEqual(self.shown[1:], [
            "sys.health asked for 3 judgements the last time it needed any:",
            "1. memory of 70% of 31 GB available: fine  (on record, from the student)",
            "2. temperature of 91 °C: worrying  (a rule)",
            "3. fan of 2400 rpm: fine  (the student, 0.6 s)",
            "To set one yourself: trace NUMBER ANSWER, such as trace 1 worrying."])

    def test_the_user_can_set_an_answer_and_it_is_used_from_then_on(self):
        shell = self.shell()
        self.judged("run 1", "memory", "12% of 31 GB available", "fine", "student", seconds=0.6)
        self.judged("run 1", "temperature", "91 °C", "fine", "rule")
        shell.handle("trace 1 worrying")
        self.assertEqual(self.shown[-1], "Set: sys.health takes memory of 12% of 31 GB available as worrying from now on.")
        self.assertEqual(cases.judged(cases.judgements()[0]["question"])["answer"], "worrying")
        shell.handle("trace 2 worrying")
        self.assertEqual(self.shown[-1], "Set: sys.health takes temperature of 91 °C as worrying from now on.\n"
                                         "A rule said fine. Your answer comes first for this value. If the rule is wrong "
                                         "more widely, rule sys.health temperature makes a new one from the record.")
        shell.handle("trace")
        self.assertEqual(self.shown[-3:-1], [
            "1. memory of 12% of 31 GB available: fine  (the student, 0.6 s); you have since set it to worrying",
            "2. temperature of 91 °C: fine  (a rule); you have since set it to worrying"])
        self.judged("run 2", "memory", "12% of 31 GB available", "worrying", "memory", source="user")
        shell.handle("trace")
        self.assertEqual(self.shown[-2:], ["1. memory of 12% of 31 GB available: worrying  (on record, set by you)",
                                           "To set one yourself: trace NUMBER ANSWER, such as trace 1 fine. To take back "
                                           "what you set: trace forget NUMBER."])

    def test_trace_shows_everything_on_record_for_one_judgement_and_sets_any_value(self):
        shell = self.shell()
        shell.handle("trace sys.health")
        self.assertEqual(self.shown[-1], "Usage: trace COMMAND NAME, for a judgement a command asks for: sys.health memory, "
                                         "sys.health temperature.")
        shell.handle("trace sys.health temperature")
        self.assertEqual(self.shown[-1], "Nothing is on record for temperature in sys.health yet. It asks when it runs.")
        for degrees in (40, 60, 80, 90, 100):
            self.judged("run 1", "temperature", f"{degrees} °C", "fine" if degrees < 85 else "worrying", "student")
        shell.handle("trace sys.health temperature")
        self.assertEqual(self.shown[-1], "On record for temperature in sys.health, 5 answers:\n  40 to 80 °C: fine\n"
                                         "  90 to 100 °C: worrying\nTo set one yourself: trace sys.health temperature "
                                         "VALUE is ANSWER, such as trace sys.health temperature 40 °C is worrying. With "
                                         "from VALUE or up to VALUE, the answer also holds for every value above it or "
                                         "below it.")
        shell.handle("trace sys.health temperature 80 °C is worrying")
        self.assertEqual(self.shown[-1], "Set: sys.health takes temperature of 80 °C as worrying from now on.")
        shell.handle("trace sys.health temperature 70 °C is fine")      # a value nobody judged yet
        shell.handle("trace sys.health temperature")
        self.assertTrue(self.shown[-1].startswith("On record for temperature in sys.health, 6 answers, 2 of them set by "
                                                  "you:\n  40 to 70 °C: fine\n  80 to 100 °C: worrying\n"))
        self.assertEqual(cases.judged(cases.judgements()[-1]["question"])["by"], "user")
        shell.handle("trace sys.health temperature 80C is worrying")
        self.assertEqual(self.shown[-1], "Set: sys.health takes temperature of 80C as worrying from now on.\nThe values on "
                                         "record look like 40 °C. One written another way will not come up when "
                                         "sys.health runs.")
        for wrong_use in ("trace sys.health temperature 80 °C", "trace sys.health temperature 80 °C is hot",
                          "trace sys.health temperature is fine"):
            shell.handle(wrong_use)
            self.assertEqual(self.shown[-1], USAGE, wrong_use)

    def test_one_line_sets_a_value_and_every_one_above_or_below_it(self):
        shell = self.shell()
        for degrees in (40, 60, 80, 90, 100):
            self.judged("run 1", "temperature", f"{degrees} °C", "fine" if degrees < 95 else "worrying", "student")
        shell.handle("trace sys.health temperature from 85 °C is worrying")
        self.assertEqual(self.shown[-1], "Set: sys.health takes temperature of 85 °C and every value above it as worrying "
                                         "from now on.\n1 answer on record changes with it: 90 °C.")
        shell.handle("trace sys.health temperature up to 84 °C is fine")
        self.assertEqual(self.shown[-1], "Set: sys.health takes temperature of 84 °C and every value below it as fine "
                                         "from now on.")
        shell.handle("trace sys.health temperature")
        self.assertTrue(self.shown[-1].startswith(
            "On record for temperature in sys.health, 7 answers, 7 of them set by you:\n  40 to 84 °C: fine\n"
            "  85 to 100 °C: worrying\nYou set: up to 84 °C is fine; from 85 °C is worrying.\nTo set one yourself: "))
        self.assertEqual([cases.judged({**cases.judgements()[0]["question"], "value": value})["answer"]
                          for value in ("12 °C", "84 °C", "85 °C", "300 °C")], ["fine", "fine", "worrying", "worrying"])

    def test_a_stretch_says_what_it_changes_and_what_it_leaves_alone(self):
        shell = self.shell()
        for degrees in range(50, 100, 5):
            self.judged("run 1", "temperature", f"{degrees} °C", "fine", "student")
        shell.handle("trace sys.health temperature 90 °C is fine")
        shell.handle("trace sys.health temperature from 60 °C is worrying")
        self.assertEqual(self.shown[-1], "Set: sys.health takes temperature of 60 °C and every value above it as worrying "
                                         "from now on.\n7 answers on record change with it: 60 °C, 65 °C, 70 °C, 75 °C, "
                                         "80 °C and 2 more.\nWhat you set for a single value stays as it is: 90 °C is fine.")
        shell.handle("trace sys.health temperature from 60 °C is worrying")      # said twice, it changes nothing more
        self.assertEqual(self.shown[-1], "Set: sys.health takes temperature of 60 °C and every value above it as worrying "
                                         "from now on.\nWhat you set for a single value stays as it is: 90 °C is fine.")
        shell.handle("trace sys.health temperature from 60C is worrying")
        self.assertTrue(self.shown[-1].endswith("\nThe values on record look like 50 °C. One written another way will not "
                                                "come up when sys.health runs."))
        shell.handle("trace sys.health temperature up to warm is fine")
        self.assertEqual(self.shown[-1], 'up to goes by the number in a value, and "warm" has none.')
        for wrong_use in ("trace sys.health temperature from 85 °C", "trace sys.health temperature up to 85 °C is hot",
                          "trace sys.health temperature from is fine"):
            shell.handle(wrong_use)
            self.assertEqual(self.shown[-1], USAGE, wrong_use)

    def test_the_user_can_take_back_an_answer_they_set_for_a_value_of_the_latest_run(self):
        shell = self.shell()
        self.judged("run 1", "temperature", "80 °C", "fine", "student", seconds=0.6)
        self.judged("run 1", "temperature", "95 °C", "worrying", "rule")
        shell.handle("trace 1 worrying")
        shell.handle("trace 2 fine")
        self.judged("run 2", "temperature", "80 °C", "worrying", "memory", source="user")
        self.judged("run 2", "temperature", "95 °C", "fine", "memory", source="user")
        shell.handle("trace")
        self.assertEqual(self.shown[-1], "To set one yourself: trace NUMBER ANSWER, such as trace 1 fine. To take back what "
                                         "you set: trace forget NUMBER.")
        shell.handle("trace forget 1")
        self.assertEqual(self.shown[-1], "Taken back: your answer for temperature of 80 °C in sys.health, which was "
                                         "worrying. It is now fine, as the student said.")
        shell.handle("trace forget 2")
        self.assertEqual(self.shown[-1], "Taken back: your answer for temperature of 95 °C in sys.health, which was fine. "
                                         "sys.health asks the student when it next meets that value.")
        shell.handle("trace")
        self.assertEqual(self.shown[-3:], [
            "1. temperature of 80 °C: worrying  (on record, set by you); you have since taken that back",
            "2. temperature of 95 °C: fine  (on record, set by you); you have since taken that back",
            "To set one yourself: trace NUMBER ANSWER, such as trace 1 fine."])
        shell.handle("trace forget 1")
        self.assertEqual(self.shown[-1], "You have set no answer for temperature of 80 °C alone.")
        for wrong_use in ("trace forget", "trace forget 3", "trace forget one", "trace forget 1 2"):
            shell.handle(wrong_use)
            self.assertEqual(self.shown[-1], "Usage: trace forget NUMBER, with a number that trace lists.", wrong_use)
        self.assertEqual([(case["answer"], case["verdict"]) for case in cases.judgements() if case["by"] == "user"],
                         [("worrying", "accepted"), ("fine", "accepted"), ("worrying", "taken back"), ("fine", "taken back")])

    def test_an_answer_taken_back_under_a_rule_is_the_rules_again(self):
        shell = self.shell()
        self.judged("run 1", "temperature", "95 °C", "worrying", "rule")
        rules.install("sys.health", "temperature", "Is this temperature fine or worrying?", LEVELS,
                      "def rule(value):\n    return 'worrying'\n", Scripted(), 8)
        shell.handle("trace 1 fine")
        shell.handle("trace forget 1")
        self.assertEqual(self.shown[-1], "Taken back: your answer for temperature of 95 °C in sys.health, which was fine. "
                                         "It is now worrying, by its rule.")

    def test_the_user_can_take_back_a_stretch_or_the_answer_for_any_value(self):
        shell = self.shell()
        for degrees in (40, 60, 80, 90, 100):
            self.judged("run 1", "temperature", f"{degrees} °C", "fine" if degrees < 95 else "worrying", "student")
        for line in ("from 50 °C is worrying", "from 85 °C is fine", "60 °C is fine", "80 °C is fine"):
            shell.handle(f"trace sys.health temperature {line}")
        shell.handle("trace sys.health temperature")
        self.assertTrue(self.shown[-1].endswith("\nTo take back what you set: trace sys.health temperature forget VALUE, "
                                                "such as trace sys.health temperature forget from 50 °C."))
        shell.handle("trace sys.health temperature forget from 85 °C")
        self.assertEqual(self.shown[-1], "Taken back: your answer for temperature of 85 °C and every value above it in "
                                         "sys.health, which was fine.\n2 answers on record change with it: 90 °C and "
                                         "100 °C to worrying.")
        shell.handle("trace sys.health temperature forget 80 °C is fine")       # what the answer was may follow
        self.assertEqual(self.shown[-1], "Taken back: your answer for temperature of 80 °C in sys.health, which was fine. "
                                         "It is now worrying, by what you set from 50 °C.")
        shell.handle("trace sys.health temperature forget 80 °C")
        self.assertEqual(self.shown[-1], "You have set no answer for temperature of 80 °C alone. It is worrying by what "
                                         "you set from 50 °C. trace sys.health temperature forget from 50 °C takes that back.")
        shell.handle("trace sys.health temperature forget up to 50 °C")
        self.assertEqual(self.shown[-1], "You have set nothing up to 50 °C for temperature in sys.health. You set: from "
                                         "50 °C is worrying.")
        shell.handle("trace sys.health temperature forget from 50.0 °C")        # the same start, written another way
        self.assertEqual(self.shown[-1], "Taken back: your answer for temperature of 50 °C and every value above it in "
                                         "sys.health, which was worrying.\n2 answers on record change with it: 80 °C and "
                                         "90 °C to fine.")
        shell.handle("trace sys.health temperature forget from 50 °C")
        self.assertEqual(self.shown[-1], "You have set nothing from 50 °C for temperature in sys.health.")
        shell.handle("trace sys.health temperature forget 60 °C")
        self.assertEqual(self.shown[-1], "Taken back: your answer for temperature of 60 °C in sys.health, which was fine. "
                                         "It stays fine, as the student said.")
        for wrong_use in ("trace sys.health temperature forget", "trace sys.health temperature forget from",
                          "trace sys.health temperature forget up to"):
            shell.handle(wrong_use)
            self.assertEqual(self.shown[-1], USAGE, wrong_use)
        shell.handle("trace sys.health temperature")                             # as it was before anything was set
        self.assertEqual(self.shown[-1], "On record for temperature in sys.health, 5 answers:\n  40 to 90 °C: fine\n"
                                         "  100 °C: worrying\nTo set one yourself: trace sys.health temperature VALUE is "
                                         "ANSWER, such as trace sys.health temperature 40 °C is worrying. With from VALUE "
                                         "or up to VALUE, the answer also holds for every value above it or below it.")

    def test_trace_says_how_to_set_an_answer_when_it_cannot_read_one(self):
        shell = self.shell()
        self.judged("run 1", "memory", "12% of 31 GB available", "fine", "student")
        for wrong_use in ("trace 1", "trace 1 hot", "trace 1 fine worrying"):
            shell.handle(wrong_use)
            self.assertEqual(self.shown[-1], "Usage: trace NUMBER ANSWER, with a number that trace lists and one of that "
                                             "judgement's answers: fine or worrying.", wrong_use)
        for wrong_use in ("trace 2 fine", "trace first fine", "trace 0 fine"):
            shell.handle(wrong_use)
            self.assertEqual(self.shown[-1], "Usage: trace NUMBER ANSWER, with a number that trace lists and one of that "
                                             "judgement's answers.", wrong_use)
        self.assertEqual(len(cases.judgements()), 1)

    def test_stats_count_who_made_the_judgements(self):
        shell = self.shell()
        self.judged("run 1", "memory", "70%", "fine", "student", seconds=0.62)
        self.judged("run 1", "temperature", "91 °C", "fine", "student", seconds=0.58)
        self.judged("run 2", "memory", "70%", "fine", "memory", source="student")
        self.judged("run 2", "temperature", "95 °C", "worrying", "rule")
        shell.handle("trace 2 fine")
        shell.handle("trace 1 worrying")
        shell.handle("trace forget 1")
        state.append("delegations", {"words": "x", "answer": {"answer": "cannot"}})
        state.append("rule_calls", {"command": "sys.health", "failed": "no answer"})
        state.append("asks", {"command": "chat.ask", "to": "student", "seconds": 1})
        state.append("asks", {"command": "chat.ask", "to": "teacher", "seconds": 9})
        shell.handle("stats")
        self.assertEqual(self.shown[-1].splitlines()[5:], [
            "Judgements inside commands: 4 (1 from the record and 1 by a rule, saving about 1.2 s; 2 by the student, "
            "taking 1.2 s)",
            "Set by you with trace: 2, and 1 taken back",
            "Calls to the teacher: 3, of which 1 gave no answer (1 by delegate, 1 for rules, 1 by commands)",
            "Needs waiting: 0"])
