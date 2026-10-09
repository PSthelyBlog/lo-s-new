"""The one way from a running command to a model.

A command asks the core, and the core asks here. Two things can be asked.

A judgement is a closed question: one of a few answers for one value, such as whether a
temperature is fine or worrying. It is answered from the surest source there is: an answer on
record, the user's own before the student's, then a rule if one was made and it covers the value,
and the student last. Every answer is recorded as a case with the run it was asked in, so that `trace` can show
where each came from and the user can set one themselves. The student can also be asked on
purpose about values no run produced, to see where it draws its line before a rule is made.

A question of the command's own is free text to the student or the teacher. Nothing about it is
reused. One to the teacher is a call the user counts, so they are shown it and asked first.
"""
import datetime

from . import cases, rules, state
from .models import ModelUnavailable, complete_valid
from .sandbox import Refused

# The system prompt starts with the question and the answers, and the value comes alone after it.
# The server reuses its work on what comes before the last message, and keeps apart prompts that
# differ from their first words. Measured on the student, two kinds of judgement asked in turn
# take 0.6 seconds each this way, and 1.5 with these instructions first.
JUDGE = """\
You make the judgement above for a command on the user's own machine. You are given one value. \
Reply with the allowed answer that fits that value best, judging it as it stands by what is \
usual for such a thing."""
ANSWER = """\
You are answering a question put to you through lo-s, a command line on the user's own machine. \
Answer in plain text with no markup, and briefly: a few sentences unless more is asked for."""
TEXT = {"type": "object", "additionalProperties": False, "required": ["answer"],
        "properties": {"answer": {"type": "string"}}}
ROOM = 800      # output tokens allowed for a free answer
TRIAL = "the teacher is not called while a command is being tried out"


class Minds:
    """What answers a running command that asks for a model. The shell makes one from the models
    it was set up with and its way of asking the user."""

    def __init__(self, student=None, teacher=None, confirm=None, keep=True):
        self.student, self.teacher, self.confirm = student, teacher, confirm
        self.keep = keep        # False while a command is tried out: nothing is recorded or reused

    def trial(self):
        """The same, for trying a command out: every judgement goes to the student, nothing is
        recorded, and the teacher is not called."""
        return Minds(self.student, self.teacher, keep=False)

    def judge(self, command, run, name, question, value, choices):
        """One of `choices` for `value`. Raises Refused when nobody can answer."""
        asked = {"command": command.name, "name": name, "ask": question, "choices": list(choices), "value": value}
        if self.keep:
            known = cases.judged(asked)
            if known and known["answer"] in choices:
                cases.record("judgement", asked, known["answer"], "memory", run=run, source=known["by"])
                return known["answer"]
            ruled = rules.answer(asked)
            if ruled:
                cases.record("judgement", asked, ruled, "rule", run=run)
                return ruled
        return self._student(asked, run=run)

    def sample(self, command, name, question, value, choices):
        """What the student says to a value no run has produced, asked on purpose to see where it
        draws its line. A value that has its answer on record is not asked about again. The
        answer is recorded like any other of the student's, as part of a spread and of no run."""
        asked = {"command": command.name, "name": name, "ask": question, "choices": list(choices), "value": value}
        known = cases.judged(asked)
        return known["answer"] if known else self._student(asked, spread=True)

    def _student(self, asked, **more):
        """Ask the student for one judgement and record what it says."""
        name, choices = asked["name"], asked["choices"]
        if not self.student:
            raise Refused(f"no model is set up as the student, which would judge {name}")
        schema = {"type": "object", "additionalProperties": False, "required": ["answer"],
                  "properties": {"answer": {"type": "string", "enum": list(choices)}}}
        try:
            output, meta = complete_valid(self.student, f"Question: {asked['ask']}\nAllowed answers: "
                                          f"{' | '.join(choices)}\n\n{JUDGE}", f"Value: {asked['value']}", schema)
        except ModelUnavailable as error:
            raise Refused(f"the student, which would judge {name}, did not answer ({error}). If it is the local "
                          "model, scripts/serve.sh starts it")
        except RuntimeError as error:
            raise Refused(f"the student's judgement of {name} could not be used ({error})")
        if self.keep:
            cases.record("judgement", asked, output["answer"], "student",
                         model=self.student.model, seconds=meta.get("seconds"), **more)
        return output["answer"]

    def ask(self, command, to, message):
        """The answer of the student or the teacher to a question of the command's own."""
        model = self.student if to == "student" else self.teacher
        if not model:
            raise Refused(f"no model is set up as the {to}")
        if to == "teacher":
            if not self.keep:
                raise Refused(TRIAL)
            shown = " ".join(message.split())
            shown = shown if len(shown) <= 300 else f"{shown[:300]} ... ({len(message)} characters in all)"
            if not self.confirm or not self.confirm(
                    f"{command.name} wants to put this to {model.model}, which is one call to it:\n  {shown}\nSend it?",
                    default=False):
                raise Refused(f"the question was not sent to {model.model}, because you did not say yes")
        record = {"date": datetime.date.today().isoformat(), "command": command.name, "to": to, "model": model.model}
        try:
            # The teacher gets one try: asking again is another call, and that is for the user to decide.
            output, meta = complete_valid(model, ANSWER, message, TEXT, tries=1 if to == "teacher" else 3, limit=ROOM)
        except (ModelUnavailable, RuntimeError) as error:
            if self.keep:
                state.append("asks", {**record, "failed": str(error)})
            raise Refused(f"the {to} gave no answer ({error})")
        if self.keep:
            state.append("asks", {**record, "seconds": meta.get("seconds")})
        return output["answer"]
