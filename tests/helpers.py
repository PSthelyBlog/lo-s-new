"""Shared test fixtures."""
import os
import pathlib
import tempfile
import textwrap
import unittest

from los import plugins, sandbox
from los.shell import Shell

needs_sandbox = unittest.skipIf(sandbox.unusable(), f"commands cannot be sandboxed here: {sandbox.unusable()}")


class Folders(unittest.TestCase):
    """Gives each test a folder of its own, with an empty state folder and a place for its files.

    The folder is made outside /tmp when the machine has somewhere else for it. Inside the
    sandbox /tmp is the command's own scratch space, so a path under the host's /tmp is the one
    place where writing beside a granted path does not fail. It is lost instead.
    """

    def setUp(self):
        elsewhere = os.environ.get("XDG_RUNTIME_DIR")
        folder = tempfile.TemporaryDirectory(
            prefix="los-test-", dir=elsewhere if elsewhere and os.access(elsewhere, os.W_OK) else None)
        self.addCleanup(folder.cleanup)
        self.root = pathlib.Path(folder.name)
        self.files = self.root / "files"
        self.files.mkdir()
        previous = os.environ.get("LOS_STATE")
        os.environ["LOS_STATE"] = str(self.root / "state")
        self.addCleanup(lambda: os.environ.pop("LOS_STATE") if previous is None
                        else os.environ.__setitem__("LOS_STATE", previous))

    def plugin(self, manifest, code, folder="probe"):
        """Write a plugin into the test's own plugin folder. Returns the table and what load said."""
        place = self.root / "plugins" / folder
        place.mkdir(parents=True)
        (place / "plugin.toml").write_text(textwrap.dedent(manifest))
        (place / "commands.py").write_text(textwrap.dedent(code))
        return plugins.load(self.root / "plugins")


class Ran:
    """Stands in for the sandbox: notes what was run and answers with a prepared result."""

    def __init__(self, result=None):
        self.calls, self.result = [], result

    def __call__(self, command, args):
        self.calls.append((command.name, args))
        return self.result or sandbox.Result(f"ran {command.name}")


def table(*commands):
    """A table of commands that exist only as entries: (name, parameter names, effect)."""
    return {name: plugins.Command(name, f"Test command {name}", {param: plugins.Param() for param in params}, effect)
            for name, params, effect in commands}


TABLE = table(("fs.list", ["path", "sort_by"], "read"), ("note.add", ["text"], "write"),
              ("fs.move", ["source", "dest"], "destructive"))


class ShellCase(unittest.TestCase):
    """A shell whose commands and user are both scripted."""

    def shell(self, answers=(), result=None, commands=TABLE):
        self.shown, self.asked, self.ran = [], [], Ran(result)
        replies = list(answers)

        def ask(question):
            self.asked.append(question)
            if not replies:
                raise EOFError
            return replies.pop(0)

        return Shell(commands, ask, self.shown.append, self.ran)
