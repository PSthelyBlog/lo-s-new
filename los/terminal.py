"""Line editing, for when a person is typing at the prompt.

Three things, all from Python's readline:

- History that lasts. Memory answers a line only when it is typed word for word, so getting the
  same words back is what makes a line free the second time. The lines typed at the prompt are
  kept in the state folder. Answers to the shell's questions are not lines and are left out.
- Completion with Tab: command names, a command's own parameters, paths, the shell's own words
  and what follows them, and the lines the user has settled.
- A line to correct: the shell can put a command on the input line for the user to change.

And what needs only a terminal to write to: each thing said shown in its voice and broken
between words to the width of the screen, and a count of the seconds while a model is waited for.

`complete` works out what could follow what has been typed and needs no terminal, so it is the
part the tests cover.
"""
import contextlib
import os
import re
import shutil
import sys
import textwrap
import threading
import time
import unicodedata

from . import cases, rules
from .parse import flag
from .say import Aside, Exact, Fault, Warn, voices

KEPT = 2000     # lines of history kept from one session to the next
ALONE = ("wrong", "needs", "stats", "exit")                             # the shell's words that stand alone
TAKING = ("help", "means", "forget", "delegate", "trace", "rule", "improve")    # and those that take more


BOLD, DIM, RED, YELLOW, RESET = "\x1b[1m", "\x1b[2m", "\x1b[31m", "\x1b[33m", "\x1b[0m"
STYLE = {Aside: DIM, Fault: RED, Warn: YELLOW}      # lo-s speaking plainly, and what is shown exactly, have none
WIDEST = 100    # columns a line of prose takes at the most, however wide the terminal is
CHOSEN = re.compile(r"(→ .*?)((?:  \([^()]*\))?)")      # a command as it will run, and where the choice came from
HANG = re.compile(r"\s*(?:\d+\.\s+|-\s+|\S+\s{2,})?")     # what the rest of a broken line is set under


def coloured(out=None):
    """Whether to use colour and weight: at a terminal, unless NO_COLOR says not to."""
    out = out or sys.stdout
    return out.isatty() and not os.environ.get("NO_COLOR") and os.environ.get("TERM") != "dumb"


def render(text, width, colour=True):
    """What is said, as the lines a terminal shows.

    lo-s speaking is broken between words to the width, and what follows a break is set under
    the start of the text: after the number of a numbered line, or the name in a table. An aside
    is dim, a fault and a warning are coloured, and a command about to run is bold. What is shown
    exactly is left alone, whatever its length. Without `colour` only the breaking is done."""
    def paint(style, words):
        return f"{style}{words}{RESET}" if colour and style and words else words

    lines, line = [], []        # each line as the runs of words it is made of, with their voices
    for voice, words in voices(text):
        first, *rest = words.split("\n")
        line.append((voice, first))
        for more in rest:
            lines.append(line)
            line = [(voice, more)]
    rows, width = [], min(width, WIDEST)
    for line in lines + [line]:
        plain = "".join(words for _, words in line)
        chosen = CHOSEN.fullmatch(plain)
        if any(voice is Exact and words for voice, words in line):
            rows.append(plain)
        elif chosen:        # kept on one line, so that it can be copied as it is
            rows.append(paint(BOLD, chosen[1]) + paint(DIM, chosen[2]))
        else:
            under = len(HANG.match(plain).group())
            under = under if under <= width // 2 else len(plain) - len(plain.lstrip())
            marks = iter([voice for voice, words in line for char in words if not char.isspace()])
            # A word too long for a line, such as a deep path, would be set on a line by itself. Such a
            # text is left for the terminal to break, as it always was.
            fits = all(len(word) <= width - under for word in plain.split())
            for row in (textwrap.wrap(plain, width, subsequent_indent=" " * under, break_long_words=False,
                                      break_on_hyphens=False) if fits else [plain]) or [""]:
                parts, voice, run = [], str, ""
                for char in row:        # breaking moves spaces and nothing else, so the voices are counted off
                    mine = voice if char.isspace() else next(marks)
                    if mine is not voice:
                        parts.append(paint(STYLE.get(voice), run))
                        run = ""
                    voice, run = mine, run + char
                rows.append("".join(parts) + paint(STYLE.get(voice), run))
    return "\n".join(rows)


def show(text):
    """Say something at the terminal."""
    sys.stdout.write(render(text, shutil.get_terminal_size().columns, coloured()) + "\n")
    sys.stdout.flush()


def ask(question):
    """Put a question at the terminal the way things are said there, and read the answer. All of
    it but its last line is written, and that line is what the answer is typed after."""
    *above, last = render(question, shutil.get_terminal_size().columns, coloured()).split("\n")
    if above:
        sys.stdout.write("\n".join(above) + "\n")
    if "readline" in sys.modules:       # which has to be told what in a prompt takes no room on the screen
        last = re.sub(r"(\x1b\[[0-9;]*m)", "\x01\\1\x02", last)
    return input(last + (" " if question.endswith(" ") else ""))


SOON = 1.5      # seconds a wait may last before a line that is not kept is shown at all
ROOM = 14       # columns the count of seconds needs at the end of a line
SAVE, BACK, CLEAR = "\x1b7", "\x1b8", "\x1b[K"     # note where the cursor is; go back there; clear to the end of the line


def took(seconds):
    return f"{seconds:.1f} s" if seconds < 10 else f"{seconds:.0f} s"


def _columns(text):
    """How many columns the last line of a text takes on the screen."""
    return sum(2 if unicodedata.east_asian_width(char) in "WF" else 0 if unicodedata.combining(char) else 1
               for char in text.rpartition("\n")[2])


@contextlib.contextmanager
def waiting(text, kept=True, out=None, soon=SOON, every=1.0, colour=None):
    """Show that something is being waited for, and for how long: the seconds are counted in
    place for as long as the block runs.

    A line that is kept is written at once and stays as a record, with the time it took after
    it, on the same line. One that is not kept appears only when the wait lasts longer than
    `soon`, and is gone when the wait is over: a student that answers in a second leaves the
    screen as it was.

    Nothing else may be written or asked while the block runs."""
    out = out or sys.stdout
    width, started, over = shutil.get_terminal_size().columns, time.monotonic(), threading.Event()
    dim, plain = (DIM, RESET) if (coloured(out) if colour is None else colour) else ("", "")    # it is an aside
    shown = []

    def write(*parts):
        out.write("".join(parts))
        out.flush()

    if kept:
        # The text is broken between words so that its last line has room for the count. Where a
        # word too long to break leaves none, the count goes on a line of its own. The place is
        # noted once, so a text of several lines is not written again.
        text = "\n".join(row for line in text.split("\n") for row in textwrap.wrap(
            line, max(min(width, WIDEST) - ROOM, 20), break_long_words=False, break_on_hyphens=False) or [""])
        used = _columns(text) % width
        write(dim, text, plain, "" if 0 < used <= width - ROOM else "\n", SAVE)

    def count():
        if not kept and over.wait(soon):
            return
        while True:
            seconds = f"  {time.monotonic() - started:.0f} s"
            if kept:
                write(BACK, dim, seconds, plain, CLEAR)
            else:
                write("\r", dim, text[:max(width - ROOM, 0)], seconds, plain, CLEAR)
            shown.append(seconds)
            if over.wait(every):
                return

    counting = threading.Thread(target=count, daemon=True)
    counting.start()
    try:
        yield
    finally:
        over.set()
        counting.join()
        if kept:
            write(BACK, dim, f"  ({took(time.monotonic() - started)})", plain, CLEAR, "\n")
        elif shown:
            write("\r", CLEAR)


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
