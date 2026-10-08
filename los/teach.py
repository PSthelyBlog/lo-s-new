"""The teacher step: what to do about something the user wants, and a new command when none will do.

One call to the teacher gives one of four answers: run a command that exists, write a new one,
ask the user one question, or say that lo-s cannot do it. A written command arrives complete,
with everything that can then be checked here for free: candidate descriptions, lines that
should reach it, lines that should not, and checks of what it does.

The teacher returns text only, and nothing here trusts that text. A proposal is written into a
scratch folder and read back by the same loader as any plugin. Its checks run in the sandbox, in
empty folders. Its descriptions are tried on the student. The user sees what was found and
decides; a poor result is information for them, not a gate.
"""
import dataclasses
import datetime
import json
import os
import pathlib
import shutil
import tempfile

from . import judge, plugins, route, sandbox, state
from .models import complete_valid
from .parse import flag, render

BRIEF = """\
You are the teacher of lo-s, a personal command line that grows as it is used. You know how \
lo-s works so that its user does not have to. You receive what the user wants, in their own \
words, and answer with what lo-s should do about it. You return text only. The user sees your \
answer and agrees before anything runs or is installed.

How lo-s handles a line.
- A command is named plugin.verb and takes named parameters, all optional strings. Typed as \
plugin.verb --param value, it runs directly.
- Any other line is plain language. A small local model, the student, reads the command table \
(each command's name, one-line description and parameters with short hints) and either picks a \
command and fills in its parameters, or says that nothing fits. The user sees its choice in \
typed form and agrees before it runs. A line the user accepted once is remembered and is not \
asked of the student again.
- A line nothing fits is queued as a need, and you are asked about it when the user says so.

Give one of four answers.

"run": a command in the table already does what the user wants. Give its name in command and \
the parameters to send in args, using only the parameters the table lists for it, with values \
taken from the user's words. Leave out what they said nothing about. Do not stretch a command to \
something it does not do: a wrong command is worse than none.

"ask": the user's words leave open something that changes what you would answer. Put one \
question in question. Their answer comes back to you together with their words. Ask only when \
you cannot answer well without it: every question is another call the user waits for.

"cannot": lo-s cannot do it even with a new command. It needs an account, a payment, hardware \
or a service that nothing below provides, or it is something a command cannot be. Say why in a \
sentence or two. If a command in the table does part of it, name that command. Do not offer to \
do something else instead: the user cannot reply to you, and whatever they ask next is a new call.

"write": no command does it, and one can. Give the whole command in write, as described below.

Always give reason: one or two plain sentences for the user, saying why this is the answer.

What a command is. One Python function, do_<verb>, in a module of its own.
- It takes exactly the parameters you declare, as keyword arguments that default to None. The \
values arrive as strings. It returns the text to show the user.
- When it cannot do what was asked, for instance a missing parameter, a value it cannot read or \
a file that is not there, it raises CommandError with a message the user can act on.
- It runs once for a line and ends. It cannot ask the user anything while it runs, hold a \
session open or keep running in the background.
- It uses the standard library, and `from los import ...` for the few things named below. It \
cannot import another plugin.

Where it runs. Every command runs in a sandbox and holds only what its manifest declares. There \
is no network, no home folder and no other file of the user's, and the root is read-only. /tmp \
is private scratch space that is gone when the command ends; use tempfile for it. Declare the \
least that does the job. The user is shown what a command may touch, and that is what they agree to.

- Paths. A parameter can be declared as a path. Its value arrives as an absolute path, and that \
one path is in the sandbox. The folder around it is not: the command cannot list it or see \
anything beside the path. A path is declared in one of three ways.
  - read: the file or folder is there, read-only.
  - create: the command makes something new at this path, where nothing is yet. It creates \
exactly this path with ordinary code (open, shutil.copy2, shutil.copytree, os.mkdir), and the \
user gets it only if the command ends without an error. If something is there already the \
command can see it but not change it: raise CommandError saying that it exists. Nothing can be \
created beside the path, or inside a folder that was given for reading.
  - write: the file or folder is there and may be changed in place: a file rewritten, a folder \
added to or emptied. Only a destructive command may have one. A command cannot rename, move or \
delete a path it was given with os.rename, os.remove or shutil.rmtree: those fail. It asks the \
core instead, with move(source, dest) and remove(path) from los. move never replaces anything.
  A path parameter can have a default, used when the user leaves it out: "." for the current \
directory, or a value built from other parameters in braces, such as "{source}.bak". With no \
default, a path left out arrives as None. A command reaches only paths that are parameters. If \
it needs a second path, such as where a copy goes, that is a parameter too, with a default when \
there is a sensible one.
- reads: fixed absolute paths the command may read whatever the user types, such as /proc.
- data: "read" or "write" gives the command a folder that belongs to its plugin, at the path in \
DATA (from los import DATA), for what it keeps between runs.
- hosts: host names the command may fetch from. fetch(url), from los, returns the text of an \
https GET to a listed host. Anything else is refused, and there is no other network. List only \
the hosts the command needs for what the user asked. Never contact a service to find out where \
the user is or who they are: take a place or a name as a parameter.
- judges: the names of the judgements the command asks for. judge(name, question, value, \
choices), from los, returns the one of choices that fits value. It is for a judgement that no \
code can make, such as whether a reading is worrying, and never for what code can work out. \
lo-s answers from what it has on record for that exact value, then from a rule if one was made, \
and asks the student last. The user can see every answer and set one themselves. Keep question \
and choices fixed text, and value short and regular, such as a number with its unit, so that \
the same value comes round again. No check can know what will be answered, so let none depend \
on it.
- asks: "student", "teacher" or both: the models the command may put a question of its own to. \
ask(to, message), from los, returns the answer as text. It is for a command whose whole purpose \
is to consult a model, such as one that puts the user's question to the student, and not a way \
to have a model do a command's work. Such a command is for lines that name the model, and its \
description must say so, or it becomes a catch-all. The user is shown every question to the \
teacher and asked before it is sent, because each is a call they count. In a check a question to \
the student is answered and one to the teacher is not sent.
- Nothing else exists yet. A command cannot run a program outside the sandbox, send mail or \
open a window. If the need takes one of those, answer cannot and say what is missing.

Effect. read: it changes nothing; it may have read paths and read its data. write: it adds \
something and changes nothing that exists; it may also have create paths and write its data. \
destructive: it changes or removes what exists; it may also have write paths and call move and \
remove. Choose the least that does the job. The user is asked before anything but a read \
command runs.

Write one command for one kind of task, general enough to be used again: give it the \
parameters a user would reasonably vary and no more. Never write a catch-all, a command that \
would take any request, such as one that answers anything or searches for anything. It would \
swallow lines that should become commands of their own. Put the command in an existing plugin \
when it belongs with that plugin's commands. The plugin name is lower-case letters and digits; \
the verb and the parameter names are lower-case letters, digits and underscores. The command's \
name must not be one in the table.

What to give in write.
- plugin, verb, effect, code, and params: each with name and hint, and for a path also path \
and, when there is one, default. reads, data, hosts, judges and asks only when the command \
needs them.
- descriptions: two or three candidate descriptions of one sentence each, worded differently. \
The student sees nothing but the table, so the description and the hints are all it goes by. \
Say what the command is for in words a user would use. Where another command is close, say what \
this one is not for. lo-s tries each on the student and keeps the one that works best.
- lines: five or six different ways a user might ask for this, each with the args the student \
should produce for it. When the user's own words are a request, make them one of the lines.
- others: three or four lines that look similar but belong to another command in the table or \
to no command. For each give that command's name, or "none".
- checks: three to five runs that show the command works. Each has args, the files to set up \
first, whether to expect output or an error, words the text must contain, and in then what \
must be on disk afterwards. In a check every path is relative, and stands in an empty folder \
made for that check. A path in files that ends in a slash is an empty folder. Include a check \
for a wrong or missing parameter. A check of a command that uses fetch contacts the real host \
and runs only if the user allows it, so give at least one check that needs no network.
- code: the full source of the module, short and plain. The user reads it.
"""

