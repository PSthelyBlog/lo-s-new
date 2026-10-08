"""Rules: a judgement's recorded cases turned into a small function.

When a command has asked for the same judgement on enough different values, the record of what
was judged and how can be handed to the teacher, which writes a pure function giving the same
answers. Once the user approves it, that judgement asks the rule before the student, and the
student only when the rule returns nothing.

Nothing here trusts the function. It is code a model wrote, so it runs in a sandbox that holds
nothing, once for each value. Before the user is asked, it is tried on every recorded case,
including cases the teacher was never shown. A rule may leave a held-back case to the student by
returning None, which is always safe. It may never contradict one.

An answer on record for an exact value is used before the rule is asked, so a rule only ever
decides values that were not seen before, and an answer the user sets later comes first.
"""
import ast
import datetime
import json
import re

from . import cases, sandbox, state
from .models import complete_valid

MINIMUM = 6     # different values on record before a rule is attempted

BRIEF = """\
You are the teacher of lo-s, a personal command line. One of its commands needs a judgement that \
no code makes: one of a few allowed answers for a value. A small local model, the student, has \
been making it, and lo-s has recorded each value and the answer given. An answer marked as set \
by the user is theirs and is a fact. Write a rule, a small pure Python function that gives the \
same answers, so that lo-s can ask the rule in place of the student.

You are given the command, the question, the allowed answers and the recorded cases. Some \
recorded cases are held back and your rule is tested on those too, so write the rule the cases \
point to and not a table of the cases.

The function is:  def rule(value):
- value is the text that was judged, exactly as in the cases.
- It returns one of the allowed answers, as a string. It returns None whenever the value is not \
one the rule clearly covers: a value in a form the cases do not show, or one in a range where \
the cases do not settle the answer. lo-s then asks the student as before, so None is always safe \
and a wrong answer is not.
- It runs in a sandbox that holds nothing: no file, no network and nothing to call. It may use \
the standard library. It is a pure function of its argument.
- Keep it short and plain. A person reads it before it is used.

Also judge the recorded answers themselves. In reason, say in two or three plain sentences where \
the answers draw the line and whether that looks sensible for the question. If the answers \
contradict the question or each other too much for any rule, decline and say why.
"""

TEXT = {"type": "string"}
SCHEMA = {"type": "object", "additionalProperties": False, "required": ["decision", "reason"],
          "properties": {"decision": {"type": "string", "enum": ["write", "decline"]}, "reason": TEXT, "code": TEXT}}


class Unsuitable(Exception):
    """This judgement's record cannot become a rule yet. The message says why."""


def _natural(text):
    """A sort key that puts 9 °C before 10 °C."""
    return [int(part) if part.isdigit() else part for part in re.split(r"(\d+)", text)]


def recorded(command, name):
    """What is on record for one judgement: (the question, the allowed answers, one (value, answer,
    who gave it) per value, in the order of the values). The answer for a value is the one the
    user set if they set one, otherwise what the student said. Only cases asked the way the
    command asks now count: under another question they would be answers to something else."""
    asked = [case for case in cases.judgements(command, name) if case["by"] in ("user", "student")]
    if not asked:
        raise Unsuitable("nothing is on record for it yet")
    question, choices = asked[-1]["question"]["ask"], asked[-1]["question"]["choices"]
    found = {}
    for case in asked:
        value = case["question"]["value"]
        if (case["question"]["ask"], case["question"]["choices"]) == (question, choices) \
                and (case["by"] == "user" or value not in found or found[value][2] != "user"):
            found[value] = (value, case["answer"], case["by"])
    listed = sorted(found.values(), key=lambda one: _natural(one[0]))
    if len(listed) < MINIMUM:
        raise Unsuitable(f"only {len(listed)} different value(s) are on record for it, and a rule needs {MINIMUM}")
    if len({answer for _, answer, _ in listed}) < 2:
        raise Unsuitable("every recorded answer is the same, so there is no line for a rule to draw")
    return question, choices, listed


def split(listed):
    """(cases the teacher is shown, cases held back to test the rule). About a quarter are held
    back, spread over the values. An answer the user set is always shown."""
    held = [case for index, case in enumerate(listed) if index % 4 == 2 and case[2] != "user"]
    shown = [case for case in listed if case not in held]
    if len({answer for _, answer, _ in shown}) < 2:
        return listed, []
    return shown, held


