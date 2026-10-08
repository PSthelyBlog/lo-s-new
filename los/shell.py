"""The shell: read a line and run it as a command.

A line is one of the shell's own words, or a structured command, `plugin.verb --param value`,
which runs in the sandbox with what its manifest and the line grant it. A destructive command
asks first. Plain language is not read yet.
"""
import argparse
import os
import pathlib

from . import plugins, sandbox, state
from .parse import UsageError, flag, parse, usage

BUILTINS = {
    "help": "help lists the commands. help NAME explains one and says what it may touch.",
    "exit": "exit leaves the shell.",
}
CARE = {
    "read": "It only reads, so it runs as soon as you type it.",
    "write": "It changes what lo-s keeps for its plugin and no file of yours, so it runs as soon as you type it.",
    "destructive": "It can change or move what you name, so it asks before it runs.",
}


class Shell:
    def __init__(self, table, ask=input, out=print, run=sandbox.run):
        self.table, self.ask, self.out, self.runner = table, ask, out, run

    def handle(self, line):
        """Take one typed line. Returns False when the shell should stop."""
        line = line.strip()
        words = line.split()
        if not words:
            return True
        if line in ("exit", "quit"):
            return False
        if words[0] == "help":
            self.help(words[1:])
            return True
        try:
            parsed = parse(line, self.table)
        except UsageError as error:
            self.out(f"{error}\nUsage: {usage(self.table[words[0]])}")
            return True
        if parsed:
            self.run_typed(*parsed)
        else:
            self.out("That is not a command. Type help to list the commands. Plain language is not read yet.")
        return True

    def run_typed(self, command, args):
        if command.effect == "destructive" and not self.confirm(
                f"{command.name} makes changes that cannot be undone. Run it?", default=False):
            self.out("Not run.")
            return
        self.run(command, args)

    def run(self, command, args):
        result = self.runner(command, args)
        if result.broke:
            self.out(f"{command.name} broke. The fault is in the command, not in what you typed.\n{result.text}")
        elif not result.ok:
            self.out(f"{command.name}: {result.text}")
        elif result.text:
            self.out(result.text)

    def confirm(self, question, default):
        try:
            answer = self.ask(f"{question} [{'Y/n' if default else 'y/N'}] ").strip().lower()
        except EOFError:  # nobody is there to agree
            return False
        return default if not answer else answer.startswith("y")

    def help(self, names):
        if not names:
            width = max(map(len, self.table), default=0)
            self.out("\n".join(f"{name:{width}}  {self.table[name].description}" for name in sorted(self.table)))
            self.out("\nType a command as NAME --parameter value. help NAME explains one and says what it\n"
                     "may touch. Each command runs in a sandbox that holds only that. exit leaves.")
            return
        for name in names:
            if name in BUILTINS:
                self.out(BUILTINS[name])
                continue
            if name not in self.table:
                self.out(f"There is no command named {name}.")
                continue
            command = self.table[name]
            width = max((len(flag(key)) for key in command.params), default=0)
            self.out("\n".join([command.description, f"Usage: {usage(command)}"] +
                               [f"  {flag(key):{width}}  {param.hint}" for key, param in command.params.items()]))
            self.out("\n".join([CARE[command.effect]] + plugins.touches(command)))


def main(argv=None):
    parser = argparse.ArgumentParser(prog="lo-s", description="The lo-s shell.")
    parser.add_argument("-c", dest="line", metavar="LINE", help="run one line and exit")
    opts = parser.parse_args(argv)

    plugin_dir = pathlib.Path(os.environ.get("LOS_PLUGINS", state.ROOT / "plugins"))
    table, problems = plugins.load(plugin_dir)
    for problem in problems:
        print(problem)
    if os.environ.get("LOS_NO_SANDBOX") == "1":
        print("LOS_NO_SANDBOX is set: every command runs without a sandbox, with all of your permissions.")
    elif sandbox.unusable():
        print(f"Commands cannot be sandboxed here: {sandbox.unusable()}.\n"
              "The starter commands run without a sandbox, with all of your permissions. A command written by "
              "a model does not run at all, unless you set LOS_NO_SANDBOX=1.")

    shell = Shell(table)
    if opts.line is None:
        import readline  # noqa: F401  gives input() line editing and history
    while True:
        try:
            if not shell.handle(opts.line if opts.line is not None else input("lo-s> ")) or opts.line is not None:
                break
        except EOFError:
            print()
            break
        except KeyboardInterrupt:   # the command that was running has been stopped
            print("\nInterrupted.")
            if opts.line is not None:
                break
