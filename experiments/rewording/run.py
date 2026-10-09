#!/usr/bin/env python3
"""Rewording experiment: when a user says a line they have settled in other words, does the
student still give the command and the values they accepted? And can likeness of wording tell
such a line from the same request with another value?

The lines are a user's own. They are read from where they are (--data), and the answers are
written beside them, so neither is kept here. The student is asked the way the shell asks
(los/route.py), with the shell's own command table and the server's prompt cache on. Every
answer is recorded once; running again fills gaps only.

  run.py --data FILE ask       put every line in the file to the student
  run.py --data FILE report    the counts; with --lines, every line that went another way too

FILE is a JSON list with one entry for each settled line:

  {"line": the line as the user settled it, "command": NAME, "args": {...},
   "reworded": [the same request with the same values, in other words, ...],
   "other_language": [the same again in another language, ...],
   "changed": [{"line": the same request with another value, "args": {...}}, ...]}
"""
import argparse
import json
import os
import pathlib
import statistics
import sys
import tomllib

HERE = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent.parent))
from los import plugins, route, sandbox, state  # noqa: E402
from los.models import provider  # noqa: E402
from los.parse import render  # noqa: E402

KINDS = {"settled": "The settled lines themselves, asked as if new",
         "reworded": "The same request and values, in other words",
         "other_language": "The same again, in another language",
         "changed": "The same request with another value"}
LEVELS = (0.2, 0.3, 0.4, 0.5, 0.6)      # how alike two lines must be to count as one, tried in turn


def lines_of(data):
    """Every line to ask, as (kind, the settled line it comes from, the line, the command and
    the values that are right for it)."""
    for entry in json.loads(data.read_text()):
        right = (entry["command"], entry["args"])
        yield "settled", entry["line"], entry["line"], right
        for kind in ("reworded", "other_language"):
            for line in entry.get(kind, []):
                yield kind, entry["line"], line, right
        for other in entry.get("changed", []):
            yield "changed", entry["line"], other["line"], (other.get("command", entry["command"]), other["args"])


def answers_of(data):
    path = data.with_suffix(".answers.jsonl")
    return {row["line"]: row for row in map(json.loads, path.read_text().splitlines())} if path.exists() else {}


def ask(model, table, data):
    done = answers_of(data)
    with data.with_suffix(".answers.jsonl").open("a") as out:
        for _, _, line, _ in lines_of(data):
            if line in done:
                continue
            try:
                choice = route.ask(model, table, line)
                row = {"line": line, "command": choice.command, "args": choice.args, "seconds": choice.meta.get("seconds")}
            except RuntimeError as error:       # an answer that fits no command counts as going nowhere
                row = {"line": line, "command": None, "args": {}, "failed": str(error)}
            done[line] = row
            out.write(json.dumps(row) + "\n")
            out.flush()
    print(f"{len(done)} answers", flush=True)


def as_run(table, command, args):
    """A command and its values as they would run: defaults filled in and paths absolute, which is
    what the shell shows. Other values are compared without regard to capitals or spacing."""
    if command not in table:
        return command, args
    full = sandbox.complete(table[command], args)
    return command, {name: value if table[command].params[name].path else " ".join(value.lower().split())
                     for name, value in full.items()}


def trigrams(text):
    text = f"  {' '.join(text.lower().split())}  "
    return {text[i:i + 3] for i in range(len(text) - 2)}


def likeness(one, other):
    """The measure lo-s already has (los/cases.py): shared character trigrams. No model in it."""
    mine, theirs = trigrams(one), trigrams(other)
    return len(mine & theirs) / len(mine | theirs)


def report(table, data, show):
    asked, answers = list(lines_of(data)), answers_of(data)
    missing = [line for _, _, line, _ in asked if line not in answers]
    if missing:
        sys.exit(f"{len(missing)} lines have no answer yet. Run: run.py --data FILE ask")
    settled = {line: as_run(table, *right) for kind, _, line, right in asked if kind == "settled"}

    print("| | Lines | Same command | Same command and values | No command | Another command | Median seconds |")
    print("|---|---|---|---|---|---|---|")
    astray = []
    for kind, title in KINDS.items():
        mine = [(line, right) for one, _, line, right in asked if one == kind]
        if not mine:
            continue
        got = [(line, right, answers[line]) for line, right in mine]
        command = sum(answer["command"] == right[0] for _, right, answer in got)
        whole = sum(as_run(table, answer["command"], answer["args"]) == as_run(table, *right) for _, right, answer in got)
        none = sum(answer["command"] is None for _, _, answer in got)
        took = [answer["seconds"] for _, _, answer in got if answer.get("seconds")]
        print(f"| {title} | {len(got)} | {command} | {whole} | {none} | {len(got) - command - none} | "
              f"{statistics.median(took):.2f} |")
        astray += [(kind, line, right, answer) for line, right, answer in got
                   if as_run(table, answer["command"], answer["args"]) != as_run(table, *right)]

    # Could likeness of wording stand in for the student? A line is taken for the settled line it
    # is most like, when the two are at least so much alike. That is right when the settled line's
    # answer is the right one for it, and a wrong merge when it is not.
    print("\n| Lines at least this much alike are taken as one | " + " | ".join(f"{level:.1f}" for level in LEVELS) + " |")
    print("|---|" + "---|" * len(LEVELS))
    rows = {"Rewordings answered rightly from a settled line": [], "Rewordings given another line's answer": [],
            "Lines with another value given the old value": []}
    for level in LEVELS:
        found = wrong = merged = 0
        for kind, _, line, right in asked:
            if kind == "settled":
                continue
            near = max(settled, key=lambda other: likeness(line, other))
            if likeness(line, near) < level:
                continue
            same = settled[near] == as_run(table, *right)
            found += same and kind != "changed"
            wrong += not same and kind != "changed"
            merged += not same and kind == "changed"
        for row, number in zip(rows.values(), (found, wrong, merged)):
            row.append(str(number))
    total = {kind: sum(one == kind for one, _, _, _ in asked) for kind in KINDS}
    for (title, cells), among in zip(rows.items(), (total["reworded"] + total["other_language"],) * 2 + (total["changed"],)):
        print(f"| {title}, of {among} | " + " | ".join(cells) + " |")

    if show:
        print()
        for kind, line, right, answer in astray:
            went = render(answer["command"], answer["args"]) if answer["command"] else "no command"
            print(f"- [{kind}] {line!r}: {went}, where {render(*right)} was right")


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("what", choices=["ask", "report"])
    parser.add_argument("--data", type=pathlib.Path, required=True, help="the file of settled lines and their rewordings")
    parser.add_argument("--lines", action="store_true", help="in the report, list the lines that went another way")
    parser.add_argument("--url", help="the student's server, if not the one in los.toml")
    opts = parser.parse_args()
    table, problems = plugins.load(pathlib.Path(os.environ.get("LOS_PLUGINS", state.ROOT / "plugins")))
    for problem in problems:
        print(problem)
    if opts.what == "report":
        return report(table, opts.data, opts.lines)
    settings = tomllib.loads(pathlib.Path(os.environ.get("LOS_CONFIG", state.ROOT / "los.toml")).read_text())
    student = settings["providers"][settings["roles"]["student"]]
    ask(provider({**student, "url": opts.url} if opts.url else student), table, opts.data)


if __name__ == "__main__":
    main()
