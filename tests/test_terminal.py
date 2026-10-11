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
from los.say import Aside, Exact, Fault, Said, Warn, voices
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

    def test_within_a_word_tab_works_on_what_follows_the_last_slash(self):
        for name in ("docs", "downloads"):
            (self.files / name).mkdir()
        (self.files / "docs" / "draft.txt").write_text("")
        offered = lambda before, text: terminal.offered(TABLE, before, text)
        # The word is the whole path. What is offered takes the place of its last part only.
        self.assertEqual(offered(f"fs.list --path {self.files}/", "do"), ["docs/", "downloads/"])
        self.assertEqual(offered(f"fs.list --path {self.files}/docs/", ""), ["draft.txt "])
        self.assertEqual(offered(f"fs.list --path {self.files}/nowhere/", "x"), [])
        self.assertEqual(offered("fs.list --path ", "~"), ["~/"])
        # Where no slash was typed, it is as before.
        self.assertEqual(offered("", "fs"), ["fs.list ", "fs.move "])
        self.assertEqual(offered("fs.list ", "--p"), ["--path "])
        self.assertEqual(offered("trace ", "sys"), ["sys.health "])
        # A settled line with a slash in it is given from the last slash on.
        cases.record("line", "what is the price/performance of this", {"command": "fs.list", "args": {}}, "student", "accepted")
        self.assertEqual(offered("what is the ", "pri"), ["price/performance of this"])
        self.assertEqual(offered("what is the price/", "perf"), ["performance of this"])

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
    elif step == "asked":
        print("GOT", repr(terminal.ask("Sure? [y/N] ")))
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

        prompts = {"line": b"lo-s> ", "question": b"Run it? [Y/n] ", "asked": b"Sure? [y/N] "}
        waited = {}
        for what, keys in steps:
            prompt = prompts.get(what, b"Correct it: ")
            waited[prompt] = waited.get(prompt, 0) + 1
            wait_for(prompt, waited[prompt])
            os.write(fd, keys.encode())
        wait_for(b"DONE", 1)
        os.close(fd)
        os.waitpid(pid, 0)
        self.screen = seen.decode()
        return [eval(got) for got in re.findall(r"GOT (.*?)\r?\n", self.screen)]

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

    def test_tab_lists_the_names_in_a_folder_and_not_the_folders_that_lead_to_them(self):
        for name in ("docs", "downloads"):
            (self.files / name).mkdir()
        # One Tab completes as far as the names agree and lists them. Then c settles it.
        got = self.typed(("line", f"fs.list --path {self.files}/\tc\t\n"))
        self.assertEqual(got, [f"fs.list --path {self.files}/docs/"])
        self.assertRegex(self.screen, r"docs/\s+downloads/")
        self.assertNotIn(f"{self.files}/downloads", self.screen)

    def test_tab_offers_nothing_at_a_question(self):
        (self.files / "visible.txt").write_text("")
        self.addCleanup(os.chdir, os.getcwd())
        os.chdir(self.files)
        got = self.typed(("asked", "\ty\n"), ("line", "fs.l\t\n"))
        self.assertEqual(got, ["y", "fs.list "])                # and it completes again at the next line
        asked = self.screen.partition("lo-s> ")[0]
        self.assertNotIn("fs.list", asked)                      # neither a command
        self.assertNotIn("visible.txt", asked)                  # nor a file of the folder

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


B, D, R, Y, O = terminal.BOLD, terminal.DIM, terminal.RED, terminal.YELLOW, terminal.RESET