TEXT = {"type": "string"}


def _things(required, **properties):
    return {"type": "array", "items": {"type": "object", "additionalProperties": False, "required": required,
                                       "properties": properties}}


ARGS = _things(["name", "value"], name=TEXT, value=TEXT)
SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["answer", "reason"],
    "properties": {
        "answer": {"type": "string", "enum": ["run", "write", "ask", "cannot"]},
        "reason": TEXT,
        "command": TEXT,            # run
        "args": ARGS,               # run
        "question": TEXT,           # ask
        "write": {
            "type": "object", "additionalProperties": False,
            "required": ["plugin", "verb", "descriptions", "effect", "params", "code", "lines", "others", "checks"],
            "properties": {
                "plugin": TEXT, "verb": TEXT,
                "descriptions": {"type": "array", "items": TEXT},
                "effect": {"type": "string", "enum": list(plugins.EFFECTS)},
                "params": _things(["name", "hint"], name=TEXT, hint=TEXT, default=TEXT,
                                  path={"type": "string", "enum": ["", *plugins.ACCESS]}),
                "reads": {"type": "array", "items": TEXT},
                "data": {"type": "string", "enum": ["", "read", "write"]},
                "hosts": {"type": "array", "items": TEXT},
                "judges": {"type": "array", "items": TEXT},
                "asks": {"type": "array", "items": {"type": "string", "enum": list(plugins.ROLES)}},
                "code": TEXT,
                "lines": _things(["line", "args"], line=TEXT, args=ARGS),
                "others": _things(["line", "command"], line=TEXT, command=TEXT),
                "checks": _things(["args", "expect", "contains"], args=ARGS,
                                  files=_things(["path", "content"], path=TEXT, content=TEXT),
                                  expect={"type": "string", "enum": ["output", "error"]},
                                  contains={"type": "array", "items": TEXT},
                                  then=_things(["path", "state"], path=TEXT, content=TEXT,
                                               state={"type": "string", "enum": ["present", "absent"]})),
            },
        },
    },
}
MOST = {"descriptions": 3, "lines": 6, "others": 4, "checks": 6}   # how much of a proposal is tried


