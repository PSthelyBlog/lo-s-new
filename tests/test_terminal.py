"""Line editing: what Tab offers, and history and a line to correct as a terminal sees them."""
import os
import re
import select
import sys
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
        self.assertEqual(complete("trace sys.health memory ", ""), ["from ", "up to "])     # a stretch of values
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
