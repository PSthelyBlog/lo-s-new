"""What a command imports from `los`.

A command runs in a sandbox that holds the standard library, the paths the user named for it,
the fixed paths its manifest lists and, if the manifest asks, its plugin's data folder. It reads
and changes those with the standard library as usual. For anything else it asks the core, through
the functions here. The core checks every request against the manifest and what the user typed.

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