@dataclasses.dataclass
class Advice:
    answer: str                 # run, write, ask or cannot
    reason: str
    raw: dict                   # the teacher's answer as it came
    command: str = ""           # run
    args: dict = dataclasses.field(default_factory=dict)
    question: str = ""          # ask


@dataclasses.dataclass
class Found:
    """What trying a proposal showed, for the user and for the teacher if it is asked to revise."""
    command: plugins.Command = None     # the proposal as a command, when it could be read
    folder: pathlib.Path = None         # the plugin folder it was written into
    fault: str = ""                     # why it cannot be read as a plugin, if it cannot
    checks: list = dataclasses.field(default_factory=list)      # (what was run, "" or what went wrong)
    tried: list = dataclasses.field(default_factory=list)       # (description, lines right, lines tried, misses)
    untried: str = ""                   # why the descriptions were not tried on the student

    def failures(self):
        """Everything that went wrong, as sentences."""
        if self.fault:
            return [self.fault]
        return [f"The check {what} {problem}" for what, problem in self.checks
                if problem and not problem.startswith("was not run")] + (self.tried[0][3] if self.tried else [])


def _args(listed):
    return {arg["name"].replace("-", "_"): arg["value"] for arg in listed}


def _line(text):
    return " ".join(str(text).split())


def setup(roles):
    """Which model fills which role, and how a program on this machine reaches it."""
    return "\n".join(f"{role}: {model.describe()}" for role, model in roles.items() if model)


def ask(teacher, words, table, roles, example=None, exchange=(), earlier=None):
    """One call to the teacher about what the user wants. `exchange` holds the questions it asked
    before and the user's answers. `earlier` is a proposal of its own and what was found wrong
    with it, when it is asked to put that right. Returns (advice, what the call took)."""
    system = (BRIEF + "\nThe models this machine is set up with. The student reads plain-language lines; "
              "the teacher is you.\n" + setup(roles) +
              "\n\nCommands, one per line as: name | what it does | parameters\n" + route.table_text(table))
    example = pathlib.Path(example) if example else None
    if example and (example / "commands.py").exists():
        system += ("\n\nAn existing plugin, as an example of the style.\n\nplugin.toml:\n"
                   f"{(example / 'plugin.toml').read_text()}\ncommands.py:\n{(example / 'commands.py').read_text()}")
    user = f"What the user wants: {words}"
    for question, reply in exchange:
        user += f"\n\nYou asked: {question}\nThe user answered: {reply}"
    if earlier:
        proposal, failures = earlier
        user += ("\n\nYou proposed this command for it:\n" + json.dumps(proposal, ensure_ascii=False, indent=1) +
                 "\n\nlo-s tried it, and this is what went wrong:\n" + "\n".join(f"- {failure}" for failure in failures) +
                 "\n\nGive the whole command again with that put right. If a check or a line of yours was at "
                 "fault and not the command, put that right instead.")
    # One try: asking again is another call, and that is for the user to decide.
    output, meta = complete_valid(teacher, system, user, SCHEMA, tries=1)
    answer, advice = output["answer"], Advice(output["answer"], _line(output["reason"]), output)
    if answer == "run":
        command, advice.args = table.get(output.get("command")), _args(output.get("args", []))
        if not command:
            raise RuntimeError(f"it named a command that does not exist: {output.get('command')!r}")
        unknown = sorted(set(advice.args) - set(command.params))
        if unknown:
            raise RuntimeError(f"it gave {command.name} a parameter it does not have: {', '.join(unknown)}")
        advice.command = command.name
    elif answer == "ask":
        advice.question = _line(output.get("question", ""))
        if not advice.question:
            raise RuntimeError("it wanted to ask something and gave no question")
    elif answer == "write" and "write" not in output:
        raise RuntimeError("it chose to write a command and returned none")
    return advice, meta


