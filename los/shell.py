"""The shell: read a line, run it as a command, or find out which command was meant.

A typed line is handled in this order, and the first that applies ends it:

1. It is one of the shell's own words.
2. It is a structured command, `plugin.verb --param value`. It runs as typed.
3. The user accepted a command for this exact line before. That command is shown as remembered,
   and no model is asked.
4. The student is asked which command the line means. Its choice is shown in typed form and runs
   only if the user agrees.
5. Nothing fits, and the line is queued as a need.

Whatever is shown before a question is the command in full: defaults filled in and every path
absolute. That line is what will run and all that the command can touch.
"""
import argparse
import os
import pathlib
import tomllib

from . import cases, plugins, route, sandbox, state
from .models import ModelUnavailable, provider
from .parse import UsageError, flag, parse, render, usage

BUILTINS = {
    "help": "help lists the commands. help NAME explains one and says what it may touch.",
    "wrong": "wrong takes back the latest command chosen for a plain-language line, so that the line is no longer "
             "remembered that way. It then offers to queue the line as a need.",
    "needs": "needs lists the lines no command could handle, each with its number.",
    "forget": "forget NUMBER drops a queued need.",
    "stats": "stats shows how many plain-language lines memory and the student answered, and the model time "
             "memory saved.",
    "exit": "exit leaves the shell.",
}
CARE = {
    "read": "It only reads, so it runs as soon as you type it.",
    "write": "It changes what lo-s keeps for its plugin and no file of yours, so it runs as soon as you type it.",
    "destructive": "It can change or move what you name, so it asks before it runs.",
}
UNDONE = "It makes changes that cannot be undone. "


