"""Short text notes, kept in the plugin's data folder."""
import datetime
import json
import pathlib

from los import DATA, CommandError

NOTES = pathlib.Path(DATA) / "notes.jsonl"


def do_add(text=None, tag=None):
    if not text:
        raise CommandError("needs --text")
    with NOTES.open("a") as out:
        out.write(json.dumps({"date": datetime.date.today().isoformat(), "text": text, "tag": tag}) + "\n")
    return "Noted."


def do_list(tag=None):
    notes = [json.loads(row) for row in NOTES.read_text().splitlines()] if NOTES.exists() else []
    return "\n".join(f"{note['date']}  {note['text']}" + (f"  [{note['tag']}]" if note["tag"] else "")
                     for note in notes if not tag or note["tag"] == tag) or "No notes."
