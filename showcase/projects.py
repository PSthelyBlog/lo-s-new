#!/usr/bin/env python3
"""Make the folder of made-up projects the showcase was run on, or make it older.

  projects.py make FOLDER        make FOLDER with twelve project folders in it, last changed from
                                 a day to three and a half years ago
  projects.py age FOLDER DAYS    stamp them DAYS days older than they are made, as if that many
                                 days had passed

Every file and folder of a project carries the project's age, because a command may go by either.
An hour is added, so that the count of whole days does not tip over while a session runs. Only a
folder this script made is ever stamped.
"""
import os
import pathlib
import sys
import time

PROJECTS = {"atlas": 1, "birdsong": 6, "cellar-map": 19, "drift": 44, "ember-cli": 88, "fathom": 131,
            "glasswing": 203, "harbor-log": 297, "inkwell": 412, "juniper": 655, "kiln": 918, "lantern": 1310}
MARK = ".made-up-projects"      # what tells a folder made here from one of the user's own


def age(folder, shift):
    now = time.time()
    for name, days in PROJECTS.items():
        when = now - (days + shift) * 86400 - 3600
        for here, _, files in os.walk(folder / name):
            for file in files:
                os.utime(os.path.join(here, file), (when, when))
            os.utime(here, (when, when))


def main(argv):
    if len(argv) not in (2, 3) or argv[0] not in ("make", "age") or (argv[0] == "make") != (len(argv) == 2):
        sys.exit(__doc__.strip())
    folder = pathlib.Path(argv[1]).expanduser()
    if argv[0] == "make":
        if folder.exists():
            sys.exit(f"{folder} exists already. Give a folder that is not there yet.")
        for name in PROJECTS:
            (folder / name / "src").mkdir(parents=True)
            for file in ("README.md", "notes.txt", "src/main.py"):
                (folder / name / file).write_text(f"{name}\n")
        (folder / MARK).write_text("Made by showcase/projects.py. Nothing in here is a real project.\n")
        age(folder, 0)
        print(f"Made {len(PROJECTS)} projects in {folder}.")
    else:
        if not (folder / MARK).exists():
            sys.exit(f"{folder} was not made by this script, so it is left alone.")
        try:
            shift = int(argv[2])
        except ValueError:
            sys.exit(f"DAYS is a whole number, not {argv[2]!r}")
        age(folder, shift)
        print(f"The projects in {folder} are now {shift} days older than they were made.")


if __name__ == "__main__":
    main(sys.argv[1:])
