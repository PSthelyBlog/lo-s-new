"""Structured command lines: `plugin.verb --param value ...`."""
import shlex


class UsageError(Exception):
    """The line names a known command but the rest does not fit it."""


def flag(name):
    """A parameter's name as it is typed."""
    return "--" + name.replace("_", "-")


def count(number, noun):
    """A number with its noun, as in "1 check" and "3 checks"."""
    return f"{number} {noun}{'' if number == 1 else 's'}"


def parse(line, table):
    """Return (command, args) when the line starts with a known command name, else None.

    None means the line is not a structured command and should be treated as plain language.
    """
    try:
        words = shlex.split(line)
    except ValueError:  # unbalanced quotes, as in "what's running"
        return None
    if not words or words[0] not in table:
        return None
    command, rest, args = table[words[0]], words[1:], {}
    while rest:
        word = rest.pop(0)
        if not word.startswith("--"):
            raise UsageError(f"{command.name}: expected a --parameter, got {word!r}")
        name, equals, value = word[2:].partition("=")
        name = name.replace("-", "_")
        if name not in command.params:
            raise UsageError(f"{command.name} has no parameter {flag(name)}")
        if not equals:
            if not rest:
                raise UsageError(f"{command.name}: {flag(name)} needs a value")
            value = rest.pop(0)
        args[name] = value
    return command, args


def render(name, args):
    """The typed form of a command, so a choice made by a model reads like something the user
    could have typed."""
    return " ".join([name] + [f"{flag(key)} {_quote(value)}" for key, value in args.items()])


def usage(command):
    """One line showing how to type a command."""
    return " ".join([command.name] + [f"[{flag(key)} VALUE]" for key in command.params])


def _quote(value):
    return value if value and not set(value) & set(" \t\n'\"\\") else shlex.quote(value)
