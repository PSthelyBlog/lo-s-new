"""Looking for improvements: what lo-s could do better, found in its own records.

Each finder below looks for one kind of opportunity: something the user keeps asking for and not
getting, or something a model keeps being asked that a cheaper part could answer. It says what
happened, how often and how much model time it took, and what to type. Nothing here acts. Most
of these cost a call to the teacher, so lo-s proposes and the user decides.

What cost the user something comes first: a request that went unanswered, an answer they did not
take. What only cost model time comes after it, largest first.

One finder needs more than the records. Whether a command's own example lines still reach it can
only be found out by asking the student again, so that is done when the user asks for it
(`check`). Where the lines went is noted when a command is installed and at every check, and the
finder compares the latest check with the one before.
"""
import dataclasses
import datetime
import json
import statistics

from . import cases, route, rules, state
from .parse import count, render

OFTEN = 3       # times the student is asked for a judgement before a rule is worth raising
USUAL = 1.0     # seconds a plain-language line took when it was measured, at up to 200 commands
SLOW = 2.0      # the middle of the latest lines above this is worth raising
LATEST = 20     # how many of the latest lines that looks at


@dataclasses.dataclass
class Found:
    text: str               # what was found, in a sentence or two
    do: str = ""            # what to type, when there is something to type
    cost: str = ""          # what that costs; empty when it is free
    times: int = 0          # how often it cost the user something: a request unanswered, an answer not taken
    seconds: float = 0      # the model time it took so far


def judgements(table):
    """A judgement the student keeps being asked, which a rule could answer; and a rule that the
    user has overruled, or that leaves too much to the student."""
    found, in_force = [], rules.installed()
    for command in table.values():
        for name in command.judges:
            record = cases.judgements(command.name, name)

            def stretched(question):    # a value in a stretch the user set is theirs for good: a rule adds nothing there
                return (cases.judged(question, record) or {}).get("reach")

            asked = [case for case in record if case.get("run") and case["by"] == "student" and not stretched(case["question"])]
            on_record, rule = rules.answers(command.name, name), in_force.get((command.name, name))
            typed, known = f"rule {command.name} {name}", len(on_record[2]) if on_record else 0
            if rule:
                asked = [case for case in asked if case["run"] > rule.get("at", rule["date"])]
                at = lambda value: {"command": command.name, "name": name, "ask": on_record[0], "choices": on_record[1],
                                    "value": value}
                against = sum(1 for value, answer, who in on_record[2] if who == "user" and not stretched(at(value))
                              and rules.answer(at(value)) not in (None, answer)) if on_record else 0
                if against:
                    found.append(Found(f"You set {count(against, 'answer')} for {name} in {command.name} that its rule "
                                       "gives otherwise. Yours come first for those values. A new rule made from the "
                                       "record would follow them for the values around them too.",
                                       typed, "one call to the teacher", times=against))
                elif len(asked) >= OFTEN and known > rule["cases"]:
                    found.append(Found(f"The rule for {name} in {command.name} has left it to the student "
                                       f"{count(len(asked), 'time')} since it was made, {_took(asked):.1f} s in all. "
                                       f"{known} answers are on record now, against {rule['cases']} then, so a new rule "
                                       "may cover more.", typed, "one call to the teacher", seconds=_took(asked)))
                continue
            try:
                rules.recorded(command.name, name)
                missing = ""
            except rules.Unsuitable as reason:
                missing = str(reason)
            start = (f"{command.name} has asked the student about {name} {count(len(asked), 'time')}, "
                     f"{_took(asked):.1f} s in all.")
            if asked and not missing:
                found.append(Found(f"{start} {known} answers are on record, enough for a rule to answer in its place.",
                                   typed, "one call to the teacher", seconds=_took(asked)))
            elif len(asked) >= OFTEN and name in command.ranges:
                found.append(Found(f"{start} A rule could answer in its place, but {missing}. {typed} first puts "
                                   "values from across its range to the student, which is free.",
                                   typed, "one call to the teacher, after the free part", seconds=_took(asked)))
    return found


def needs(table):
    """Something the user keeps asking for that nothing does."""
    found, said = [], cases.teacher_said()
    nothing = [case for case in state.read("cases")
               if case["kind"] == "line" and case["by"] == "student" and case["answer"]["command"] is None]
    for number, need in cases.waiting().items():
        asked = [case for case in nothing if case["question"] == need["line"]]
        if len(asked) >= 2 and said.get(need["line"]) != "cannot":      # what the teacher turned down stays as it is
            found.append(Found(f"You have asked {count(len(asked), 'time')} for something nothing does: \"{need['line']}\".",
                               f"delegate {number}", "one call to the teacher", len(asked), _took(asked)))
    return found


