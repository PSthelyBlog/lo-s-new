#!/usr/bin/env python3
"""Routing experiment: how long the student takes over a line as the command table grows, and
whether showing it the user's nearest confirmed lines makes its choice better or steadier.

The lines, the command tables and the teacher's labels are those of the first build's dispatch
experiment, read from where they are (--data). The student is asked the way the shell asks
(los/route.py), with the server's prompt cache on. Every answer is recorded once in
results/TAG.jsonl; running again fills gaps only.

  run.py --data DIR plain       the 100 lines at 10, 50 and 200 commands, as the shell asks them
  run.py --data DIR nearest     the same, each line shown with its 3 nearest labelled lines
  run.py --data DIR steady      50 commands plus one more that some other line is meant for, six
                                times over, asked both ways
  run.py --data DIR reversed    the 100 lines at 50 commands again, plainly, last line first: how
                                much the answers move when nothing but the order changes
  run.py --data DIR report
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
from los import route, state  # noqa: E402
from los.models import complete_valid, provider  # noqa: E402
from los.parse import render  # noqa: E402
from los.plugins import Command, Param  # noqa: E402

RESULTS = HERE / "results"
SIZES = (10, 50, 200)
SHOWN = 3       # confirmed lines shown as examples
ADDED = 6       # tables in the steadiness run, each with one more command than the 50
EXAMPLES = "Lines this user typed before, and the command they accepted for each:\n{examples}\n\nThe line: {line}"


def rows(data):
    return [row.split("\t") for row in (data / "commands.tsv").read_text().splitlines()]


def table_of(chosen):
    return {name: Command(name, description, {param.strip(): Param() for param in (params[0].split(",") if params else [])})
            for name, description, *params in chosen}


def lines_of(data):
    return [tuple(row.split("\t")[:2]) for row in (data / "lines.tsv").read_text().splitlines()]


def teacher(data, size):
    """The teacher's answer for each line at one table size, as id -> (command or None, args)."""
    labels = {}
    for row in (data / "results" / f"teacher-opus-5-5-{size}.jsonl").read_text().splitlines():
        label = json.loads(row)
        labels[label["id"]] = (None if label["command"] == "none" else label["command"],
                               {arg["name"]: arg["value"] for arg in label["args"]})
    return labels


def trigrams(text):
    text = f"  {' '.join(text.lower().split())}  "
    return {text[i:i + 3] for i in range(len(text) - 2)}


def nearest(line, pool, count=SHOWN):
    """The lines of the pool that share the most character trigrams with this one, nearest first.
    `pool` holds (id, line) pairs. No model is involved."""
    mine = trigrams(line)

    def likeness(other):
        theirs = trigrams(other[1])
        return len(mine & theirs) / len(mine | theirs)

    return sorted(pool, key=lambda other: (-likeness(other), int(other[0])))[:count]


def read(tag):
    path = RESULTS / f"{tag}.jsonl"
    return {row["id"]: row for row in map(json.loads, path.read_text().splitlines())} if path.exists() else {}


def run(model, tag, table, lines, labels=None):
    """Ask every line not yet recorded under this tag. With `labels`, each line is shown with
    its nearest other lines that have a command there, as lines the user confirmed."""
    done, system, schema = read(tag), route.system_prompt(table), route.schema(table)
    with (RESULTS / f"{tag}.jsonl").open("a") as out:
        for number, line in lines:
            if number in done:
                continue
            user, shown = line, []
            if labels is not None:
                pool = [(other, text) for other, text in lines if other != number and labels[other][0]]
                shown = nearest(line, pool)
                user = EXAMPLES.format(line=line, examples="\n".join(
                    f"- {text} => {render(*labels[other])}" for other, text in shown))
            output, meta = complete_valid(model, system, user, schema)
            call = output["call"]
            out.write(json.dumps({"id": number, "line": line, "command": call["command"], "args": call.get("args", {}),
                                  "examples": [other for other, _ in shown], **meta}) + "\n")
            out.flush()
    print(f"{tag}: {len(read(tag))} answers", flush=True)


