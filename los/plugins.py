"""Plugins: which commands exist, what each takes and what each may touch.

A plugin is a folder holding `plugin.toml`, which declares its commands, and `commands.py`, which
defines one function `do_<verb>` per command. Several folders may add commands under one plugin
name; a command written by a model lives in a folder of its own, so removing it is one deletion.

The core reads the manifest and parses the code. It never runs the code: a command runs in a
process of its own (see sandbox.py), which is given what the manifest declares and nothing else.

    name = "fs"

    [commands.move]
    description = "Move or rename a file or directory"
    effect = "destructive"              # read (the default), write or destructive
    reads = ["/proc"]                   # fixed paths it may read
    data = "write"                      # its plugin's data folder: read or write

    [commands.move.params]
    sort_by = "name, size or time"      # a hint, for whoever fills the value in
    source = { hint = "what to move", path = "write" }
    path = { hint = "directory", path = "read", default = "." }

A parameter declared as a path is how a command reaches the user's files: the path the user
gives is the one the sandbox holds. The effect is a promise the sandbox keeps. A read command
can change nothing. A write command can change its plugin's data folder. Only a destructive
command can change a path.
"""
import ast
import dataclasses
import keyword
import os
import pathlib
import re
import tomllib

from .parse import flag

EFFECTS = ("read", "write", "destructive")
ACCESS = ("read", "write")
NAME = re.compile(r"[a-z][a-z0-9_]*")


class ManifestError(Exception):
    """A plugin folder cannot be used as it is. The message says what is at fault."""


@dataclasses.dataclass(frozen=True)
class Param:
    hint: str = ""              # for whoever fills the value in, possibly empty
    path: str = ""              # read or write when the value names a file or folder, else empty
    default: str = ""           # for a path: what leaving it out stands for, such as "."


@dataclasses.dataclass(frozen=True)
class Command:
    name: str                   # plugin.verb
    description: str
    params: dict                # parameter name -> Param
    effect: str = "read"        # read, write or destructive
    reads: tuple = ()           # fixed paths it may read
    data: str = ""              # read or write when it uses its plugin's data folder, else empty
    source: pathlib.Path = None  # the commands.py that defines do_<verb>
    written_by: str = ""        # the model that wrote it, when one did

    @property
    def plugin(self):
        return self.name.split(".")[0]

    @property
    def verb(self):
        return self.name.split(".", 1)[1]


def load(directory):
    """Read every plugin under `directory`. Returns the table of commands keyed by name, and one
    sentence for each plugin folder that was left out because its manifest or its code is at fault."""
    table, problems = {}, []
    for manifest in sorted(pathlib.Path(directory).glob("*/plugin.toml")):
        try:
            commands = read(manifest.parent)
            for command in commands:
                if command.name in table:
                    raise ManifestError(f"{command.name} is already defined in {table[command.name].source.parent}")
        except (ManifestError, tomllib.TOMLDecodeError, OSError) as error:
            problems.append(f"{manifest.parent} was left out: {error}")
            continue
        table.update({command.name: command for command in commands})
    return table, problems


def read(folder):
    """The commands one plugin folder declares. The code is parsed, never run."""
    folder = pathlib.Path(folder)
    spec = tomllib.loads((folder / "plugin.toml").read_text())
    plugin = spec.get("name")
    if not isinstance(plugin, str) or not re.fullmatch(r"[a-z][a-z0-9]*", plugin):
        raise ManifestError(f"a plugin name is lower-case letters and digits, not {plugin!r}")
    _only(spec, {"name", "description", "origin", "commands"}, "plugin.toml")
    source = folder / "commands.py"
    if not source.exists():
        raise ManifestError("it has no commands.py")
    try:
        tree = ast.parse(source.read_text())
    except SyntaxError as error:
        raise ManifestError(f"commands.py does not parse: {error.msg} on line {error.lineno}")
    functions = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}
    origin, commands = spec.get("origin", {}), spec.get("commands", {})
    if not isinstance(origin, dict) or not isinstance(commands, dict):
        raise ManifestError("origin and commands are tables")
    return [_command(plugin, verb, entry, functions, source, str(origin.get("written_by", "")))
            for verb, entry in commands.items()]


