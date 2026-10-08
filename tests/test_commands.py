"""The starter commands, run the way the shell runs them: in the sandbox."""
import os
import time

from los import cases, judge, plugins, sandbox, state
from tests.helpers import Folders, Scripted, needs_sandbox

TABLE, _ = plugins.load(state.ROOT / "plugins")


def run(command, /, **args):
    """What the command showed, or None when it refused."""
    result = sandbox.run(TABLE[command], args)
    assert not result.broke, result.text
    return result.text if result.ok else None


@needs_sandbox
class FilesTest(Folders):
    def setUp(self):
        super().setUp()
        (self.files / "docs").mkdir()
        (self.files / "docs" / "budget-2025.pdf").write_bytes(b"x" * 3000)
        (self.files / "docs" / "notes.txt").write_bytes(b"x" * 10)
        (self.files / "old.log").write_bytes(b"x" * 500)
        long_ago = time.time() - 90 * 86400
        os.utime(self.files / "old.log", (long_ago, long_ago))

    def found(self, **args):
        return [line.split()[-1].rsplit("/", 1)[-1] for line in run("fs.find", path=str(self.files), **args).splitlines()]

    def test_find(self):
        self.assertEqual(self.found(), ["budget-2025.pdf", "old.log", "notes.txt"])    # largest first
        self.assertEqual(self.found(name="*.pdf"), ["budget-2025.pdf"])
        self.assertEqual(self.found(name="budget"), ["budget-2025.pdf"])                # a word matches anywhere
        self.assertEqual(self.found(larger_than="1K"), ["budget-2025.pdf"])
        self.assertEqual(self.found(older_than="30 days"), ["old.log"])
        self.assertEqual(self.found(older_than="1 year"), ["match."])                   # "No files match."

    def test_find_explains_values_it_cannot_read(self):
        for args in ({"larger_than": "huge"}, {"older_than": "a while"}, {"older_than": "3 m"}):
            self.assertIsNone(run("fs.find", path=str(self.files), **args), args)
        self.assertIsNone(run("fs.find", path=str(self.files / "missing")))

    def test_list_and_usage(self):
        listing = run("fs.list", path=str(self.files), sort_by="size").splitlines()
        self.assertEqual([line.split()[-1] for line in listing], ["old.log", "docs/"])
        self.assertEqual(listing[0].split()[1], time.strftime("%Y-%m-%d", time.localtime(time.time() - 90 * 86400)))
        usage = run("fs.usage", path=str(self.files)).splitlines()
        self.assertTrue(usage[0].endswith(f"{self.files}  (total)"))
        self.assertTrue(usage[1].endswith("/docs"))
        self.assertIsNone(run("fs.usage", path=str(self.files), depth="two"))
        self.assertIsNone(run("fs.list", path=str(self.files), sort_by="colour"))

    def test_a_path_left_out_is_the_current_directory(self):
        self.addCleanup(os.chdir, os.getcwd())
        os.chdir(self.files)
        self.assertEqual([line.split()[-1] for line in run("fs.list").splitlines()], ["docs/", "old.log"])
        self.assertTrue(run("fs.usage", path="docs").splitlines()[0].endswith(f"{self.files}/docs  (total)"))

    def test_move_renames_moves_into_directories_and_never_overwrites(self):
        self.assertEqual(run("fs.move", source=str(self.files / "old.log"), dest=str(self.files / "older.log")),
                         f"Moved {self.files}/old.log to {self.files}/older.log")
        self.assertEqual(sorted(path.name for path in self.files.iterdir()), ["docs", "older.log"])
        run("fs.move", source=str(self.files / "older.log"), dest=str(self.files / "docs"))
        self.assertEqual((self.files / "docs" / "older.log").read_bytes(), b"x" * 500)
        self.assertIsNone(run("fs.move", source=str(self.files / "docs" / "older.log"),
                              dest=str(self.files / "docs" / "notes.txt")))
        self.assertEqual((self.files / "docs" / "notes.txt").read_bytes(), b"x" * 10)
        self.assertTrue((self.files / "docs" / "older.log").exists())
        for args in ({}, {"source": str(self.files / "nope"), "dest": str(self.files / "x")}):
            self.assertIsNone(run("fs.move", **args))

    def test_move_takes_a_directory_with_everything_in_it(self):
        run("fs.move", source=str(self.files / "docs"), dest=str(self.files / "papers"))
        self.assertEqual(sorted(path.name for path in (self.files / "papers").iterdir()), ["budget-2025.pdf", "notes.txt"])
        self.assertFalse((self.files / "docs").exists())


@needs_sandbox
class NotesAndStatusTest(Folders):
    def test_notes(self):
        self.assertEqual(run("note.list"), "No notes.")
        self.assertEqual(run("note.add", text="the wifi password is on the fridge"), "Noted.")
        run("note.add", text="cache dispatch results", tag="work")
        self.assertEqual(len(run("note.list").splitlines()), 2)
        self.assertEqual(run("note.list", tag="work"), f"{time.strftime('%Y-%m-%d')}  cache dispatch results  [work]")
        self.assertIsNone(run("note.add"))
        self.assertEqual([path.name for path in state.data("note").iterdir()], ["notes.jsonl"])

    def test_status(self):
        self.assertTrue(run("sys.status", what="memory").startswith("Memory: "))
        self.assertTrue(run("sys.status", what="cpu").startswith("CPU: load "))
        self.assertEqual(len(run("sys.status", what="all").splitlines()), len(run("sys.status").splitlines()))
        self.assertIsNone(run("sys.status", what="mood"))

    def test_health_has_each_reading_judged_once_and_says_what_was_found(self):
        def health(*student_says):
            result = sandbox.run(TABLE["sys.health"], {}, minds=judge.Minds(Scripted(*student_says)))
            self.assertFalse(result.broke, result.text)
            return result.text

        reading = r"memory \d+% free, of \d+ GB(; temperature -?\d+ °C)?"
        self.assertRegex(health({"answer": "fine"}, {"answer": "fine"}), rf"^The machine looks healthy: {reading}\.$")
        asked = cases.judgements()
        self.assertEqual([case["question"]["name"] for case in asked], ["memory", "temperature"][:len(asked)])
        self.assertEqual({(case["by"], tuple(case["question"]["choices"])) for case in asked}, {("student", ("fine", "worrying"))})
        (state.directory() / "cases.jsonl").unlink()         # with nothing on record the student is asked again
        self.assertRegex(health({"answer": "worrying"}, {"answer": "worrying"}), rf"^Worrying: {reading}\.$")
        if len(asked) == 2:                                 # a machine with a temperature sensor
            (state.directory() / "cases.jsonl").unlink()
            self.assertRegex(health({"answer": "worrying"}, {"answer": "fine"}),
                             r"^Worrying: memory \d+% free, of \d+ GB\. Fine: temperature -?\d+ °C\.$")
