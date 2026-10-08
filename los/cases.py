"""The record of answered questions, and the queue of lines nothing could answer.

A case is one answered question: what was asked, the answer, who gave it and what the user said
about it. Cases are appended to `state/cases.jsonl` and never changed. A case the user accepted
is a fact: the same question is answered from it and no model is asked. Everything else a case
holds is kept for what can be built from it later. There are two kinds of question.

    kind        line: which command a typed line means
    question    the line
    answer      {"command": NAME or null, "args": {...}}
    by          student or teacher, memory when an accepted case answered, or user for what the
                user said themselves: a choice taken back, or what a line means
    verdict     accepted, declined (it may be right and was not wanted), wrong, or empty

    kind        judgement: what a named judgement inside a command comes to for one value
    question    {"command": NAME, "name": ..., "ask": the question, "choices": [...], "value": ...}
    answer      one of the choices
    by          student, rule, memory when a recorded answer was used again, or user for an
                answer the user set themselves
    run         the run of the command it was asked in; a user's answer belongs to no run, and
                neither does one the student gave when it was asked on purpose (spread: true)
"""
import datetime

from . import state


def record(kind, question, answer, by, verdict="", **more):
    state.append("cases", {"date": datetime.date.today().isoformat(), "kind": kind, "question": question,
                           "answer": answer, "by": by, "verdict": verdict, **more})


def settled(table):
    """Every line the user has accepted a command for and not taken back since, as line -> the
    case that settled it, as long as that command still exists with those parameters. Which other
    commands are installed makes no difference."""
    lines = {}
    for case in state.read("cases"):
        if case["kind"] == "line" and case["verdict"] == "accepted":
            lines[case["question"]] = case
        elif case["kind"] == "line" and case["verdict"] == "wrong":
            lines.pop(case["question"], None)
    return {line: case for line, case in lines.items()
            if case["answer"]["command"] in table
            and set(case["answer"]["args"]) <= set(table[case["answer"]["command"]].params)}


def remembered(line, table):
    """The case in which the user accepted a command for this exact line, if there is one."""
    return settled(table).get(line)


def taken_back(line, answer):
    """Whether the user said this answer was wrong for this exact line and has not accepted it
    since. A model that gives it again is repeating a known mistake."""
    wrong = False
    for case in state.read("cases"):
        if (case["kind"], case["question"], case["answer"]) == ("line", line, answer) and case["verdict"] in ("accepted", "wrong"):
            wrong = case["verdict"] == "wrong"
    return wrong


def judged(asked):
    """The answer on record for exactly this question and value: the one the user set if they
    set one, otherwise what the student said. Returns that case, or nothing.

    What a rule answered is not a case to answer from. It is worked out again each time, so that
    removing a rule removes its answers with it."""
    found = None
    for case in state.read("cases"):
        if case["kind"] == "judgement" and case["question"] == asked and case["by"] in ("user", "student") \
                and (case["by"] == "user" or not found or found["by"] != "user"):
            found = case
    return found


def judgements(command=None, name=None):
    """Every judgement case on record, or those of one command, or of one judgement in it."""
    return [case for case in state.read("cases")
            if case["kind"] == "judgement" and command in (None, case["question"]["command"])
            and name in (None, case["question"]["name"])]


def latest_run():
    """The judgements of the latest run that asked for any, in the order they were asked."""
    asked = [case for case in judgements() if case.get("run")]
    return [case for case in asked if case["run"] == asked[-1]["run"]]


def _trigrams(text):
    text = f"  {' '.join(text.lower().split())}  "
    return {text[i:i + 3] for i in range(len(text) - 2)}


def nearest(lines, to, count=3):
    """The lines that share the most character trigrams with any of the lines in `to`, nearest
    first. A plain measure of likeness, with no model in it."""
    def likeness(line):
        mine = _trigrams(line)
        return max((len(mine & _trigrams(other)) / len(mine | _trigrams(other)) for other in to), default=0)

    return sorted(lines, key=lambda line: -likeness(line))[:count]


def queue(line, by):
    """Add a line to the queue of needs, unless it is waiting there already. Returns its number,
    which it keeps for good."""
    for number, need in waiting().items():
        if need["line"] == line:
            return number
    number = sum("line" in entry for entry in state.read("needs")) + 1
    state.append("needs", {"number": number, "date": datetime.date.today().isoformat(), "line": line, "by": by})
    return number


def teacher_said():
    """The kind of answer the teacher last gave to each thing it was asked through delegate:
    run, write, ask or cannot, by the words it was asked about."""
    return {call["words"]: call["answer"]["answer"] for call in state.read("delegations") if "answer" in call}


def drop(number):
    state.append("needs", {"dropped": number, "date": datetime.date.today().isoformat()})


def waiting():
    """The needs still queued, by number."""
    needs = {}
    for entry in state.read("needs"):
        if "line" in entry:
            needs[entry["number"]] = entry
        else:
            needs.pop(entry["dropped"], None)
    return needs