def added(data):
    """Commands beyond the first 50 that the teacher chose for some line at 200 commands: each is
    what one line is meant for, and a near miss for the lines around it."""
    wanted = {command for command, _ in teacher(data, 200).values()}
    return [row for row in rows(data)[50:] if row[0] in wanted][:ADDED]


def lowered(args):
    return {name: value.lower() for name, value in args.items() if value.strip()}


def same(answers, labels, among):
    return sum(answers[number]["command"] == (labels[number][0] or "none") for number in among)


def report(data):
    lines = lines_of(data)
    ids = [number for number, _ in lines]
    print("Seconds per line, prompt cache on, lines asked one after another\n")
    print("| Commands in table | 10 | 50 | 200 |\n|---|---|---|---|")
    table = {size: read(f"plain-{size}") for size in SIZES}
    if all(len(table[size]) == len(ids) for size in SIZES):
        def row(title, value):
            print(f"| {title} | " + " | ".join(value(list(table[size].values()), size) for size in SIZES) + " |")
        row("Median seconds per line", lambda a, _: f"{statistics.median(r['seconds'] for r in a):.2f}")
        row("Mean seconds per line", lambda a, _: f"{statistics.mean(r['seconds'] for r in a):.2f}")
        row("Slowest line", lambda a, _: f"{max(r['seconds'] for r in a[1:]):.2f}")
        row("First line after the table changed", lambda a, _: f"{a[0]['seconds']:.2f}")
        row("Prompt tokens", lambda a, _: f"{statistics.median(r['prompt_tokens'] for r in a):.0f}")
        row("Of those, worked out again (median)", lambda a, _: f"{statistics.median(r['prompt_tokens_evaluated'] for r in a[1:]):.0f}")
        row("Same command as the teacher", lambda a, size: f"{same(table[size], teacher(data, size), ids)}%")

    print("\nNearest confirmed lines shown as examples, against the same lines asked plainly\n")
    print("| Commands in table | 10 | 50 | 200 |\n|---|---|---|---|")
    for title, tag in (("asked plainly", "plain"), ("with nearest lines", "nearest")):
        got = {size: read(f"{tag}-{size}") for size in SIZES}
        if not all(len(got[size]) == len(ids) for size in SIZES):
            continue
        cells = {"Same command as the teacher": [], "Same command and the same parameters": [],
                 "Teacher picked a command: student picked another": [],
                 "Teacher picked a command: student said none": [], "Teacher said none: student ran a command": [],
                 "Median seconds per line": []}
        for size in SIZES:
            labels, answers = teacher(data, size), got[size]
            commands = [number for number in ids if labels[number][0]]
            nones = [number for number in ids if not labels[number][0]]
            cells["Same command as the teacher"].append(f"{same(answers, labels, ids)}%")
            cells["Same command and the same parameters"].append(
                f"{sum(answers[n]['command'] == labels[n][0] and lowered(answers[n]['args']) == lowered(labels[n][1]) for n in commands)}"
                f" of {len(commands)}")
            cells["Teacher picked a command: student picked another"].append(
                f"{sum(answers[n]['command'] not in ('none', labels[n][0]) for n in commands)} of {len(commands)}")
            cells["Teacher picked a command: student said none"].append(
                f"{sum(answers[n]['command'] == 'none' for n in commands)} of {len(commands)}")
            cells["Teacher said none: student ran a command"].append(
                f"{sum(answers[n]['command'] != 'none' for n in nones)} of {len(nones)}")
            cells["Median seconds per line"].append(f"{statistics.median(r['seconds'] for r in answers.values()):.2f}")
        for name, values in cells.items():
            print(f"| {name}, {title} | " + " | ".join(values) + " |")

    forward, backward = read("plain-50"), read("reversed-50")
    if len(forward) == len(backward) == len(ids):
        differ = [number for number in ids if forward[number]["command"] != backward[number]["command"]]
        values = [number for number in ids if number not in differ
                  and lowered(forward[number]["args"]) != lowered(backward[number]["args"])]
        print(f"\nThe same lines at 50 commands, asked plainly in reverse order: {len(differ)} of {len(ids)} got "
              f"another command and {len(values)} the same command with other parameters; "
              f"{same(backward, teacher(data, 50), ids)}% got the teacher's command")
        for number in values:
            print(f"- {forward[number]['line']!r}: {forward[number]['args']}, then {backward[number]['args']}")
        for number in differ:
            print(f"- {forward[number]['line']!r}: {forward[number]['command']}, then {backward[number]['command']}")

    at50, at200 = teacher(data, 50), teacher(data, 200)
    settled = [number for number in ids if at50[number][0] == at200[number][0]]
    found = {}
    for tag in ("plain", "nearest"):
        tables = [read(f"{tag}-50")] + [read(f"steady-{tag}-{index}") for index in range(1, ADDED + 1)]
        if not all(len(answers) == len(ids) for answers in tables):
            return
        moved = [number for number in settled if len({answers[number]["command"] for answers in tables}) > 1]
        right = sum(same(answers, at50, settled) for answers in tables)
        found[tag] = (len(moved), right, len(settled) * len(tables), moved)
    print(f"\nSteadiness: {len(settled)} lines whose right command is the same at 50 and at 200 commands, asked "
          f"with the 50 and again with each of {ADDED} tables of 51 ({', '.join(row[0] for row in added(data))})\n")
    print("| | asked plainly | with nearest lines |\n|---|---|---|")
    print(f"| Lines that got more than one command | {found['plain'][0]} of {len(settled)} | {found['nearest'][0]} of {len(settled)} |")
    print(f"| Answers that are the teacher's command | {found['plain'][1]} of {found['plain'][2]} | "
          f"{found['nearest'][1]} of {found['nearest'][2]} |")
    for tag in ("plain", "nearest"):
        print(f"\nLines that moved, {'asked plainly' if tag == 'plain' else 'with nearest lines'}:")
        tables = [read(f"{tag}-50")] + [read(f"steady-{tag}-{index}") for index in range(1, ADDED + 1)]
        for number in found[tag][3]:
            print(f"- {tables[0][number]['line']!r} (teacher: {at50[number][0] or 'none'}): "
                  + ", ".join(answers[number]["command"] for answers in tables))


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("what", choices=["plain", "nearest", "steady", "reversed", "report"])
    parser.add_argument("--data", type=pathlib.Path, required=True, help="the first build's experiments/dispatch folder")
    parser.add_argument("--url", help="the student's server, if not the one in los.toml")
    opts = parser.parse_args()
    if opts.what == "report":
        return report(opts.data)

    settings = tomllib.loads(pathlib.Path(os.environ.get("LOS_CONFIG", state.ROOT / "los.toml")).read_text())
    student = settings["providers"][settings["roles"]["student"]]
    model = provider({**student, "url": opts.url} if opts.url else student)
    RESULTS.mkdir(exist_ok=True)
    lines, every = lines_of(opts.data), rows(opts.data)
    if opts.what == "reversed":
        run(model, "reversed-50", table_of(every[:50]), lines[::-1])
    elif opts.what == "steady":
        for index, extra in enumerate(added(opts.data), 1):
            table = table_of(every[:50] + [extra])
            run(model, f"steady-plain-{index}", table, lines)
            run(model, f"steady-nearest-{index}", table, lines, teacher(opts.data, 50))
    else:
        for size in SIZES:
            run(model, f"{opts.what}-{size}", table_of(every[:size]), lines,
                teacher(opts.data, size) if opts.what == "nearest" else None)


if __name__ == "__main__":
    main()
