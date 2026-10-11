"""Line editing: what Tab offers, and history and a line to correct as a terminal sees them."""
import io
import os
import re
import select
import sys
import threading
import unittest
from unittest import mock

from los import cases, state, terminal
from los.plugins import Command, Param
from tests.helpers import Folders

try:
    import pty
    import readline  # noqa: F401
except ImportError:     # no terminal to try it in
    pty = None

TABLE = {
    "fs.list": Command("fs.list", "List a folder", {"path": Param(path="read"), "sort_by": Param()}),
    "fs.move": Command("fs.move", "Move a file", {"source": Param(path="write"), "dest": Param(path="create")}, "destructive"),
    "note.add": Command("note.add", "Add a note", {"text": Param(), "tag": Param()}, "write"),
    "sys.health": Command("sys.health", "Look at the machine", {}, judges=("memory", "temperature")),
}


def complete(before, text):
    return terminal.complete(TABLE, before, text)


class CompleteTest(Folders):
    def test_the_first_word_is_a_command_or_one_of_the_shells_own(self):
        self.assertEqual(complete("", "fs"), ["fs.list ", "fs.move "])
        self.assertEqual(complete("", "s"), ["stats", "sys.health "])       # a word that stands alone gets no space
        self.assertEqual(complete("", "tr"), ["trace "])
        self.assertEqual(len(complete("", "")), len(TABLE) + 11)

    def test_a_command_is_followed_by_its_own_parameters_once_each(self):
        self.assertEqual(complete("fs.list ", ""), ["--path ", "--sort-by "])
        self.assertEqual(complete("fs.list --path /tmp ", "--"), ["--sort-by "])
        self.assertEqual(complete("fs.list --path=/tmp ", ""), ["--sort-by "])
        self.assertEqual(complete("sys.health ", ""), [])
        self.assertEqual(complete("note.add --text ", ""), [])              # a value that names no file

    def test_a_parameter_that_names_a_file_is_followed_by_a_path(self):
        (self.files / "docs").mkdir()
        for name in ("draft.txt", ".hidden", "my notes.txt"):
            (self.files / name).write_text("")
        self.assertEqual(complete("fs.list --path ", f"{self.files}/d"), [f"{self.files}/docs/", f"{self.files}/draft.txt "])
        self.assertEqual(complete("fs.list --path ", f"{self.files}/nowhere/"), [])
        self.assertEqual(complete("fs.move --source a --dest ", f"{self.files}/doc"), [f"{self.files}/docs/"])
        self.addCleanup(os.chdir, os.getcwd())
        os.chdir(self.files)
        self.assertEqual(complete("fs.list --path ", ""), ["docs/", "draft.txt ", "my\\ notes.txt "])
        self.assertEqual(complete("fs.list --path ", "."), [".hidden "])    # offered once the dot is typed
        self.assertEqual(complete("fs.list --path ", "docs/"), [])
        with mock.patch.dict(os.environ, HOME=str(self.files)):
            self.assertEqual(complete("fs.list --path ", "~"), ["~/"])
            self.assertEqual(complete("fs.list --path ", "~/do"), ["~/docs/"])

    def test_the_shells_own_words_are_followed_by_what_they_take(self):
        self.assertEqual(complete("help ", "fs.m"), ["fs.move "])
        self.assertEqual(complete("help fs.list ", "wr"), ["wrong "])
        self.assertEqual(complete("rule ", ""), ["sys.health "])            # the one command that asks for a judgement
        self.assertEqual(complete("trace sys.health ", "t"), ["temperature "])
        self.assertEqual(complete("rule sys.health memory ", ""), [])
        self.assertEqual(complete("trace ", ""), ["forget ", "sys.health "])
        self.assertEqual(complete("trace sys.health memory ", ""), ["forget ", "from ", "up to "])      # taking back, or a stretch
        self.assertEqual(complete("trace sys.health memory ", "u"), ["up to "])
        self.assertEqual(complete("improve ", ""), ["lines"])
        self.assertEqual(complete("forget ", ""), [])
        cases.queue("order a large pizza", "user")
        self.assertEqual((complete("forget ", ""), complete("delegate ", "")), (["1 "], ["1 "]))
        self.assertEqual(complete("delegate order a large ", "p"), [])      # the user's own words are theirs to type

    def test_trace_is_followed_by_the_answers_a_judgement_allows(self):
        asked = {"command": "sys.health", "name": "memory", "ask": "Fine or worrying?", "choices": ["fine", "worrying"],
                 "value": "70% free"}
        self.assertEqual(complete("trace sys.health memory 5% free is ", ""), [])
        cases.record("judgement", asked, "fine", "student", run="one")
        self.assertEqual(complete("trace sys.health memory 5% free is ", "w"), ["worrying"])
        self.assertEqual(complete("trace 1 ", ""), ["fine", "worrying"])
        self.assertEqual(complete("trace 2 ", ""), [])

    def test_forget_is_followed_by_what_the_user_set(self):
        asked = {"command": "sys.health", "name": "memory", "ask": "Fine or worrying?", "choices": ["fine", "worrying"]}
        self.assertEqual((complete("trace sys.health memory forget ", ""), complete("trace forget ", "")), ([], []))
        for percent in (70, 20):
            cases.record("judgement", {**asked, "value": f"{percent}% free"}, "fine", "student", run="one")
        self.assertEqual((complete("trace sys.health memory forget ", ""), complete("trace forget ", "")), ([], []))
        cases.record("judgement", {**asked, "value": "20% free"}, "worrying", "user", "accepted")
        cases.record("judgement", {**asked, "value": "10% free"}, "worrying", "user", "accepted", reach="up to")
        cases.record("judgement", {**asked, "value": "50% free"}, "fine", "user", "accepted", reach="from")
        self.assertEqual(complete("trace sys.health memory forget ", ""), ["20% free", "from 50% free", "up to 10% free"])
        self.assertEqual(complete("trace sys.health memory forget ", "f"), ["from 50% free"])
        self.assertEqual(complete("trace sys.health memory forget up to ", ""), ["10% free"])    # from the word being typed on
        self.assertEqual(complete("trace sys.health memory forget 20% ", "f"), ["free"])
        self.assertEqual(complete("trace forget ", ""), ["2"])                   # the one of the latest run that is the user's
        cases.record("judgement", {**asked, "value": "20% free"}, "worrying", "user", "taken back")
        self.assertEqual((complete("trace sys.health memory forget ", "2"), complete("trace forget ", "")), ([], []))

    def test_means_is_followed_by_a_command_line(self):
        self.assertEqual(complete("means ", "no"), ["note.add "])
        self.assertEqual(complete("means note.add ", "--t"), ["--tag ", "--text "])
        self.assertEqual(complete("means nothing ", ""), [])

    def test_a_settled_line_is_given_from_the_word_being_typed_on(self):
        def said(line, verdict, by="student"):
            cases.record("line", line, {"command": "sys.health", "args": {}}, by, verdict)

        said("how much ram is free", "accepted")
        said("how is the machine", "accepted")
        said("how hot is it", "declined")               # not settled, so typing it again would ask the student
        said("is it fine", "accepted")
        said("is it fine", "wrong", by="user")          # taken back
        self.assertEqual(complete("", "how"), ["how is the machine", "how much ram is free"])
        self.assertEqual(complete("how much ", "r"), ["ram is free"])
        self.assertEqual(complete("how much ram is ", "free"), [])          # all of it is there already
        self.assertEqual(complete("is ", "it"), [])
        self.assertEqual(complete("", "h"), ["help ", "how is the machine", "how much ram is free"])