def _command(plugin, verb, entry, functions, source, written_by):
    name = f"{plugin}.{verb}"
    if not NAME.fullmatch(verb):
        raise ManifestError(f"{name}: a verb is lower-case letters, digits and underscores")
    if not isinstance(entry, dict) or not isinstance(entry.get("params", {}), dict):
        raise ManifestError(f"{name} and its params are tables")
    _only(entry, {"description", "effect", "reads", "data", "params"}, name)
    description, effect = entry.get("description"), entry.get("effect", "read")
    reads, data = entry.get("reads", []), entry.get("data", "")
    if not isinstance(description, str) or not description.strip():
        raise ManifestError(f"{name} needs a description")
    if effect not in EFFECTS:
        raise ManifestError(f"{name}: effect is one of {', '.join(EFFECTS)}, not {effect!r}")
    if not isinstance(reads, list) or not all(isinstance(path, str) and os.path.isabs(path) for path in reads):
        raise ManifestError(f"{name}: reads is a list of absolute paths")
    if data not in ("", *ACCESS):
        raise ManifestError(f"{name}: data is read or write, not {data!r}")
    params = {key: _param(name, key, value) for key, value in entry.get("params", {}).items()}

    # The effect is what the user is told before they agree, so the grants may not exceed it.
    changed = [flag(key) for key, param in params.items() if param.path == "write"]
    if changed and effect != "destructive":
        raise ManifestError(f"{name} is marked {effect} but asks to change {', '.join(changed)}, "
                            "and only a destructive command may change a path")
    if data == "write" and effect == "read":
        raise ManifestError(f"{name} is marked read but asks to change its data folder")

    problem = _signature(functions.get(f"do_{verb}"), params)
    if problem:
        raise ManifestError(f"{name}: commands.py {problem.format(function=f'do_{verb}')}")
    return Command(name, description, params, effect, tuple(reads), data, source, written_by)


def _param(name, key, value):
    if not NAME.fullmatch(key) or keyword.iskeyword(key):
        raise ManifestError(f"{name}: {key!r} cannot be a parameter name")
    if isinstance(value, str):
        return Param(value)
    if not isinstance(value, dict) or set(value) - {"hint", "path", "default"} \
            or not all(isinstance(part, str) for part in value.values()):
        raise ManifestError(f"{name}: parameter {key} is a hint, or a table of hint, path and default")
    param = Param(value.get("hint", ""), value.get("path", ""), value.get("default", ""))
    if param.path not in ("", *ACCESS):
        raise ManifestError(f"{name}: the path of {key} is read or write, not {param.path!r}")
    if param.default and not param.path:
        raise ManifestError(f"{name}: only a path can have a default, and {key} is not declared as one")
    return param


def _signature(function, params):
    """What is wrong with do_<verb> as the code defines it, or nothing."""
    if function is None:
        return "does not define {function}"
    args = function.args
    names = [arg.arg for arg in args.args + args.kwonlyargs]
    if args.posonlyargs or args.vararg or args.kwarg or sorted(names) != sorted(params):
        return "must define {function} with exactly the declared parameters: " + (", ".join(params) or "none")
    if len(args.defaults) != len(args.args) or None in args.kw_defaults:
        return "must give every parameter of {function} a default, because any of them can be left out"
    return None


def _only(table, known, where):
    unknown = sorted(set(table) - known)
    if unknown:
        raise ManifestError(f"{where} has an entry the core does not know: {', '.join(unknown)}")


def touches(command):
    """What a command may touch, in sentences for the user. The sandbox holds it to this."""
    def given(access):
        return ", ".join(flag(name) for name, param in command.params.items() if param.path == access)

    lines = []
    if given("read"):
        lines.append(f"It may read what you give as {given('read')}.")
    if given("write"):
        lines.append(f"It may change or move what you give as {given('write')}.")
    if command.reads:
        lines.append(f"It may read {', '.join(command.reads)}.")
    if command.data:
        lines.append(f"It may read {'and change ' if command.data == 'write' else ''}"
                     f"the data lo-s keeps for the {command.plugin} commands.")
    return lines + ["It sees no other file of yours and has no network."]