def lines(table):
    """A line the student keeps answering in a way the user does not take."""
    found, settled, answered = [], cases.settled(table), {}
    for case in state.read("cases"):
        if case["kind"] == "line" and case["by"] == "student" and case["answer"]["command"]:
            answered.setdefault(case["question"], []).append(case)
    for line, asked in answered.items():
        if line not in settled and len(asked) >= 2:
            last = asked[-1]["answer"]
            found.append(Found(f"The student has answered \"{line}\" {count(len(asked), 'time')} and none of its answers "
                               f"stands. The last was {render(last['command'], last['args'])}. If you know the command, "
                               "say the line again and then: means COMMAND --parameter value. That is free.",
                               f"delegate {line}", "one call to the teacher", len(asked), _took(asked)))
    return found


def examples(table):
    """A command whose own example lines no longer reach it: they did at an earlier check and
    went elsewhere at the latest one. A line that never reached its command is no news; the
    user saw that when the command was installed."""
    rows, found = state.read("line_checks"), []
    for name in dict.fromkeys(row["command"] for row in rows):
        mine = [row for row in rows if row["command"] == name]
        before = {row["line"]: row for row in mine if row["at"] != mine[-1]["at"]}     # the check before, line by line
        lost = [(row["line"], row["reached"], before[row["line"]]["date"]) for row in mine
                if row["at"] == mine[-1]["at"] and row["reached"] != name and before.get(row["line"], row)["reached"] == name]
        if name in table and lost:
            found.append(Found(f"{count(len(lost), 'example line')} of {name} no longer {'reaches' if len(lost) == 1 else 'reach'} "
                               f"it, as of {mine[-1]['date']}: " + "; ".join(
                                   f"\"{line}\" reached it on {date} and now goes to {reached or 'no command'}"
                                   for line, reached, date in lost)
                               + f". If one matters to you, say it and then: means {name} --parameter value."))
    return found


def routing(table):
    """Plain-language lines that have grown slow."""
    took = [case["seconds"] for case in state.read("cases")
            if case["kind"] == "line" and case["by"] == "student" and case.get("seconds")][-LATEST:]
    if len(took) < 5 or statistics.median(took) <= SLOW:
        return []
    middle = statistics.median(took)
    return [Found(f"A plain-language line now takes the student {middle:.1f} s (the middle one of the latest {len(took)}). "
                  f"It took about {USUAL:.0f} s when measured, with up to 200 commands. The table holds {len(table)}. "
                  "Starting the student again (scripts/serve.sh) is the first thing to try. A shortlist of commands "
                  "for a large table is not built.", seconds=(middle - USUAL) * len(took))]


FINDERS = (needs, lines, judgements, examples, routing)


def find(table):
    """Everything the finders see, what cost the user something first and then the most model time."""
    return sorted((one for finder in FINDERS for one in finder(table)), key=lambda one: (-one.times, -one.seconds))


def _took(asked):
    return sum(case.get("seconds") or 0 for case in asked)


def written(table):
    """The commands a model wrote that came with example lines, with those lines the user has not
    settled themselves. A settled line is answered from memory, so where the student would send
    it no longer matters."""
    settled, found = cases.settled(table), {}
    for command in table.values():
        proposal = command.source.parent / "proposal.json" if command.source else None
        if command.written_by and proposal and proposal.exists():
            said = [" ".join(entry["line"].split()) for entry in json.loads(proposal.read_text()).get("lines", [])]
            found[command.name] = [line for line in said if line not in settled]
    return found


def note(name, went):
    """Record where a command's example lines went, as one check: [(line, the command reached or None)]."""
    now = datetime.datetime.now()
    for line, reached in went:
        state.append("line_checks", {"at": now.isoformat(timespec="microseconds"), "date": now.date().isoformat(),
                                     "command": name, "line": line, "reached": reached})


def check(student, table):
    """Ask the student every such line again, with the table as it is now, and record where each
    went. Returns, for each command, (how many lines were asked, [(line, where it went instead,
    the earlier record of that line or None)])."""
    earlier, results = {}, {}
    for row in state.read("line_checks"):
        earlier[row["command"], row["line"]] = row
    for name, said in written(table).items():
        went = []
        for line in said:
            try:
                went.append((line, route.ask(student, table, line).command))
            except RuntimeError:        # an answer that fits no command counts as going nowhere
                went.append((line, None))
        note(name, went)
        results[name] = (len(said), [(line, reached, earlier.get((name, line))) for line, reached in went if reached != name])
    return results
