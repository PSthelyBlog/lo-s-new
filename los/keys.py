"""Keys: what a service asks for to know who is calling.

A key belongs to a host. The user gives it, and lo-s keeps it in one file in the state folder
that only they can read. When a command's manifest says that a host wants a key, the core adds
it to each request the command makes there (see sandbox.py). Nothing else reads it: no command
holds a key, no record names one, and no model is shown one.
"""
import json
import os

from . import state


def _file():
    return state.directory() / "keys.json"


def held():
    """The keys the user has given, by host."""
    try:
        kept = json.loads(_file().read_text())
    except (OSError, ValueError):
        return {}
    return kept if isinstance(kept, dict) else {}


def keep(host, key):
    """Keep a key for a host, in place of the one kept before."""
    _write({**held(), host: key})


def drop(host):
    """Forget the key for a host. Returns whether there was one."""
    kept = held()
    if host not in kept:
        return False
    del kept[host]
    _write(kept)
    return True


def _write(kept):
    # Written beside the file and moved over it, and never readable by anyone but the user.
    new = _file().with_suffix(".new")
    with os.fdopen(os.open(new, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600), "w") as out:
        json.dump(kept, out, indent=1)
    os.replace(new, _file())
