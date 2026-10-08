"""The record of answered questions, and the queue of lines nothing could answer.

A case is one answered question: what was asked, the answer, who gave it and what the user said
about it. Cases are appended to `state/cases.jsonl` and never changed. A case the user accepted
is a fact: the same question is answered from it and no model is asked. Everything else a case
holds is kept for what can be built from it later.

    kind        line: which command a typed line means
    question    the line
    answer      {"command": NAME or null, "args": {...}}
    by          student, or memory when an accepted case answered, or user for a verdict given later
    verdict     accepted, declined (it may be right and was not wanted), wrong, or empty
"""
import datetime

from . import state


def record(kind, question, answer, by, verdict="", **more):
    state.append("cases", {"date": datetime.date.today().isoformat(), "kind": kind, "question": question,
                           "answer": answer, "by": by, "verdict": verdict, **more})


def remembered(line, table):
    """The case in which the user accepted a command for this exact line, if they have not taken
    it back since and the command still exists with those parameters. Which other commands are
    installed makes no difference."""
    settled = None
    for case in state.read("cases"):
        if case["kind"] == "line" and case["question"] == line:
            if case["verdict"] == "accepted":
                settled = case
            elif case["verdict"] == "wrong":
                settled = None
    if settled:
        command = table.get(settled["answer"]["command"])
        if command and set(settled["answer"]["args"]) <= set(command.params):
            return settled
    return None


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
