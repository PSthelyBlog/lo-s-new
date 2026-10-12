"""Plain language: ask the student which command a line means.

The student is shown the instructions, then the command table, then the line. What stays the
same from one line to the next comes first, so that the server can reuse the work it did on it.
Its answer is limited to one command with that command's own parameters, or none.

A line may also name its command and say the rest in plain words. Which command is meant is
then the user's choice, and the student is asked only for that command's parameters: it is shown
that command alone, and its answer cannot be none.

The answer is a suggestion. The shell shows it and the user decides, and nothing here expects
the student to say the same thing twice.
"""
import dataclasses

from .models import complete_valid

INSTRUCTIONS = """\
You are the dispatcher of a command-line operating system. Users normally type structured \
commands. The line you receive did not parse as one, so it is probably plain language. Decide \
which command from the table, if any, the user meant.

Pick a command only when running it would do what the user asked for. A wrong command is worse \
than no command: when nothing in the table does the job, answer "none", and the request is \
queued so that a new command can be written for it. When several commands could serve, pick \
the most specific one.

For args, use only the parameters listed for the chosen command, take the values from the \
user's line, and leave out parameters the line says nothing about.

Reply with JSON of the form {"call": {"command": "<name>", "args": {"<parameter>": "<value>"}}}, \
or {"call": {"command": "none"}} when nothing fits.

Commands, one per line as: name | what it does | parameters
"""


FILLING = """\
You fill in the parameters of one command of a command-line operating system. The user typed \
the command's name and then said the rest in plain words, which you receive. The command is \
their choice and is not in question: whatever its description says about when to use it, it is \
the command that runs.

For args, use only the parameters listed for the command, take the values from the user's \
words, and leave out parameters the words say nothing about.

Reply with JSON of the form {"call": {"command": "<name>", "args": {"<parameter>": "<value>"}}}.

The command, as: name | what it does | parameters
"""


@dataclasses.dataclass
class Choice:
    command: str | None     # None when the student says nothing in the table fits
    args: dict
    meta: dict              # timing and token counts from the provider


def table_text(table):
    """The command table, one row per command, sorted by name so position carries no hint."""
    rows = []
    for command in sorted(table.values(), key=lambda c: c.name):
        params = ", ".join(f"{name} ({param.hint})" if param.hint else name for name, param in command.params.items())
        rows.append(f"{command.name} | {command.description} | {params}".rstrip(" |"))
    return "\n".join(rows)


def system_prompt(table):
    return INSTRUCTIONS + table_text(table)


def schema(table):
    """One allowed form per command, so the student can only name parameters that command has."""
    def form(properties):
        return {"type": "object", "additionalProperties": False, "required": list(properties),
                "properties": properties}

    forms = [form({"command": {"const": command.name},
                   "args": {"type": "object", "additionalProperties": False,
                            "properties": {name: {"type": "string"} for name in command.params}}})
             for command in sorted(table.values(), key=lambda c: c.name)]
    forms.append(form({"command": {"const": "none"}}))
    return form({"call": {"anyOf": forms}})


def fill(model, command, words):
    """Ask the student for the parameters of a command the user named, from the plain words that
    followed its name. The answer is that command with some of its parameters, and never none."""
    only = schema({command.name: command})
    only["properties"]["call"]["anyOf"].pop()       # the form for none
    output, meta = complete_valid(model, FILLING + table_text({command.name: command}), words, only)
    return Choice(command.name, {name: value for name, value in output["call"]["args"].items() if value.strip()}, meta)


def ask(model, table, line):
    """Ask the student which command the line means."""
    output, meta = complete_valid(model, system_prompt(table), line, schema(table))
    call = output["call"]
    if call["command"] == "none":
        return Choice(None, {}, meta)
    # A parameter the student named but left empty says nothing, so it is not passed on.
    return Choice(call["command"], {name: value for name, value in call["args"].items() if value.strip()}, meta)
