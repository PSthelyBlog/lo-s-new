"""The record of answered questions, and the queue of lines nothing could answer.

A case is one answered question: what was asked, the answer, who gave it and what the user said
about it. Cases are appended to `state/cases.jsonl` and never changed. A case the user accepted
is a fact: the same question is answered from it and no model is asked. Everything else a case
holds is kept for what can be built from it later.

    kind        line: which command a typed line means
    question    the line
    answer      {"command": NAME or null, "args": {...}}
    by          student or teacher, memory when an accepted case answered, or user for what the
                user said themselves: a choice taken back, or what a line means
    verdict     accepted, declined (it may be right and was not wanted), wrong, or empty
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
    """Add a line to the queue of needs. Returns its number, which it keeps for good."""
    number = sum("line" in entry for entry in state.read("needs")) + 1
    state.append("needs", {"number": number, "date": datetime.date.today().isoformat(), "line": line, "by": by})
    return number


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
