"""Project commands: how recently each project in a folder was worked on."""
import os
import time

from los import CommandError, judge

STATES = ["active", "dormant", "abandoned"]
QUESTION = "Nothing in a project has changed for this long. Is the project active, dormant or abandoned?"


def _newest(folder):
    """The latest modification time of the folder or of anything beneath it."""
    newest = os.lstat(folder).st_mtime
    for parent, folders, files in os.walk(folder):
        for name in folders + files:
            try:
                newest = max(newest, os.lstat(os.path.join(parent, name)).st_mtime)
            except OSError:
                pass
    return newest


def do_activity(path=None, only=None):
    if not path or not os.path.isdir(path):
        raise CommandError(f"{path} is not a directory")
    only = only.strip().lower() if only else None
    if only and only not in STATES:
        raise CommandError(f"--only is active, dormant or abandoned, not {only!r}")
    now = time.time()
    projects = []   # (whole days since the last change, name); hidden folders are not projects
    for entry in os.scandir(path):
        if entry.is_dir(follow_symlinks=False) and not entry.name.startswith("."):
            days = max(0, int((now - _newest(entry.path)) // 86400))
            projects.append((days, entry.name))
    if not projects:
        return f"{path} has no project folders in it."
    projects.sort()     # most recently changed first
    lines, counts = [], dict.fromkeys(STATES, 0)
    for days, name in projects:
        value = f"{days} days"
        # Where active ends and abandoned begins is the user's opinion, so it is judged, not coded.
        state = judge("activity", QUESTION, value, STATES)
        counts[state] += 1
        if not only or state == only:
            lines.append(f"{state:<10}{value:>10}  {name}")
    lines.append(", ".join(f"{counts[state]} {state}" for state in STATES))
    return "\n".join(lines)
