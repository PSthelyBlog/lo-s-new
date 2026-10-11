"""What lo-s says, in parts that each have a voice.

Everything said is text and stays text: each class here is a str, equal to its plain words. The
class tells a terminal how to show the words, and nothing else reads it. Away from a terminal
the words are printed as they are.
"""


class Aside(str):
    """Said beside the point: what could be typed next, or how to undo something."""


class Exact(str):
    """Shown exactly as it is and never broken into lines of another length: a command's own
    output, or code."""


class Fault(str):
    """Something that went wrong."""


class Warn(str):
    """Something to stop and read before answering."""


class Said(str):
    """A text made of parts, each with a voice of its own. It is the parts joined."""

    def __new__(cls, *parts):
        said = super().__new__(cls, "".join(parts))
        said.parts = parts
        return said


def voices(text):
    """A text as [(voice, words)], with the parts of a Said taken apart. The voice is the class
    that says how to show the words, or str for lo-s speaking plainly."""
    if isinstance(text, Said):
        return [one for part in text.parts for one in voices(part)]
    return [(type(text) if type(text) in (Aside, Exact, Fault, Warn) else str, str(text))]