CHILD = """
import pathlib, sys
from los import terminal
from los.plugins import Command, Param
table = {"fs.list": Command("fs.list", "List a folder", {"path": Param(path="read"), "sort_by": Param()})}
read, edit = terminal.start(lambda: table, pathlib.Path(sys.argv[1]))
for step in sys.argv[2:]:
    if step == "line":
        print("GOT", repr(read("lo-s> ")))
    elif step == "question":
        print("GOT", repr(input("Run it? [Y/n] ")))
    else:
        print("GOT", repr(edit("Correct it: ", step)))
print("DONE")
"""
UP = "\x1b[A"


@unittest.skipUnless(pty, "there is no terminal to try it in")
class TypingTest(Folders):
    """The same through a real terminal: a pseudo-terminal with readline at the other end."""

    def typed(self, *steps):
        """Run the child above with one prompt for each step, typing each step's keys once its
        prompt is there. A step is (what the child reads, the keys). Returns what the child read."""
        history = state.directory() / "history"
        pid, fd = pty.fork()
        if pid == 0:
            os.execve(sys.executable, [sys.executable, "-c", CHILD, str(history)] + [what for what, _ in steps],
                      {**os.environ, "PYTHONPATH": str(state.ROOT), "TERM": "xterm", "INPUTRC": "/dev/null"})
        seen = b""

        def wait_for(marker, count):
            nonlocal seen
            while seen.count(marker) < count:
                if not select.select([fd], [], [], 10)[0]:
                    self.fail(f"the terminal went quiet before {marker!r} came {count} times: {seen!r}")
                try:
                    seen += os.read(fd, 4096)
                except OSError:     # the child has gone
                    break

        prompts = {"line": b"lo-s> ", "question": b"Run it? [Y/n] "}
        waited = {}
        for what, keys in steps:
            prompt = prompts.get(what, b"Correct it: ")
            waited[prompt] = waited.get(prompt, 0) + 1
            wait_for(prompt, waited[prompt])
            os.write(fd, keys.encode())
        wait_for(b"DONE", 1)
        os.close(fd)
        os.waitpid(pid, 0)
        return [eval(got) for got in re.findall(r"GOT (.*?)\r?\n", seen.decode())]

    def test_history_holds_the_lines_and_not_the_answers_and_lasts(self):
        got = self.typed(("line", "how much ram is free\n"), ("question", "y\n"), ("line", UP + "\n"),
                         ("line", "   \n"), ("line", UP + UP + "\n"))
        # The line comes back with Up, the y between does not, and saying a line twice keeps it once.
        self.assertEqual(got, ["how much ram is free", "y", "how much ram is free", "   ", "how much ram is free"])
        self.assertEqual((state.directory() / "history").read_text(), "how much ram is free\n")
        self.assertEqual(self.typed(("line", "fs.list\n"), ("line", UP + UP + "\n")), ["fs.list", "how much ram is free"])
        self.assertEqual((state.directory() / "history").read_text(), "how much ram is free\nfs.list\nhow much ram is free\n")

    def test_tab_completes_a_command_a_parameter_and_a_path(self):
        (self.files / "docs").mkdir()
        self.assertEqual(self.typed(("line", f"fs.l\t--p\t{self.files}/do\t\n")), [f"fs.list --path {self.files}/docs/"])
        cases.record("line", "how much ram is free", {"command": "fs.list", "args": {}}, "student", "accepted")
        self.assertEqual(self.typed(("line", "how m\t\n")), ["how much ram is free"])

    def test_a_line_to_correct_starts_out_filled_in(self):
        got = self.typed(("fs.list --path home", "\x7f" * 4 + "~\n"), ("line", UP + "\n"))
        self.assertEqual(got, ["fs.list --path ~", ""])       # and a corrected line is not a line of history


