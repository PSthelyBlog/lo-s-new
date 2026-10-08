"""Where lo-s keeps what it records: one append-only JSON-lines file per kind of record, and one
data folder per plugin for what its commands keep between runs."""
import json
import os
import pathlib

ROOT = pathlib.Path(__file__).resolve().parent.parent


def directory():
    path = pathlib.Path(os.environ.get("LOS_STATE", ROOT / "state")).absolute()
    path.mkdir(parents=True, exist_ok=True)
    return path


def append(name, record):
    with (directory() / f"{name}.jsonl").open("a") as out:
        out.write(json.dumps(record) + "\n")


def read(name):
    path = directory() / f"{name}.jsonl"
    return [json.loads(row) for row in path.read_text().splitlines()] if path.exists() else []


def data(plugin):
    """The folder the commands of one plugin keep their own records in."""
    path = directory() / "data" / plugin
    path.mkdir(parents=True, exist_ok=True)
    return path