def manifest(proposal, description, words, teacher):
    """The proposal as the text of a plugin.toml, with one of its descriptions."""
    def quoted(text):
        return json.dumps(_line(text), ensure_ascii=False)      # a JSON string is also a TOML string

    rows = [f"name = {quoted(proposal['plugin'])}", "",
            "[origin]", f"words = {quoted(words)}", f"written_by = {quoted(teacher.model)}",
            f"provider = {quoted(teacher.provider)}", f"date = {quoted(datetime.date.today().isoformat())}", "",
            f"[commands.{proposal['verb']}]", f"description = {quoted(description)}",
            f"effect = {quoted(proposal['effect'])}"]
    rows += [f"{key} = [{', '.join(map(quoted, proposal[key]))}]" for key in ("reads", "hosts", "judges", "asks")
             if proposal.get(key)]
    rows += [f"data = {quoted(proposal['data'])}"] if proposal.get("data") else []
    rows.append(f"[commands.{proposal['verb']}.params]")
    for param in proposal["params"]:
        extra = "".join(f", {key} = {quoted(param[key])}" for key in ("path", "default") if param.get(key))
        rows.append(f"{param['name']} = {{ hint = {quoted(param['hint'])}{extra} }}" if extra
                    else f"{param['name']} = {quoted(param['hint'])}")
    return "\n".join(rows) + "\n"


def scratch():
    """A new empty folder for trying things in. It lies in the state folder and not in /tmp,
    which inside the sandbox is the command's own."""
    home = state.directory() / "scratch"
    home.mkdir(exist_ok=True)
    return pathlib.Path(tempfile.mkdtemp(dir=home))


def stage(proposal, words, teacher, table, into):
    """Write the proposal into `into` as the plugin folder it would be, and read it back the way
    any plugin is read. Returns a Found holding the command, or the reason it cannot be one."""
    names = [proposal["plugin"], proposal["verb"]] + [param["name"] for param in proposal["params"]]
    if not all(isinstance(name, str) and plugins.NAME.fullmatch(name) for name in names):
        return Found(fault="A name in it is not lower-case letters, digits and underscores: "
                           + ", ".join(repr(name) for name in names if not plugins.NAME.fullmatch(str(name))))
    name = f"{proposal['plugin']}.{proposal['verb']}"
    if name in table:
        return Found(fault=f"{name} already exists.")
    if not proposal["descriptions"]:
        return Found(fault="It gave no description.")
    folder = pathlib.Path(into) / name
    folder.mkdir()
    (folder / "plugin.toml").write_text(manifest(proposal, proposal["descriptions"][0], words, teacher))
    (folder / "commands.py").write_text(proposal["code"].rstrip() + "\n")
    (folder / "proposal.json").write_text(json.dumps({"words": words, **proposal}, ensure_ascii=False, indent=1) + "\n")
    try:
        command, = plugins.read(folder)
    except (plugins.ManifestError, ValueError, OSError) as error:      # ValueError: the manifest is not TOML
        return Found(folder=folder, fault=f"It cannot be read as a plugin: {error}.")
    return Found(command, folder)


def _inside(path):
    """Whether a path given in a check stays in the check's own folder."""
    return bool(path) and not os.path.isabs(path) and not path.startswith("~") and ".." not in pathlib.PurePath(path).parts