SAVE, BACK, CLEAR = terminal.SAVE, terminal.BACK, terminal.CLEAR


class Screen(io.StringIO):
    """What was written to a terminal, and a way to wait until something has been."""

    def __init__(self):
        super().__init__()
        self.written = threading.Event()

    def write(self, text):
        self.written.set()
        return super().write(text)


class WaitingTest(unittest.TestCase):
    def waited(self, text, columns=80, **how):
        screen = Screen()
        with mock.patch.dict("os.environ", {"COLUMNS": str(columns)}), terminal.waiting(text, out=screen, **how):
            if how.get("soon") == 0:
                screen.written.wait(5)
        return screen.getvalue()

    def test_a_line_that_is_kept_is_written_at_once_and_ends_with_the_time_it_took(self):
        wrote = self.waited("Asking the teacher about: a thing")
        self.assertTrue(wrote.startswith("Asking the teacher about: a thing" + SAVE + BACK + "  0 s" + CLEAR))
        self.assertRegex(wrote, re.escape(BACK) + r"  \(0\.\d s\)" + re.escape(CLEAR) + r"\n$")
        self.assertEqual(wrote.count("Asking"), 1)          # the text is not written again, only the count after it

    def test_a_text_is_broken_between_words_so_that_the_count_has_room_after_it(self):
        asking = "Asking gemma-4-26B-A4B-it-qat-q4_0.gguf 38 example lines of 7 commands a model wrote."
        room = len(asking) + terminal.ROOM                      # the columns the text and the count take together
        for columns in (room - 12, room - 6, room - 1):         # the text fits, and the count after it does not
            wrote = self.waited(asking, columns=columns)
            first, second = wrote[:wrote.index(SAVE)].split("\n")
            self.assertEqual((first + " " + second, len(first) <= columns - terminal.ROOM, 0 < len(second)),
                             (asking, True, True))
        self.assertTrue(self.waited(asking, columns=room).startswith(asking + SAVE))
        said = "two lines\n\nand a third, which is long enough to be broken between two of its words"
        self.assertTrue(self.waited(said, columns=60).startswith(
            "two lines\n\nand a third, which is long enough to be broken\nbetween two of its words" + SAVE))

    def test_the_count_goes_on_a_line_of_its_own_after_a_word_too_long_to_break(self):
        for text in ("x" * 50, "x" * 60, "x" * 170, "日本" * 13):         # near the edge, at it, on a third line, wide
            self.assertTrue(self.waited(text, columns=60).startswith(text + "\n" + SAVE), text)
        for text in ("x" * 46, "x" * 61):
            self.assertTrue(self.waited(text, columns=60).startswith(text + SAVE), text)

    def test_a_line_that_is_not_kept_is_not_shown_for_a_short_wait_and_is_gone_after_a_long_one(self):
        self.assertEqual(self.waited("Asking the student", kept=False, soon=60), "")
        self.assertEqual(self.waited("Asking the student", kept=False, soon=0),
                         "\rAsking the student  0 s" + CLEAR + "\r" + CLEAR)
        self.assertEqual(self.waited("Asking " + "x" * 80, columns=40, kept=False, soon=0)[:29], "\rAsking " + "x" * 19 + "  ")

    def test_a_wait_that_ends_in_a_fault_still_ends_its_line(self):
        screen = Screen()
        with self.assertRaises(KeyboardInterrupt), terminal.waiting("Asking", out=screen):
            raise KeyboardInterrupt
        self.assertTrue(screen.getvalue().endswith(CLEAR + "\n"))

    def test_a_time_is_given_to_a_tenth_of_a_second_while_it_is_short(self):
        self.assertEqual([terminal.took(seconds) for seconds in (0.42, 4.02, 9.94, 10.2, 131.09)],
                         ["0.4 s", "4.0 s", "9.9 s", "10 s", "131 s"])
