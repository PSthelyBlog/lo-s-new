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

`delegate` is for what no command does yet, or for a user who does not know what to type: they
say what they need, and the teacher answers with a command to run, a new command, a question or
the news that lo-s cannot do it. `means` is the user saying themselves what a line means.

A command may ask for a judgement while it runs. `trace` shows the judgements of the latest run
and where each answer came from, and lets the user set one. `rule` has the teacher turn the
answers on record for one judgement into code.
"""
import argparse
import datetime
import os
import pathlib
import shutil
import statistics
import tomllib

from . import cases, judge, plugins, route, rules, sandbox, state, teach
from .models import ModelUnavailable, provider
from .parse import UsageError, flag, parse, render, usage

BUILTINS = {
    "help": "help lists the commands. help NAME explains one and says what it may touch.",
    "wrong": "wrong takes back the latest command chosen for a plain-language line, so that the line is no longer "
             "remembered that way. It then offers to queue the line as a need.",
    "means": "means COMMAND --parameter value says what the latest plain-language line means. It is remembered for "
             "that line from then on, and the command runs.",
    "needs": "needs lists the lines no command could handle, each with its number.",
    "forget": "forget NUMBER drops a queued need.",
    "delegate": "delegate WHAT YOU NEED, in your own words, asks the teacher what to do about it: run a command "
                "that exists, install a new one that it writes, or neither. delegate NUMBER does that for a queued "
                "need. You see its answer, and what a new command may touch, before anything happens.",
    "trace": "trace shows the judgements the latest command asked for, and where each answer came from: what is on "
             "record, a rule or the student. trace NUMBER ANSWER sets one yourself, and it is used from then on.",
    "rule": "rule COMMAND NAME asks the teacher to turn the answers on record for one judgement into a small "
            "function. It is tried on every one of them, and you see it before it is used. From then on that "
            "judgement asks the rule before the student.",
    "stats": "stats shows how many plain-language lines memory, the student and the teacher answered, the model "
             "time memory saved, who made the judgements commands asked for, and how many calls the teacher got.",
    "exit": "exit leaves the shell.",
}
CARE = {
    "read": "It only reads, so it runs as soon as you type it.",
    "write": "It can add something new and cannot change what exists, so it runs as soon as you type it.",
    "destructive": "It can change or remove what you name, so it asks before it runs.",
}
UNDONE = "It makes changes that cannot be undone. "
FITS = "If a command does fit, say which: means COMMAND --parameter value."
EXAMPLE = state.ROOT / "plugins" / "fs"     # the plugin the teacher is shown as an example of the style


class Shell:
    def __init__(self, table, ask=input, out=print, run=sandbox.run, student=None, teacher=None, plugin_dir=None):
        self.table, self.ask, self.out, self.runner, self.student = table, ask, out, run, student
        self.teacher, self.plugin_dir = teacher, plugin_dir
        self.minds = judge.Minds(student, teacher, self.confirm)    # what a running command reaches a model through
        self.said = None    # the latest plain-language line, so that `means` can settle it
        self.last = None    # that line and the command chosen for it, so that `wrong` can take the choice back

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
        elif words[0] == "means":
            self.means(line[len("means"):].strip())
        elif words[0] == "delegate":
            self.delegate(line[len("delegate"):].strip())
        elif line == "needs":
            self.needs()
        elif words[0] == "forget":
            self.forget(words[1:])
        elif line == "stats":
            self.stats()
        elif words[0] == "trace":
            self.trace(words[1:])
        elif words[0] == "rule":
            self.rule(words[1:])
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
        self.said, doubted = line, False
        case = cases.remembered(line, self.table)
        if case:
            answer = case["answer"]
            command, args = self.table[answer["command"]], answer["args"]
            self.out("→ " + self.typed(command, args) + "  (remembered)")
            # The user agreed to this before, so reading runs at once. Changing anything still asks.
            accepted = command.effect == "read" or self.agree(command)
            cases.record("line", line, answer, "memory", "accepted" if accepted else "declined")
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
            # The student gives the same answer to the same line, so what the user said about it
            # last time still holds: it is shown as doubted and Enter no longer runs it.
            doubted = cases.taken_back(line, answer)
            self.out("→ " + self.typed(command, args) + ("  (you said this was wrong)" if doubted else ""))
            accepted = self.agree(command, doubted)
            # Accepting settles the line. Declining does not: the choice may be right and simply
            # unwanted just now.
            cases.record("line", line, answer, "student", "accepted" if accepted else "declined", **asked)
        self.last = (line, answer)
        if accepted:
            self.run(command, args)
        elif doubted:
            self.out("Not run. " + FITS)
        else:
            self.out("Not run. If that was the wrong command for what you typed, say wrong, or say the right one "
                     "with means.")

    def agree(self, command, doubted=False):
        """Ask before running a command a model chose. Enter accepts one that only reads; anything
        else, and a choice the user took back before, needs an explicit yes."""
        return self.confirm((UNDONE if command.effect == "destructive" else "") + "Run it?",
                            default=command.effect == "read" and not doubted)

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
        self.out(f"Taken back: \"{line}\" does not mean {render(answer['command'], answer['args'])}, and is not "
                 "remembered that way.\n" + FITS)
        if self.confirm("Or queue it as a need for a new command?", default=False):
            self.queue(line, "user")

    def means(self, rest):
        """The user says what the latest plain-language line means. Theirs is the surest answer
        there is, so it is remembered as given, and the command runs."""
        if not self.said:
            self.out("There is no plain-language line to settle yet. Say what you want first, then: "
                     "means COMMAND --parameter value.")
            return
        try:
            parsed = parse(rest, self.table)
        except UsageError as error:
            self.out(f"{error}\nUsage: means {usage(self.table[rest.split()[0]])}")
            return
        if not parsed:
            self.out("Usage: means COMMAND --parameter value, with one of the commands help lists.")
            return
        command, args = parsed
        answer = {"command": command.name, "args": args}
        cases.record("line", self.said, answer, "user", "accepted")
        self.last = (self.said, answer)
        self.out(f"Remembered: \"{self.said}\" means {render(command.name, args)}.")
        self.answered(self.said)
        self.run_typed(command, args)

    def answered(self, line):
        """A line that now has its answer leaves the queue of needs."""
        for number, need in cases.waiting().items():
            if need["line"] == line:
                cases.drop(number)
                self.out(f"That answers need {number}, so it left the queue.")

    def queue(self, line, by):
        number = cases.queue(line, by)
        self.out(f"Nothing here does that yet. It is queued as need {number}. " +
                 (f"delegate {number} asks {self.teacher.model} about it, and " if self.teacher else
                  "needs lists the queue, and ") + f"forget {number} drops it.")

    def delegate(self, words):
        """Ask the teacher what to do about something the user wants, and do it if they agree.
        A number stands for the need queued under it. Every pass through the loop is one call."""
        number = None
        if words.isdigit():
            if int(words) not in cases.waiting():
                self.out("Usage: delegate NUMBER, where NUMBER is one of those listed by needs.")
                return
            number, words = int(words), cases.waiting()[int(words)]["line"]
        if not words:
            self.out("Usage: delegate WHAT YOU NEED, in your own words, or delegate NUMBER for a queued need.")
            return
        if not self.teacher or not self.plugin_dir:
            self.out("No model is set up as the teacher. Give the teacher role a provider in los.toml.")
            return
        exchange, earlier = [], None    # what it asked and was told; a proposal of its own to put right
        while True:
            self.out(f"Asking {self.teacher.model}{' again' if exchange or earlier else ''} about: {words}")
            record = {"date": datetime.date.today().isoformat(), "words": words, "model": self.teacher.model}
            try:
                advice, meta = teach.ask(self.teacher, words, self.table,
                                         {"student": self.student, "teacher": self.teacher}, EXAMPLE, exchange, earlier)
            except (ModelUnavailable, RuntimeError) as error:
                state.append("delegations", {**record, "failed": str(error)})
                self.out(f"No answer came back that could be used: {error}")
                if number is None and self.confirm("Queue your words as a need, to ask again later?", default=True):
                    number = cases.queue(words, "user")
                    self.out(f"Queued as need {number}. delegate {number} asks again.")
                return
            state.append("delegations", {**record, "seconds": meta.get("seconds"), "answer": advice.raw})
            if advice.answer == "ask":
                self.out(f"{advice.reason}\n{self.teacher.model} asks: {advice.question}")
                try:
                    reply = self.ask("Your answer, or Enter to leave it there: ").strip()
                except EOFError:
                    reply = ""
                if not reply:
                    self.out("Left there. Nothing was sent.")
                    return
                exchange.append((advice.question, reply))
            elif advice.answer == "write":
                earlier = self.propose(advice, words, number)
                if not earlier:
                    return
            else:
                break
        if advice.answer == "cannot":
            self.out(f"lo-s cannot do this: {advice.reason}" +
                     (f"\nNeed {number} stays queued; forget {number} drops it." if number else ""))
            return
        command, answer = self.table[advice.command], {"command": advice.command, "args": advice.args}
        self.out(f"{advice.reason}\n→ {self.typed(command, advice.args)}")
        # A model chose this, so it gets the care any such choice gets. Agreeing settles the words.
        accepted = self.agree(command)
        cases.record("line", words, answer, "teacher", "accepted" if accepted else "declined",
                     model=self.teacher.model, seconds=meta.get("seconds"))
        self.said, self.last = words, (words, answer)
        if accepted:
            self.answered(words)
            self.run(command, advice.args)
        else:
            self.out("Not run. If that was the wrong command for what you want, say wrong, or say the right one "
                     "with means.")

    def propose(self, advice, words, number):
        """Try a command the teacher wrote, show what was found and install it if the user agrees.
        Returns nothing when that is the end of it, or the proposal and what went wrong with it
        when the user wants the teacher to put it right."""
        proposal, folder = advice.raw["write"], teach.scratch()
        try:
            found = teach.stage(proposal, words, self.teacher, self.table, folder)
            if found.command:
                self.trial(found, proposal, words)
            self.out(teach.show(found, advice))
            if found.command and self.confirm(f"Install {found.command.name}?", default=False):
                name, home = found.command.name, teach.install(found, self.plugin_dir)
                self.table, problems = plugins.load(self.plugin_dir)
                self.out("\n".join(problems + [f"Installed {name} in {home}. Delete that folder to remove it."]))
                self.suggest(name, proposal)
                if number or any(" ".join(entry["line"].split()) == words for entry in proposal["lines"]):
                    self.out(f"Now for what you asked: {words}")    # the words were a request, so carry it out
                    self.interpret(words)
                    self.answered(words)
                return None
            failures = found.failures()
            if failures and self.confirm(f"Not installed. Have {self.teacher.model} put right what went wrong? "
                                         "That is one more call to it.", default=False):
                return proposal, failures
            self.out("Not installed. What it wrote is kept in the state folder, in delegations.jsonl." +
                     (f" Need {number} stays queued." if number else ""))
            return None
        finally:
            shutil.rmtree(folder, ignore_errors=True)

    def trial(self, found, proposal, words):
        """What can be found out about a proposal for free: run its checks in the sandbox, and try
        its descriptions on the student."""
        command, checks = found.command, proposal["checks"][:teach.MOST["checks"]]
        online = not command.hosts or self.confirm(
            f"Its checks would fetch from {', '.join(command.hosts)}. Let them?", default=False)
        self.out(f"Running {len(checks)} check(s) of {command.name} in the sandbox.")
        found.checks = [teach.check(command, wanted, online, self.minds.trial()) for wanted in checks]
        if not self.student:
            found.untried = "No model is set up as the student."
            return
        self.out(f"Trying {min(len(proposal['descriptions']), teach.MOST['descriptions'])} description(s) of it on "
                 f"{self.student.model}.")
        try:
            found.tried = teach.try_descriptions(self.student, self.table, command, proposal)
            teach.settle(found, found.tried[0][0], words, self.teacher, proposal)
        except ModelUnavailable as error:
            found.untried = f"The student did not answer ({error})."

    def suggest(self, name, proposal):
        """A new command may suit a line the user settled before better than the command it is
        remembered for. The lines nearest to the new command are asked of the student again, and
        nothing moves unless the user says so."""
        settled = cases.settled(self.table)
        if not settled or not self.student:
            return
        for line in cases.nearest(list(settled), [entry["line"] for entry in proposal["lines"]]):
            try:
                choice = route.ask(self.student, self.table, line)
            except (ModelUnavailable, RuntimeError):
                return
            if choice.command != name:
                continue
            old = settled[line]["answer"]
            self.out(f"\"{line}\" is remembered as {render(old['command'], old['args'])}. With {name} installed, "
                     f"the student would send it to:\n→ {self.typed(self.table[name], choice.args)}")
            if self.confirm("Remember it that way from now on?", default=False):
                cases.record("line", line, {"command": name, "args": choice.args}, "student", "accepted",
                             model=self.student.model, seconds=choice.meta.get("seconds"))
                self.out("Moved.")
            else:
                self.out("Left as it was.")

    def needs(self):
        waiting = cases.waiting()
        # Asking the teacher again costs a call, so a need it has already turned down says so.
        latest = {call["words"]: call["answer"]["answer"] for call in state.read("delegations") if "answer" in call}
        self.out("\n".join(f"{number}. {need['line']}  ({need['date']}" +
                           ("; the teacher said lo-s cannot do it)" if latest.get(need["line"]) == "cannot" else ")")
                           for number, need in waiting.items())
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
        by = {source: [case for case in lines if case["by"] == source] for source in ("memory", "student", "teacher", "user")}
        told = {verdict: sum(case["verdict"] == verdict for case in by["student"]) for verdict in ("accepted", "declined", "")}
        took = [case["seconds"] for case in by["student"] if case.get("seconds")]
        # What memory saved is counted at the student's usual time for a line. The time a line
        # took when it was first asked may include working out the whole table.
        usual = statistics.median(took) if took else 0
        # Every call to the teacher, whoever asked for it: delegate, rule, or a command with a question of its own.
        calls = {"by delegate": state.read("delegations"), "for rules": state.read("rule_calls"),
                 "by commands": [asked for asked in state.read("asks") if asked["to"] == "teacher"]}
        failed = sum("failed" in call for kind in calls.values() for call in kind)
        judged = cases.judgements()
        made = {source: [case for case in judged if case.get("run") and case["by"] == source]
                for source in ("memory", "rule", "student")}
        self.out(f"Plain-language lines: {len(by['memory']) + len(by['student'])}\n"
                 f"Answered from memory: {len(by['memory'])}, saving about {len(by['memory']) * usual:.1f} s of model time\n"
                 f"Answered by the student: {len(by['student'])}, taking {sum(took):.1f} s "
                 f"({told['accepted']} accepted, {told['declined']} declined, {told['']} where nothing fitted)\n"
                 f"Settled by you with means: {sum(case['verdict'] == 'accepted' for case in by['user'])}\n"
                 f"Taken back with wrong: {sum(case['verdict'] == 'wrong' for case in by['user'])}\n" +
                 (f"Judgements inside commands: {sum(map(len, made.values()))} ({len(made['memory'])} from the record, "
                  f"{len(made['rule'])} by a rule, {len(made['student'])} by the student, taking "
                  f"{sum(case.get('seconds') or 0 for case in made['student']):.1f} s)\n"
                  f"Set by you with trace: {sum(case['by'] == 'user' for case in judged)}\n" if judged else "") +
                 f"Calls to the teacher: {sum(map(len, calls.values()))}" +
                 (f", of which {failed} gave no answer" if failed else "") +
                 (" (" + ", ".join(f"{len(kind)} {how}" for how, kind in calls.items()) + ")"
                  if calls["for rules"] or calls["by commands"] else "") + "\n"
                 f"Needs waiting: {len(cases.waiting())}")

    def trace(self, words):
        """Show the judgements the latest run asked for and where each answer came from, or set
        one of them as the user's own."""
        asked = cases.latest_run()
        if not asked:
            self.out("No command has asked for a judgement yet.")
            return
        if words:
            case = asked[int(words[0]) - 1] if words[0].isdigit() and 1 <= int(words[0]) <= len(asked) else None
            answer = " ".join(words[1:])
            if not case or answer not in case["question"]["choices"]:
                self.out("Usage: trace NUMBER ANSWER, with a number that trace lists" +
                         (f" and one of that judgement's answers: {' or '.join(case['question']['choices'])}."
                          if case else " and one of that judgement's answers."))
                return
            question = case["question"]
            cases.record("judgement", question, answer, "user", "accepted")
            self.out(f"Set: {question['command']} takes {question['name']} of {question['value']} as {answer} from now on." +
                     (f"\nA rule said {case['answer']}. Your answer comes first for this value. If the rule is wrong "
                      f"more widely, rule {question['command']} {question['name']} makes a new one from the record."
                      if case["by"] == "rule" and case["answer"] != answer else ""))
            return
        self.out(f"{asked[0]['question']['command']} asked for {len(asked)} judgement(s) the last time it needed any:")
        for number, case in enumerate(asked, 1):
            question, now = case["question"], cases.judged(case["question"])
            how = {"student": f"the student, {case.get('seconds') or 0:.1f} s", "rule": "a rule",
                   "memory": "on record, set by you" if case.get("source") == "user" else "on record, from the student"}
            self.out(f"{number}. {question['name']} of {question['value']}: {case['answer']}  ({how[case['by']]})" +
                     (f"; you have since set it to {now['answer']}" if now and now["answer"] != case["answer"] else ""))
        other = next(choice for choice in asked[0]["question"]["choices"] if choice != asked[0]["answer"])
        self.out(f"To set one yourself: trace NUMBER ANSWER, such as trace 1 {other}.")

    def rule(self, words):
        """Have the teacher turn the answers on record for one judgement into a rule, try it on
        every one of them, and use it if the user agrees. Every pass through the loop is one call."""
        command = self.table.get(words[0]) if len(words) == 2 else None
        if not command or words[1] not in command.judges:
            known = [f"{name} {one}" for name in sorted(self.table) for one in self.table[name].judges]
            self.out("Usage: rule COMMAND NAME, for a judgement a command asks for" +
                     (f": {', '.join(known)}." if known else ". No command here asks for one."))
            return
        name = words[1]
        if not self.teacher:
            self.out("No model is set up as the teacher. Give the teacher role a provider in los.toml.")
            return
        if os.environ.get("LOS_NO_SANDBOX") != "1" and sandbox.unusable():
            self.out(f"A rule is code a model writes, and it cannot be sandboxed here: {sandbox.unusable()}. "
                     "Set LOS_NO_SANDBOX=1 to have rules run with all of your permissions.")
            return
        try:
            question, choices, listed = rules.recorded(command.name, name)
        except rules.Unsuitable as reason:
            self.out(f"No rule for {name} in {command.name} yet: {reason}.")
            return
        (shown, held), earlier = rules.split(listed), None
        current = rules.installed().get((command.name, name))
        if current:
            self.out(f"A rule for it is in use already, made from {current['cases']} answers on {current['date']}. "
                     "A new one would take its place.")
        while True:
            self.out(f"Asking {self.teacher.model}{' again' if earlier else ''} for a rule from {len(shown)} answer(s) "
                     f"on record for {name} in {command.name}. {len(held)} more are held back to test it.")
            record = {"date": datetime.date.today().isoformat(), "command": command.name, "name": name,
                      "model": self.teacher.model}
            try:
                output, meta = rules.ask(self.teacher, command, name, question, choices, shown, earlier)
            except (ModelUnavailable, RuntimeError) as error:
                state.append("rule_calls", {**record, "failed": str(error)})
                self.out(f"No rule came back: {error}")
                return
            state.append("rule_calls", {**record, "seconds": meta.get("seconds"), "answer": output})
            reason = " ".join(output["reason"].split())
            if output["decision"] == "decline":
                self.out(f"It declined: {reason}")
                return
            code = output["code"].rstrip()
            problems, answered = rules.check(code), 0
            if not problems:
                self.out(f"Trying it on all {len(listed)} in the sandbox.")
                problems, answered = rules.failures(code, shown, held)
            if not problems:
                break
            self.out(f"{code}\n\nWhy: {reason}\nThis rule cannot be used:\n" + "\n".join(f"  - {problem}" for problem in problems))
            if not self.confirm(f"Have {self.teacher.model} put it right? That is one more call to it.", default=False):
                self.out("Not installed. What it wrote is kept in the state folder, in rule_calls.jsonl.")
                return
            earlier = (code, problems)
        self.out(f"{code}\n\nWhy: {reason}\nIt gives the answer on record for all {len(shown)} it was shown. Of the "
                 f"{len(held)} held back, it gives the answer on record for {answered} and leaves {len(held) - answered} "
                 "to the student.")
        if not self.confirm(f"Use this rule for {name} in {command.name}?", default=False):
            self.out("Not installed. What it wrote is kept in the state folder, in rule_calls.jsonl.")
            return
        path = rules.install(command.name, name, question, choices, code, self.teacher, len(listed))
        self.out(f"Installed. {command.name} now asks the rule for {name} before the student, and the student only "
                 f"when the rule has no answer.\nDelete {path} to remove it.")

    def run(self, command, args):
        result = self.runner(command, args, minds=self.minds)
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
                     "command that fits is shown before it runs. A line you accepted is remembered. wrong\n"
                     "takes the latest choice back, and means COMMAND says what the line does mean.\n"
                     "delegate WHAT YOU NEED asks the teacher, which can write a new command; needs lists\n"
                     "what nothing could do yet, and forget NUMBER drops one. trace shows the judgements\n"
                     "the latest command asked for, and rule COMMAND NAME has the teacher turn one into\n"
                     "code. stats counts who answered. help NAME explains a command and says what it may\n"
                     "touch; each runs in a sandbox that holds only that. exit leaves.")
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
            in_force = rules.installed()
            self.out("\n".join([CARE[command.effect]] + plugins.touches(command) + [
                f"A rule answers {one} where it can, made from {in_force[command.name, one]['cases']} answers on "
                f"{in_force[command.name, one]['date']}." for one in command.judges if (command.name, one) in in_force]))


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
    def role(name):
        chosen = config.get("roles", {}).get(name)
        return provider(config["providers"][chosen]) if chosen else None

    shell = Shell(table, student=role("student"), teacher=role("teacher"), plugin_dir=plugin_dir)
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