def check(command, wanted, online, minds=None):
    """Run one of a proposal's checks in the sandbox, in an empty folder made for it. Returns
    (what was run, what went wrong), the second empty when the check passed. `minds` answers what
    the command asks of a model, in the way of a trial: nothing recorded, the teacher not called."""
    args = _args(wanted["args"])
    what = render(command.name, args)
    paths = [file["path"] for file in wanted.get("files", [])] + [after["path"] for after in wanted.get("then", [])]
    paths += [value for name, value in args.items() if name in command.params and command.params[name].path]
    if not all(_inside(path) for path in paths):
        return what, "was not run: a path in it leaves the folder made for the check."
    if set(args) - set(command.params):
        return what, f"names a parameter the command does not have: {', '.join(sorted(set(args) - set(command.params)))}."
    folder = scratch()
    try:
        work = folder / "work"
        work.mkdir()
        for file in wanted.get("files", []):
            place = work / file["path"]
            (place if file["path"].endswith("/") else place.parent).mkdir(parents=True, exist_ok=True)
            if not file["path"].endswith("/"):
                place.write_text(file["content"])
        (folder / "data").mkdir()
        result = sandbox.run(command, args, base=str(work), data=str(folder / "data"), offline=not online, minds=minds)
        said = " ".join(result.text.split())
        said = said if len(said) <= 300 else said[:300] + " ..."
        if sandbox.OFFLINE in result.text:
            return what, "was not run: it needs the network."
        if judge.TRIAL in result.text:
            return what, "was not run: it would call the teacher."
        if result.broke:
            return what, f"broke the command: {said}"
        if wanted["expect"] == "output" and not result.ok:
            return what, f"should have worked and gave an error: {said}"
        if wanted["expect"] == "error" and result.ok:
            return what, f"should have given an error and said: {said}"
        missing = [word for word in wanted["contains"] if word.casefold() not in result.text.casefold()]
        if missing:
            return what, f"should have said {', '.join(map(repr, missing))} and said: {said}"
        for after in wanted.get("then", []):
            place = work / after["path"]
            if os.path.lexists(place) != (after["state"] == "present"):
                return what, f"should have left {after['path']} {after['state']}, and it is not."
            if after["state"] == "present" and "content" in after and place.is_file() \
                    and place.read_text(errors="replace") != after["content"]:
                return what, f"should have left {after['path']} holding {after['content']!r}, and it holds something else."
        return what, ""
    finally:
        shutil.rmtree(folder, ignore_errors=True)


def try_descriptions(student, table, command, proposal):
    """Ask the student the proposal's lines once for each candidate description, with the
    command in the table. Returns one (description, lines that went where they should, lines
    tried, what went astray) per description, the best first."""
    lines = [(_line(entry["line"]), command.name) for entry in proposal["lines"][:MOST["lines"]]]
    lines += [(_line(entry["line"]), None if entry["command"] == "none" else entry["command"])
              for entry in proposal["others"][:MOST["others"]]]
    tried = []
    for description in proposal["descriptions"][:MOST["descriptions"]]:
        with_it = {**table, command.name: dataclasses.replace(command, description=_line(description))}
        right, misses = 0, []
        for line, belongs in lines:
            try:
                reached = route.ask(student, with_it, line).command
            except RuntimeError:        # an answer that fits no command counts as going nowhere
                reached = None
            if reached == belongs:
                right += 1
            else:
                misses.append(f"The line \"{line}\" should reach {belongs or 'no command'}, and the student sent it to "
                              f"{reached or 'no command'}.")
        tried.append((_line(description), right, len(lines), misses))
    return sorted(tried, key=lambda one: -one[1])


def settle(found, description, words, teacher, proposal):
    """Write the description that was kept into the staged manifest."""
    (found.folder / "plugin.toml").write_text(manifest(proposal, description, words, teacher))
    found.command, = plugins.read(found.folder)


def show(found, advice):
    """A proposal as the user sees it before deciding: what it does, what it may touch, how its
    checks and its lines fared, and the code."""
    proposal = advice.raw["write"]
    if found.fault:
        return f"{advice.reason}\nIts command, {proposal['plugin']}.{proposal['verb']}, cannot be installed. {found.fault}"
    command = found.command
    width = max((len(flag(key)) for key in command.params), default=0)
    parts = [f"{command.name}  {command.description}  (effect: {command.effect})"]
    parts += [f"  {flag(key):{width}}  {param.hint}" for key, param in command.params.items()]
    parts += [f"Why: {advice.reason}", ""] + plugins.touches(command) + [""]
    passed = sum(not problem for _, problem in found.checks)
    parts.append(f"Checks: {passed} of {len(found.checks)} passed.")
    parts += [f"  - {what} {problem}" for what, problem in found.checks if problem]
    if found.tried:
        _, right, total, misses = found.tried[0]
        others = ", ".join(f"{score} of {total}" for _, score, _, _ in found.tried[1:])
        parts.append(f"Lines: with this description the student sent {right} of {total} where they belong."
                     + (f" The other descriptions got {others}." if others else ""))
        parts += [f"  - {miss}" for miss in misses]
    else:
        parts.append(f"Lines: not tried on the student. {found.untried}")
    return "\n".join(parts + ["", command.source.read_text().rstrip(), ""])


def install(found, plugin_dir):
    """Move a staged proposal into the plugin folder. Returns where it is now."""
    home = pathlib.Path(plugin_dir) / found.command.name
    if home.exists():
        raise FileExistsError(f"{home} already exists")
    shutil.move(str(found.folder), str(home))
    return home