def ask(teacher, command, name, question, choices, shown, earlier=None):
    """One call to the teacher for a rule. `earlier` is a rule of its own and what was found wrong
    with it, when it is asked to put that right. Returns (its answer, what the call took)."""
    lines = "\n".join(f"{json.dumps(value, ensure_ascii=False)} => {answer}" + ("   (set by the user)" if who == "user" else "")
                      for value, answer, who in shown)
    user = (f"Command: {command.name}, which is described as: {command.description}\nJudgement: {name}\n"
            f"Question: {question}\nAllowed answers: {' | '.join(choices)}\n\nRecorded cases:\n{lines}")
    if earlier:
        code, failures = earlier
        user += ("\n\nYou wrote this rule for it:\n" + code.rstrip() + "\n\nlo-s tried it, and this is what went wrong:\n"
                 + "\n".join(f"- {failure}" for failure in failures) + "\n\nGive the whole rule again with that put right.")
    # One try: asking again is another call, and that is for the user to decide.
    output, meta = complete_valid(teacher, BRIEF, user, SCHEMA, tries=1)
    if output["decision"] == "write" and not output.get("code", "").strip():
        raise RuntimeError("it chose to write a rule and returned none")
    return output, meta


def check(code):
    """Read a rule without running it. Returns the reasons it cannot be one."""
    try:
        tree = ast.parse(code)
    except SyntaxError as error:
        return [f"the code does not parse: {error.msg} on line {error.lineno}"]
    entry = next((node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "rule"), None)
    if entry is None:
        return ["the code does not define rule"]
    args = entry.args
    if [arg.arg for arg in args.args] != ["value"] or args.posonlyargs or args.kwonlyargs or args.vararg or args.kwarg:
        return ["rule must take exactly one argument, named value"]
    return []


def apply(code, value):
    """What a rule says for one value, run in a sandbox that holds nothing: (its answer, ""), the
    answer being None when it leaves the value alone, or (None, how it went wrong)."""
    result = sandbox.call(code, "rule", {"value": value}, "rule.py")
    if result.broke:
        return None, f"an error ({result.text.splitlines()[-1] if result.text else 'it stopped'})"
    if not result.ok:
        return None, f"an error ({result.text})"
    return result.text or None, ""


def failures(code, shown, held=()):
    """What the rule gets wrong, as sentences, and how many held-back cases it answered.

    It must give the recorded answer for every case the teacher was shown. For a held-back case
    it may give the recorded answer or None, which leaves the case to the student."""
    wrong, answered = [], 0
    for (value, answer, _), may_abstain in [(case, False) for case in shown] + [(case, True) for case in held]:
        got, fault = apply(code, value)
        if got is None and may_abstain and not fault:
            continue
        if fault or got != answer:
            wrong.append(f"{json.dumps(value, ensure_ascii=False)} should give {answer!r}, and the rule gives {fault or repr(got)}")
        else:
            answered += may_abstain
    return wrong, answered


def install(command, name, question, choices, code, teacher, count):
    """Keep an approved rule. Returns the file it is in."""
    folder = state.directory() / "rules"
    folder.mkdir(exist_ok=True)
    path = folder / f"{command}.{name}.py"
    path.write_text(code.rstrip() + "\n")
    state.append("rules", {"command": command, "name": name, "ask": question, "choices": choices, "file": path.name,
                           "cases": count, "date": datetime.date.today().isoformat(),
                           "written_by": teacher.model, "provider": teacher.provider})
    return path


def installed():
    """The rule in force for each (command, judgement): the latest one whose file still exists.
    Deleting the file removes the rule."""
    current = {}
    for record in state.read("rules"):
        if (state.directory() / "rules" / record["file"]).exists():
            current[(record["command"], record["name"])] = record
    return current


def answer(asked):
    """What an installed rule says for a judgement: one of its answers, or None when there is no
    rule for the question as the command asks it now, the rule leaves the value alone, or it fails."""
    record = installed().get((asked["command"], asked["name"]))
    if not record or (record["ask"], record["choices"]) != (asked["ask"], asked["choices"]):
        return None
    got, _ = apply((state.directory() / "rules" / record["file"]).read_text(), asked["value"])
    return got if got in asked["choices"] else None