class VoiceTest(unittest.TestCase):
    """What is said keeps its words, and a terminal shows each part in its voice."""

    def test_what_is_said_in_parts_is_the_words_joined_and_nothing_else_to_anyone_who_reads_it(self):
        said = Said("Not run. ", Aside("Say wrong to take it back."))
        self.assertEqual((said, said[:8], said.startswith("Not"), [said]), ("Not run. Say wrong to take it back.", "Not run.",
                                                                           True, ["Not run. Say wrong to take it back."]))
        self.assertEqual(voices(Said(said, Said(Fault("no"), Exact("x")), "y")),
                         [(str, "Not run. "), (Aside, "Say wrong to take it back."), (Fault, "no"), (Exact, "x"), (str, "y")])
        self.assertEqual(voices("plain"), [(str, "plain")])

    def test_prose_is_broken_between_words_and_set_under_where_its_text_starts(self):
        self.assertEqual(terminal.render("Nothing here does that yet. It is queued as need 1.", 30),
                         "Nothing here does that yet. It\nis queued as need 1.")
        self.assertEqual(terminal.render("1. You have asked 2 times for something nothing does.\n   delegate 1   (one call)", 30),
                         "1. You have asked 2 times for\n   something nothing does.\n   delegate 1   (one call)")
        self.assertEqual(terminal.render("fs.list   List the contents of a directory\nfs.usage  Show space", 30),
                         "fs.list   List the contents of\n          a directory\nfs.usage  Show space")
        self.assertEqual(terminal.render("  - a check that failed for a reason", 20), "  - a check that\n    failed for a\n    reason")
        self.assertEqual(terminal.render("one\n\n  two", 30), "one\n\n  two")                 # lines stay lines
        self.assertEqual(terminal.render("x " * 80, 500).split("\n")[0], ("x " * 50).strip())  # and no line of prose is wider than 100

    def test_a_text_with_a_word_too_long_for_a_line_is_left_as_it_is(self):
        said = "fs.copy: /a/very/long/path/that/does/not/fit/on/one/line/of/the/screen does not exist"
        self.assertEqual(terminal.render(Fault(said), 40), R + said + O)
        self.assertEqual(terminal.render(said, 40, colour=False), said)

    def test_an_aside_is_dim_a_fault_and_a_warning_are_coloured_and_plain_words_are_left_plain(self):
        said = Said("Not run. ", Aside("If that was the wrong command, say wrong."))
        self.assertEqual(terminal.render(said, 80), f"Not run. {D}If that was the wrong command, say wrong.{O}")
        self.assertEqual(terminal.render(said, 30), f"Not run. {D}If that was the wrong{O}\n{D}command, say wrong.{O}")
        self.assertEqual(terminal.render(said, 30, colour=False), "Not run. If that was the wrong\ncommand, say wrong.")
        self.assertEqual(terminal.render(Fault("fs.copy: a.txt does not exist"), 80), f"{R}fs.copy: a.txt does not exist{O}")
        self.assertEqual(terminal.render(Said(Warn("It cannot be undone. "), "Run it?", " [y/N] "), 80),
                         f"{Y}It cannot be undone. {O}Run it? [y/N]")
        self.assertEqual(terminal.render(Said(Warn(""), "Run it?"), 80), "Run it?")

    def test_a_command_about_to_run_is_bold_on_one_line_with_where_it_came_from_dim(self):
        long = "→ fs.move --source ~/a/rather/long/folder/photos --dest ~/a/rather/long/folder/photos-2"
        self.assertEqual(terminal.render(long, 40), B + long + O)
        self.assertEqual(terminal.render("→ fs.list --path ~  (remembered)", 80), f"{B}→ fs.list --path ~{O}{D}  (remembered){O}")
        self.assertEqual(terminal.render("It shows a folder.\n→ fs.list --path '(a)'", 80), f"It shows a folder.\n{B}→ fs.list --path '(a)'{O}")
        self.assertEqual(terminal.render("→ fs.list  (remembered)", 80, colour=False), "→ fs.list  (remembered)")

    def test_what_is_shown_exactly_is_left_alone_and_what_is_said_around_it_is_not(self):
        code = "def rule(value):\n    return 'fine' if int(value.split()[0]) < 80 else 'worrying'     # spaces   kept"
        self.assertEqual(terminal.render(Said(Exact(code), "\n\nWhy: The answers turn between 70 and 90 degrees."), 30),
                         code + "\n\nWhy: The answers turn between\n70 and 90 degrees.")
        self.assertEqual(terminal.render(Exact("   3B  a.txt\n→ not a command"), 80), "   3B  a.txt\n→ not a command")

    def test_a_question_is_written_up_to_its_last_line_which_is_what_the_answer_is_typed_after(self):
        asked, written = [], io.StringIO()
        question = Said("No rule yet: too little is on record.\n", Warn("It cannot be undone. "), "Run it?", " [y/N] ")
        with mock.patch("builtins.input", lambda prompt: asked.append(prompt) or "y"), \
                mock.patch("sys.stdout", written), mock.patch.dict("os.environ", {"COLUMNS": "80"}):
            self.assertEqual(terminal.ask(question), "y")
        self.assertEqual((written.getvalue(), asked), ("No rule yet: too little is on record.\n", ["It cannot be undone. Run it? [y/N] "]))

    def test_colour_is_for_a_terminal_and_can_be_turned_off(self):
        screen = mock.Mock(isatty=lambda: True)
        with mock.patch.dict("os.environ", {"TERM": "xterm-256color"}):
            os.environ.pop("NO_COLOR", None)
            self.assertTrue(terminal.coloured(screen))
            self.assertFalse(terminal.coloured(io.StringIO()))
            with mock.patch.dict("os.environ", {"NO_COLOR": "1"}):
                self.assertFalse(terminal.coloured(screen))
            with mock.patch.dict("os.environ", {"TERM": "dumb"}):
                self.assertFalse(terminal.coloured(screen))

    def test_a_wait_is_an_aside(self):
        screen = Screen()
        with mock.patch.dict("os.environ", {"COLUMNS": "80"}), terminal.waiting("Asking the teacher", out=screen, colour=True):
            pass
        self.assertTrue(screen.getvalue().startswith(D + "Asking the teacher" + O + SAVE + BACK + D + "  0 s" + O + CLEAR))
