"""What a command imports from `los`.

A command runs in a sandbox that holds the standard library, the paths the user named for it,
the fixed paths its manifest lists and, if the manifest asks, its plugin's data folder. It reads
and changes those with the standard library as usual. For anything else it asks the core, through
the functions here: to move or remove a path, to fetch a page, to have a judgement made or to
put a question to a model. The core checks every request against the manifest and what the user
typed.

This file is not part of the core. The core sends its text into the sandbox, where it becomes
the module `los`, and `DATA` and `_core` are filled in.
"""


class CommandError(Exception):
    """The command could not do what was asked. The message is shown to the user as it is, so it
    says what is wrong in terms they can act on."""


DATA = None     # the folder for what this plugin keeps between runs; None unless the manifest asks for it
_core = None    # how the functions below reach the core


def move(source, dest):
    """Move or rename something the user named. A path given to a command can be read and
    changed in place, but renaming or moving it changes the folder around it, which the command
    does not hold, so the core does it.

    `source` is a path the user gave for writing, or something inside a folder they gave for
    writing, and so is `dest`. Nothing is replaced: if `dest` exists, CommandError is raised.
    Only a command whose effect is destructive may call this.
    """
    _core("move", source=str(source), dest=str(dest))


def remove(path):
    """Delete something the user named, a folder with everything in it. `path` is a path the user
    gave for writing, or something inside a folder they gave for writing. Only a command whose
    effect is destructive may call this."""
    _core("remove", path=str(path))


def fetch(url):
    """The text of a page, fetched by the core with an https GET. The sandbox has no network of
    its own. The host has to be one the manifest lists under `hosts`; anything else is refused.
    CommandError is raised when the page cannot be had."""
    return _core("fetch", url=str(url))


def judge(name, question, value, choices):
    """One of `choices` for `value`: a judgement that no code makes, such as whether a reading is
    worrying. `name` is one the manifest lists under `judges`. lo-s answers from what is on record
    for this exact value, then from a rule if one was made, and asks the student last. Every
    answer is recorded, and the user can set one themselves.

    Keep `question` and `choices` fixed and `value` short and regular, such as a number with its
    unit, so that the same value comes round again. CommandError is raised when nobody can answer.
    """
    return _core("judge", name=str(name), question=str(question), value=str(value), choices=[str(one) for one in choices])


def ask(to, message):
    """An answer in free text to a question of the command's own. `to` is "student" or "teacher",
    and has to be listed in the manifest under `asks`. The user is shown every question to the
    teacher and asked before it is sent, because each one is a call they count. CommandError is
    raised when it was not sent or no answer came."""
    return _core("ask", to=str(to), message=str(message))
