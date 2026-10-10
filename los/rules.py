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
decides values that were not seen before, and an answer the user sets later comes first. So does
one they set for a whole stretch of values: where the user has said where a line is, the rule is
not asked.

A command's own runs may never show where the line is: a machine that stays cool only ever has
"fine" on record. When the manifest says between which numbers a value lies, the student can be
asked about values spread over that range first, which is free.
"""
import ast
import datetime
import json
import re

from . import cases, sandbox, state
from .cases import varying
from .models import complete_valid
from .parse import count

MINIMUM = 6     # different values on record before a rule is attempted
COARSE, FINER = 9, 8    # values asked evenly over a range, and then at most this many more where the answer changes

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


def answers(command, name, edges=False):
    """What is on record for one judgement: (the question, the allowed answers, one (value, answer,
    who gave it) per value, in the order of the values), or nothing when no answer is on record.
    The values are those that came up: what the student was asked, what a run met and had
    answered from the record, and what the user set an answer for by itself. The answer for a
    value is the one the user set, for that value or for a stretch it lies in, and otherwise what
    the student said. What the user took back is as if never set. Only cases asked the way the
    command asks now count: under another question they would be answers to something else.

    With `edges`, as for a rule, the value each stretch of the user's starts at is listed as
    well, and the value next to it on the other side when the user settled that one too. Those
    two are what shows a rule exactly where the answer changes."""
    asked = [case for case in cases.judgements(command, name) if case["by"] in ("user", "student", "memory")]
    if not asked:
        return None
    same = {key: asked[-1]["question"][key] for key in ("command", "name", "ask", "choices")}
    values = [case["question"]["value"] for case in asked
              if case["by"] != "user" and cases.same_question(same, case["question"])] + list(cases.own(same, asked)[0])
    if edges:
        for stretch in cases.stretches(same, asked):
            values += [stretch["question"]["value"], beside(stretch)]
    found = {}
    for value in values:
        known = cases.judged({**same, "value": value}, asked)
        if known:
            found[value] = (value, known["answer"], known["by"])
    if not found:       # the user took back all there was
        return None
    return same["ask"], same["choices"], sorted(found.values(), key=lambda one: _natural(one[0]))


def beyond(command, name):
    """How many values a rule for a judgement is shown that never came up: those at which a
    stretch the user set starts or stops."""
    with_edges, plain = answers(command, name, edges=True), answers(command, name)
    return len(with_edges[2]) - len(plain[2]) if with_edges and plain else 0


def beside(stretch):
    """The value next to the one a stretch starts at, on the side it does not reach: one step of
    the last digit it was written with."""
    before, number, after = varying(stretch["question"]["value"])
    places = len(number.partition(".")[2])
    step = 10 ** -places if stretch["reach"] == "up to" else -10 ** -places
    return f"{before}{float(number) + step:.{places}f}{after}"


def recorded(command, name):
    """What a rule is made from, when it is enough: what is on record, and where the user's
    stretches start and stop. Otherwise Unsuitable says what is missing."""
    found = answers(command, name, edges=True)
    if not found:
        raise Unsuitable("nothing is on record for it yet")
    listed = found[2]
    if len(listed) < MINIMUM:
        raise Unsuitable(f"only {count(len(listed), 'different value')} {'is' if len(listed) == 1 else 'are'} on "
                         f"record for it, and a rule needs {MINIMUM}")
    if len({answer for _, answer, _ in listed}) < 2:
        raise Unsuitable("every answer on record is the same, so there is no line for a rule to draw")
    return found


def summary(listed):
    """The answers on record in a few lines: each stretch of values that got the same answer.
    Values that differ only in their first number are written as one, as in 20 to 82 °C."""
    def stretch(first, last):
        ends = varying(first), varying(last)
        if first == last:
            return first
        if all(ends) and (ends[0][0], ends[0][2]) == (ends[1][0], ends[1][2]):
            return f"{ends[0][0]}{ends[0][1]} to {ends[1][1]}{ends[1][2]}"
        return f"{first} to {last}"

    lines, start = [], 0
    for index in range(1, len(listed) + 1):
        if index == len(listed) or listed[index][1] != listed[start][1]:
            lines.append(f"  {stretch(listed[start][0], listed[index - 1][0])}: {listed[start][1]}")
            start = index
    return lines


def spread(ask, example, answered, low, high):
    """Find where the answers change between `low` and `high`, by asking.

    `example` is a value on record, and its first number is the part that varies. `answered`
    holds the answers already on record, by value. Values evenly spaced over the range are asked
    first, and then a few more, each halfway between two neighbours that got different answers.
    `ask(value)` gives the answer for one value. Returns the values that were asked, in order."""
    before, number, after = varying(example)
    places = len(number.partition(".")[2])          # as many digits after the point as the example has
    found, asked = {}, []                           # number -> answer

    def put(number):
        number = round(number, places)
        if number not in found:
            value = f"{before}{number:.{places}f}{after}"
            found[number] = ask(value)
            asked.append(value)

    for value, answer in answered.items():
        parts = varying(value)
        if parts and (parts[0], parts[2]) == (before, after) and low <= float(parts[1]) <= high:
            found[round(float(parts[1]), places)] = answer
    for step in range(COARSE):
        put(low + step * (high - low) / (COARSE - 1))
    for _ in range(FINER):
        ordered = sorted(found)
        gaps = [(above - below, below, above) for below, above in zip(ordered, ordered[1:])
                if found[below] != found[above] and above - below > 1.5 * 10 ** -places]
        if not gaps:
            break
        _, below, above = max(gaps)                 # the widest stretch across which the answer changes
        put((below + above) / 2)
    return asked


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


def install(command, name, question, choices, code, teacher, answered):
    """Keep an approved rule. Returns the file it is in."""
    folder = state.directory() / "rules"
    folder.mkdir(exist_ok=True)
    path = folder / f"{command}.{name}.py"
    path.write_text(code.rstrip() + "\n")
    now = datetime.datetime.now()
    state.append("rules", {"command": command, "name": name, "ask": question, "choices": choices, "file": path.name,
                           "cases": answered, "date": now.date().isoformat(), "at": now.isoformat(timespec="microseconds"),
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
