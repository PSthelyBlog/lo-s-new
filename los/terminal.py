"""Line editing, for when a person is typing at the prompt.

Three things, all from Python's readline:

- History that lasts. Memory answers a line only when it is typed word for word, so getting the
  same words back is what makes a line free the second time. The lines typed at the prompt are
  kept in the state folder. Answers to the shell's questions are not lines and are left out.
- Completion with Tab: command names, a command's own parameters, paths, the shell's own words
  and what follows them, and the lines the user has settled.
- A line to correct: the shell can put a command on the input line for the user to change.

`complete` works out what could follow what has been typed and needs no terminal, so it is the
part the tests cover.
"""
import os

from . import cases, rules
from .parse import flag

KEPT = 2000     # lines of history kept from one session to the next
ALONE = ("wrong", "needs", "stats", "exit")                             # the shell's words that stand alone
TAKING = ("help", "means", "forget", "delegate", "trace", "rule", "improve")    # and those that take more


def complete(table, before, text):
    """What `text`, the word being typed, could become. `before` is the line up to that word.
    Each candidate takes the place of `text`, and ends with a space when more is to follow."""
    words = before.split()
    if words and words[0] == "means":       # what follows means is a command line
        words = words[1:]
        if not words:
            return _starting(text, [name + " " for name in table])
    elif words and words[0] in TAKING:
        return _starting(text, _after(table, words))
    elif not words or words[0] not in table:
        # Plain language so far, or nothing: a settled line that starts this way, given from the
        # word being typed on. At the start of the line a command or one of the shell's words fits too.
        typed = before + text
        lines = [line[len(before):] for line in cases.settled(table) if line.startswith(typed) and line != typed]
        first = [] if words else [name + " " for name in list(table) + list(TAKING)] + list(ALONE)
        return _starting(text, first) + sorted(lines)
    if words[0] not in table:
        return []
    command, given = table[words[0]], words[1:]
    named = given[-1][2:].replace("-", "_") if given and given[-1].startswith("--") else None
    if named in command.params and not text.startswith("--"):      # the value of a parameter
        return _paths(text) if command.params[named].path else []
    used = {word[2:].partition("=")[0].replace("-", "_") for word in given if word.startswith("--")}
    return _starting(text, [flag(name) + " " for name in command.params if name not in used])


def _after(table, words):
    """What can follow one of the shell's own words, given what follows it already."""
    word, rest = words[0], words[1:]
    judging = [name for name in table if table[name].judges]
    if word == "help":
        return [name + " " for name in list(table) + list(TAKING) + list(ALONE)]
    if word in ("forget", "delegate") and not rest:
        return [f"{number} " for number in cases.waiting()]
    if word == "improve" and not rest:
        return ["lines"]
    if word in ("rule", "trace") and not rest:
        return [name + " " for name in judging] + ["forget "] * (word == "trace")
    if word == "trace" and rest == ["forget"]:      # trace forget NUMBER: the answers of the latest run that the user set
        return [str(number) for number, case in enumerate(cases.latest_run(), 1)
                if case["question"]["value"] in cases.own(case["question"])[0]]
    if word in ("rule", "trace") and len(rest) == 1 and rest[0] in judging:
        return [name + " " for name in table[rest[0]].judges]
    if word == "trace" and len(rest) == 2 and rest[0] in judging:        # a stretch: from VALUE or up to VALUE
        return ["from ", "up to ", "forget "]
    if word == "trace" and len(rest) > 2 and rest[0] in judging and rest[2] == "forget":
        # What the user set and can take back, given from the word being typed on.
        found, typed = rules.answers(rest[0], rest[1]), "".join(word + " " for word in rest[3:])
        if not found:
            return []
        asked = {"command": rest[0], "name": rest[1], "ask": found[0], "choices": found[1]}
        yours = [f"{case['reach']} {case['question']['value']}" for case in cases.stretches(asked)] + list(cases.own(asked)[0])
        return [one[len(typed):] for one in yours if one.startswith(typed)]
    if word == "trace" and rest[0] in judging and rest[-1] == "is":      # trace COMMAND NAME VALUE is ANSWER
        found = rules.answers(rest[0], rest[1])
        return list(found[1]) if found else []
    if word == "trace" and len(rest) == 1 and rest[0].isdigit():         # trace NUMBER ANSWER
        asked = cases.latest_run()
        return list(asked[int(rest[0]) - 1]["question"]["choices"]) if 1 <= int(rest[0]) <= len(asked) else []
    return []


def _starting(text, candidates):
    return sorted(one for one in candidates if one.startswith(text))


def _paths(text):
    """The files and folders a path being typed could be. A folder ends with a slash, so that
    Tab goes on into it. A name starting with a dot is offered once the dot is typed."""
    if text == "~":
        return ["~/"]
    folder, _, start = text.rpartition("/")
    shown = folder + "/" if "/" in text else ""
    try:
        entries = sorted(os.scandir(os.path.expanduser(shown) or "."), key=lambda entry: entry.name)
    except OSError:
        return []
    # A space inside a name is written the way the shell reads one.
    return [shown + entry.name.replace(" ", "\\ ") + ("/" if entry.is_dir() else " ") for entry in entries
            if entry.name.startswith(start) and (start.startswith(".") or not entry.name.startswith("."))]


def start(table, history):
    """Turn line editing on. `table` gives the command table as it is now, and `history` is the
    file the typed lines are kept in. Returns (read, edit): `read(prompt)` reads one line and
    keeps it, and `edit(prompt, text)` reads a line that starts out as `text`."""
    import readline

    readline.set_auto_history(False)        # otherwise every y and n would be a line of history
    readline.set_history_length(KEPT)
    history.touch()
    readline.read_history_file(history)
    if readline.get_current_history_length() > KEPT:
        readline.write_history_file(history)        # which keeps the latest lines only

    found = []

    def completer(text, state):
        if state == 0:
            try:
                found[:] = complete(table(), readline.get_line_buffer()[:readline.get_begidx()], text)
            except Exception:       # a fault here must not take the prompt with it
                found[:] = []
        return found[state] if state < len(found) else None

    readline.set_completer(completer)
    readline.set_completer_delims(" \t\n")      # a word is what stands between spaces: fs.list, --sort-by, ~/a/b
    readline.parse_and_bind("bind ^I rl_complete" if "libedit" in (readline.__doc__ or "") else "tab: complete")

    def read(prompt):
        line = input(prompt)
        last = readline.get_current_history_length()
        if line.strip() and (not last or readline.get_history_item(last) != line):
            readline.add_history(line)
            readline.append_history_file(1, history)
        return line

    def edit(prompt, text):
        readline.set_startup_hook(lambda: readline.insert_text(text))
        try:
            return input(prompt)
        finally:
            readline.set_startup_hook(None)

    return read, edit
