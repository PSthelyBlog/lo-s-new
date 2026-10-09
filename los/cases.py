"""The record of answered questions, and the queue of lines nothing could answer.

A case is one answered question: what was asked, the answer, who gave it and what the user said
about it. Cases are appended to `state/cases.jsonl` and never changed. A case the user accepted
is a fact: the same question is answered from it and no model is asked. Everything else a case
holds is kept for what can be built from it later. There are two kinds of question.

    kind        line: which command a typed line means
    question    the line
    answer      {"command": NAME or null, "args": {...}}
    by          student or teacher, memory when an accepted case answered, or user for what the
                user said themselves: a choice taken back, or what a line means. Two more take
                their answer from what the user settled for another line, named in `from`:
                correction, what the user put in place of the very answer the student gave, and
                likeness, the command of the line most like one the student found nothing for
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

# How alike a line must be to a settled one for that line's command to be offered. Of the few
# lines tried (experiments/rewording/), six of the seven that a settled line could answer were
# above it, and five of the six that needed a new command were below.
ALIKE = 0.25


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


def likeness(one, other):
    """How alike two lines are, from 0 to 1: the share of their character trigrams that both
    have. A plain measure, with no model in it."""
    mine, theirs = _trigrams(one), _trigrams(other)
    return len(mine & theirs) / len(mine | theirs)


def nearest(lines, to, count=3):
    """The lines most like any of the lines in `to`, nearest first."""
    return sorted(lines, key=lambda line: -max((likeness(line, other) for other in to), default=0))[:count]


def corrected(line, answer, table):
    """What the user put in place of this very answer when a model gave it for another line: the
    case in which they said what that line means. A student that gives a wrong value for one
    wording gives it for the next, and the user's correction is likely to be right there too.

    Nothing is returned when the user accepted the answer as it stands for some line, or took
    the correction back for this one. A correction counts for as long as its line is settled that
    way. Of several, it is the one made for the line most like this one."""
    standing, given, found = settled(table), {}, {}
    for case in state.read("cases"):
        if case["kind"] == "line" and case["by"] in ("student", "teacher"):
            given[case["question"]] = case["answer"]
        elif case["kind"] == "line" and (case["by"], case["verdict"]) == ("user", "accepted") \
                and given.get(case["question"]) == answer != case["answer"]:
            found[case["question"]] = case
    if any(case["answer"] == answer for case in standing.values()):
        return None
    found = [case for other, case in found.items() if standing.get(other, {}).get("answer") == case["answer"]
             and not taken_back(line, case["answer"])]
    return max(found, key=lambda case: likeness(line, case["question"]), default=None)


def alike(line, table):
    """The case that settled the line most like this one, when the two are at least ALIKE. It is
    for a line the student finds no command for: nothing else is on offer then, so that line's
    command is worth showing. An answer the user took back for this line is passed over."""
    lines = settled(table)
    for other in sorted(lines, key=lambda other: -likeness(line, other)):
        if likeness(line, other) < ALIKE:
            break
        if not taken_back(line, lines[other]["answer"]):
            return lines[other]
    return None


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