class Shell:
    def __init__(self, table, ask=input, out=print, run=sandbox.run, student=None):
        self.table, self.ask, self.out, self.runner, self.student = table, ask, out, run, student
        self.last = None    # the latest command chosen for a plain-language line, so that `wrong` can take it back

    def handle(self, line):
        """Take one typed line through the steps above. Returns False when the shell should stop."""
        line = line.strip()
        words = line.split()
        if not words:
            return True
        if line in ("exit", "quit"):
            return False
        if words[0] == "help":
            self.help(words[1:])
        elif line == "wrong":
            self.wrong()
        elif line == "needs":
            self.needs()
        elif words[0] == "forget":
            self.forget(words[1:])
        elif line == "stats":
            self.stats()
        else:
            try:
                parsed = parse(line, self.table)
            except UsageError as error:
                self.out(f"{error}\nUsage: {usage(self.table[words[0]])}")
                return True
            if parsed:
                self.run_typed(*parsed)
            else:
                self.interpret(line)
        return True

    def run_typed(self, command, args):
        if command.effect == "destructive":
            self.out("→ " + self.typed(command, args))
            if not self.confirm(UNDONE + "Run it?", default=False):
                self.out("Not run.")
                return
        self.run(command, args)

    def interpret(self, line):
        """Plain language. A line the user settled before is answered from memory; otherwise the
        student is asked. Either way the choice is shown as a typed command before anything runs."""
        case = cases.remembered(line, self.table)
        if case:
            answer = case["answer"]
            command, args = self.table[answer["command"]], answer["args"]
            self.out("→ " + self.typed(command, args) + "  (remembered)")
            # The user agreed to this before, so reading runs at once. Changing anything still asks.
            accepted = command.effect == "read" or self.agree(command)
            cases.record("line", line, answer, "memory", "accepted" if accepted else "declined",
                         saved=case.get("seconds") or case.get("saved") or 0)
        else:
            if not self.student:
                self.out("That is not a command, and no model is set up to read plain language. Give the student "
                         "role a provider in los.toml, or type help to list the commands.")
                return
            try:
                choice = route.ask(self.student, self.table, line)
            except ModelUnavailable as error:
                self.out(f"That is not a command, and the student, which reads plain language, did not answer: {error}.\n"
                         "If it is the local model, scripts/serve.sh starts it. Structured commands still work; "
                         "type help to list them.")
                return
            except RuntimeError as error:
                self.out(f"The student's answer could not be used: {error}")
                return
            asked = {"model": self.student.model, "seconds": choice.meta.get("seconds")}
            if choice.command is None:
                cases.record("line", line, {"command": None, "args": {}}, "student", **asked)
                self.queue(line, "student")
                return
            answer = {"command": choice.command, "args": choice.args}
            command, args = self.table[choice.command], choice.args
            self.out("→ " + self.typed(command, args))
            accepted = self.agree(command)
            # Accepting settles the line. Declining does not: the choice may be right and simply
            # unwanted just now.
            cases.record("line", line, answer, "student", "accepted" if accepted else "declined", **asked)
        self.last = (line, answer)
        if accepted:
            self.run(command, args)
        else:
            self.out("Not run. If that was the wrong command for what you typed, say wrong.")

    def agree(self, command):
        """Ask before running a command a model chose. Enter accepts one that only reads; anything
        else needs an explicit yes."""
        return self.confirm((UNDONE if command.effect == "destructive" else "") + "Run it?",
                            default=command.effect == "read")

    def typed(self, command, args):
        """A command in full, as it will run: defaults filled in and every path absolute, with
        the home folder written as ~."""
        home = os.path.expanduser("~")

        def short(path):
            return "~" + path[len(home):] if path == home or path.startswith(home + os.sep) else path

        return render(command.name, {name: short(value) if command.params[name].path else value
                                     for name, value in sandbox.complete(command, args).items()})

    def wrong(self):
        """Take back the latest command chosen for a plain-language line."""
        if not self.last:
            self.out("There is no plain-language choice to take back.")
            return
        (line, answer), self.last = self.last, None
        cases.record("line", line, answer, "user", "wrong")
        self.out(f"Taken back: \"{line}\" does not mean {answer['command']}, and is not remembered that way.")
        if self.confirm("Queue it as a need for a new command?", default=False):
            self.queue(line, "user")

    def queue(self, line, by):
        number = cases.queue(line, by)
        self.out(f"Nothing here does that yet. It is queued as need {number}. needs lists the queue, and "
                 f"forget {number} drops it.")

    def needs(self):
        waiting = cases.waiting()
        self.out("\n".join(f"{number}. {need['line']}  ({need['date']})" for number, need in waiting.items())
                 or "No needs are waiting.")

    def forget(self, words):
        waiting = cases.waiting()
        if len(words) != 1 or not words[0].isdigit() or int(words[0]) not in waiting:
            self.out("Usage: forget NUMBER, where NUMBER is one of those listed by needs.")
            return
        cases.drop(int(words[0]))
        self.out(f"Forgotten: {waiting[int(words[0])]['line']}")

    def stats(self):
        lines = [case for case in state.read("cases") if case["kind"] == "line"]
        recalled = [case for case in lines if case["by"] == "memory"]
        asked = [case for case in lines if case["by"] == "student"]
        told = {verdict: sum(case["verdict"] == verdict for case in asked) for verdict in ("accepted", "declined", "")}
        self.out(f"Plain-language lines: {len(recalled) + len(asked)}\n"
                 f"Answered from memory: {len(recalled)}, saving about "
                 f"{sum(case.get('saved') or 0 for case in recalled):.1f} s of model time\n"
                 f"Answered by the student: {len(asked)}, taking {sum(case.get('seconds') or 0 for case in asked):.1f} s "
                 f"({told['accepted']} accepted, {told['declined']} declined, {told['']} where nothing fitted)\n"
                 f"Taken back with wrong: {sum(case['verdict'] == 'wrong' for case in lines)}\n"
                 f"Needs waiting: {len(cases.waiting())}")

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
            self.out("\nType a command as NAME --parameter value, or say what you want in your own words: the\n"
                     "command that fits is shown before it runs. A line you accepted is remembered; wrong\n"
                     "takes the latest choice back. needs lists what nothing could do yet, forget NUMBER\n"
                     "drops one, and stats shows how often memory answered. help NAME explains a command\n"
                     "and says what it may touch; each runs in a sandbox that holds only that. exit leaves.")
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

    settings = pathlib.Path(os.environ.get("LOS_CONFIG", state.ROOT / "los.toml"))
    config = tomllib.loads(settings.read_text()) if settings.exists() else {}
    student = config.get("roles", {}).get("student")
    shell = Shell(table, student=provider(config["providers"][student]) if student else None)
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
