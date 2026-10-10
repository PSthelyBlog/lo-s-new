# lo-s

lo-s is a personal command line that grows as it is used. You type a command, or you type what
you want in your own words. It starts with a handful of commands. When you ask for something it
cannot do, a strong remote model (the teacher) writes a command for it, once, and from then on
that command is ordinary code on your machine. A small local model (the student) turns plain
language into commands. What either model decides is recorded, and a decision you have confirmed
is not asked of a model again.

**Status: experimental.** It was built and tried on one machine. [SPEC.md](SPEC.md) holds the
design, with every item marked decided, proposed or open, what is built and what was measured.
This is the second build; it starts over from what the first one taught.

## What it looks like

```
lo-s> fs.list
      5B  2026-10-08 22:50  config.yaml
     60B  2026-10-08 22:50  notes/
      6B  2026-10-08 22:50  report.txt
lo-s> how much memory is free
→ sys.status --what memory
Run it? [Y/n/edit]
Memory: 21.5 GB available of 30.8 GB
lo-s> how much memory is free
→ sys.status --what memory  (remembered)
Memory: 21.5 GB available of 30.8 GB
lo-s> rename report.txt to report-final.txt
→ fs.move --source ~/work/report.txt --dest ~/work/report-final.txt
It makes changes that cannot be undone. Run it? [y/N/edit] y
Moved /home/you/work/report.txt to /home/you/work/report-final.txt
lo-s> what takes up the most space in my home folder
→ fs.usage --path ~/work/home
Run it? [Y/n/edit] e
Correct it: fs.usage --path ~
Remembered: "what takes up the most space in my home folder" means fs.usage --path ~.
... the folders and their sizes ...
lo-s> show the biggest folders in my home directory
The student gave fs.usage --path home. You corrected that for "what takes up the most space in my home folder".
→ fs.usage --path ~  (your correction)
Run it? [Y/n/edit]
... the folders and their sizes ...
lo-s> is my machine doing ok
→ sys.health
Run it? [Y/n/edit]
The machine looks healthy: memory 70% free, of 31 GB; temperature 52 °C.
lo-s> trace
sys.health asked for 2 judgements the last time it needed any:
1. memory of 70% free, of 31 GB: fine  (the student, 0.7 s)
2. temperature of 52 °C: fine  (the student, 0.6 s)
To set one yourself: trace NUMBER ANSWER, such as trace 1 worrying.
lo-s> delegate make a backup copy of config.yaml
Asking claude-opus-5-5 about: make a backup copy of config.yaml
Running 5 checks of fs.copy in the sandbox.
Trying 3 descriptions of it on gemma-4-26B-A4B-it-qat-q4_0.gguf.
fs.copy  Copy a file or directory, keeping the original; with no destination it makes a backup copy with .bak added to the name  (effect: write)
  --source  the file or directory to copy
  --dest    new path for the copy, default the source name with .bak added
Why: Nothing in the table copies a file: fs.move would rename config.yaml rather than keep it. ...

It may read what you give as --source.
It may create what you give as --dest, if nothing is there yet.
It sees no other file of yours and has no network.

Checks: 5 of 5 passed.
Lines: with this description the student sent 9 of 10 where they belong. The other descriptions got 8 of 10, 8 of 10.
  - The line "copy the src directory to src.orig" should reach fs.copy, and the student sent it to fs.move.

... the code of the command ...

Install fs.copy? [y/N] y
Installed fs.copy in plugins/fs.copy. Delete that folder to remove it.
Now for what you asked: make a backup copy of config.yaml
→ fs.copy --source ~/work/config.yaml --dest ~/work/config.yaml.bak
Run it? [y/N/edit] y
Copied /home/you/work/config.yaml to /home/you/work/config.yaml.bak
```

The transcript is put together from real runs and shortened, and the folder names are changed.

[showcase/](showcase/README.md) follows one question as it ran, from start to finish: nothing can
answer it, the teacher writes a command, the student makes its judgements, the user says where
their own lines are, the teacher turns that into a rule, and in the end no model is asked.

## How it works

- **Structured commands** have the form `plugin.verb --param value` and run as typed. No model is
  involved, so they work with nothing else set up.
- **Every command runs in a sandbox.** It is a process of its own with no network, no view of
  your home folder and a read-only system. It holds the paths you named on the line, what its
  manifest declares, and nothing else. The line shown before a question is the command in full,
  with every path written out: that line is what will run and all that it can touch.
- **Plain language** goes to the student, which picks one command and fills in its parameters,
  or says that nothing fits. Its choice is shown before anything runs. Enter accepts a command
  that only reads; anything else needs a typed yes. Only `y`, `yes`, `n` and `no` are answers,
  so a line typed too soon is never taken for one.
- **A line you accepted is remembered** and answered without a model from then on, whatever
  other commands are installed later. `wrong` takes a choice back, and `means` lets you say
  yourself what a line means. Answering `e` to the question does that in one go: the command
  is put on the line for you to correct. The student often has the right command with one
  wrong value.
- **What you settled for one line helps with the next.** When the student gives an answer you
  corrected before, your correction is shown in its place, with the line you made it for. When
  the student finds nothing and a settled line is much like the one you typed, that line's
  command is offered, and only a typed yes runs it. The student is still asked first: both act
  on its answer, and neither answers in its place.
- **The prompt keeps your lines and completes them.** Memory answers a line only when it is typed
  word for word, so the lines you type are kept from one session to the next, and Up or Ctrl-R
  brings one back. Tab completes a command, its parameters, a path, and a line you have settled.
- **A line nothing fits is queued as a need.** `delegate`, followed by a need's number or by what
  you want in your own words, asks the teacher. One call gives one of four answers: run a
  command that exists, a new command it wrote, a question for you, or the news that lo-s cannot
  do it.
- **A new command is tried before you are asked.** It arrives with its own checks and example
  lines. lo-s runs the checks in the sandbox and puts the lines to the student, then shows you
  what the command does, what it may touch, how it fared, and the code. Nothing is installed
  unless you agree, and nothing is removed later on a model's say-so.
- **A command can ask for a judgement** that no code makes, such as whether a temperature is
  worrying. The answer comes from what is on record for that exact value, then from a rule, and
  from the student last. `trace` shows where each answer came from and lets you set one, or
  say where a line is: an answer for a value and every one above or below it. What you set you
  can take back.
  `rule` has the teacher turn the answers on record into a small function, which is tried on
  every one of them before you are asked to use it.
- **`improve` lists what the records show could be better**: something you keep asking for, a
  line the student keeps getting wrong, a judgement a rule could make. Each comes with what to
  type and what it costs. lo-s proposes and you decide.

## Try it

You need Linux and Python 3.11 or later. Nothing beyond the standard library is used.

```
./lo-s
```

That is enough for structured commands. `help` lists them, and `help NAME` explains one and says
what it may touch. `./lo-s -c "LINE"` runs one line and exits.

**The sandbox** is made with bubblewrap (the `bwrap` program), which most distributions package.
It was tried with version 0.12.0. Where it is missing or cannot build a sandbox, lo-s says so when
it starts: the starter commands then run without one, and a command a model wrote does not run at
all, unless you set `LOS_NO_SANDBOX=1`.

**The student** is any server that speaks the OpenAI chat API. `scripts/serve.sh` starts
llama.cpp's `llama-server` from a folder you already have:

```
LOS_RUNTIME=/path/to/runtime scripts/serve.sh      # leave running in another terminal
```

That folder holds the llama.cpp build in `llama.cpp/llama-b*/`, its CUDA runtime beside it in
`llama.cpp/cudart-*/`, and the model in `models/`. lo-s downloads nothing. It was built with
Gemma 4 26B-A4B (the q4_0 file, 14.4 GB) on a laptop GPU with 8 GB and about 31 GB of RAM. To use
another model or another server, change `los.toml`.

**The teacher** is reached by running your own `claude` program, which has to be installed and
signed in. It is asked only when you type `delegate` or `rule`, or agree to a question a command
wants to put to it.

## The shell's own words

| Word | What it does |
|---|---|
| `help`, `help NAME` | Lists the commands, or explains one and says what it may touch. |
| `wrong` | Takes back the latest command chosen for a plain-language line. |
| `means COMMAND --param value` | Says what the latest plain-language line means. It is remembered. |
| `needs`, `forget NUMBER` | Lists the lines nothing could do yet, or drops one. |
| `delegate WORDS`, `delegate NUMBER` | Asks the teacher about what you want, or about a queued need. |
| `trace` | Shows the judgements of the latest run and where each answer came from. |
| `trace NUMBER ANSWER` | Sets one of them yourself. Yours comes first from then on. |
| `trace COMMAND NAME` | Shows every answer on record for one judgement. |
| `trace COMMAND NAME VALUE is ANSWER` | Sets the answer for any value. |
| `trace COMMAND NAME from VALUE is ANSWER` | Sets it for that value and every one above it; `up to`, below it. |
| `trace forget NUMBER`, `trace COMMAND NAME forget VALUE` | Takes back what you set, and with `from VALUE` or `up to VALUE` what you set for a stretch. |
| `rule COMMAND NAME` | Asks the teacher to turn a judgement's answers into a rule. |
| `improve`, `improve lines` | Lists what could be better, or checks written commands' example lines. |
| `stats` | Counts who answered what, and the model time that saved. |
| `exit` | Leaves the shell. |

## A command

A plugin is a folder with `plugin.toml` and `commands.py`. The manifest says what each command
takes and what it may touch. This is the whole `note` plugin:

```toml
name = "note"
description = "Short text notes"

[commands.add]
description = "Save a short text note"
effect = "write"
data = "write"
[commands.add.params]
text = "the note"
tag = "one word to file it under"

[commands.list]
description = "List saved notes"
data = "read"
[commands.list.params]
tag = "only notes filed under this word"
```

And this is the part of its `commands.py` that saves a note:

```python
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
```

A command is a function `do_<verb>` that takes its parameters as strings, returns the text to
show, and raises `CommandError` with a message the user can act on. What a manifest can declare:

- `effect`: `read`, `write` or `destructive`. The sandbox holds a command to it: a read command
  can change nothing, a write command can only add, and only a destructive one can change or
  remove what exists. A manifest that asks for more than its effect allows is not loaded.
- a parameter that is a path, with `read`, `create` or `write` access and an optional default.
  The path you give is the one the sandbox holds.
- `reads`: fixed paths it may read, such as `/proc`.
- `data`: its plugin's own folder for what it keeps between runs, for reading or writing.
- `hosts`: hosts it may fetch pages from. The sandbox has no network; the core fetches for it.
- `judges`, `ranges`: the judgements it asks for, and the range a judged value lies in.
- `asks`: the models it may put a question of its own to, `student` or `teacher`.

What a command cannot do itself it asks the core for, with `move`, `remove`, `fetch`, `judge` and
`ask` from `los`. The core checks each request against the manifest and the line you typed, and
records it. The starter plugins in `plugins/` are short enough to read as examples.

## Safety

lo-s runs commands on your real machine.

- A command a model chose is always shown first, in full. One that changes anything never runs
  without a typed yes. Once you have accepted a read command for a line, that line runs it again
  without asking.
- A command holds only what its manifest declares and what you named on the line. Approval of a
  new command does not rest on reading its code, though the code is shown.
- Moving and removing are done by the core, on paths you named. `fs.move` never overwrites.
- The student runs on your machine. `scripts/serve.sh` has it listen on this machine only.
- The teacher is remote. With the default setup it is Anthropic's Claude, through your own
  `claude` login, which lo-s never reads or stores. What is sent to it:
  - by `delegate`: your words, the command table, which models your machine is set up with and
    how they are reached, and one starter plugin as an example. When you send a proposal back,
    also what went wrong with it.
  - by `rule`: the command's name and description, the question, and the answers on record.
  - by a command that asks the teacher: its question, which you are shown before every call.
- Local models make mistakes. In the trials the student sent "copy the src directory to
  src.orig" to `fs.move`. Read the line before you agree to it.
- With `LOS_NO_SANDBOX=1` every command runs with all of your permissions.

This is an experiment and not a security product. The sandbox is bubblewrap's, and nobody has
audited how lo-s uses it.

## Where things are kept

- `state/` holds what the shell records: every answered question (`cases.jsonl`), the queue of
  needs, what commands asked the core for, the teacher's answers, the rules, the lines you
  typed (`history`), and each plugin's data. It is yours and is ignored by git. `LOS_STATE`
  points elsewhere.
- `plugins/` holds the starter commands. A command the teacher wrote lives in a folder of its own
  named `plugin.verb`, with the words it was written for. Deleting the folder removes the
  command. Those folders are ignored by git too. `LOS_PLUGINS` points elsewhere.
- `los.toml` says which provider fills which role. `LOS_CONFIG` points at another file.

Any provider can fill either role. There are two kinds: `openai`, for any server with the OpenAI
chat API, and `claude-cli`, which runs your own `claude` program with tools off and no session
kept.

## What was measured

On one machine, with the student's prompt cache on. The numbers show times and how often the
student agreed with a reference, not that its answers are right.

- A plain-language line takes the student about a second, whether the table holds 10, 50 or 200
  commands. The first line after the table changes takes 2 to 9 seconds.
  [experiments/routing](experiments/routing/README.md) has the method and every recorded answer.
- Showing the student the user's nearest confirmed lines did not clearly help, and is left out.
- A settled line said in other words got the settled command and values from the student for
  60 of 68 rewordings, as often as the settled lines themselves when asked as if new. Matching
  a typed line to the settled ones by likeness is left out: a line with another value is more
  like the settled line than a rewording is. What is built acts on the student's answer
  instead. Replaying the same answers through the shell, 67 of the 68 rewordings are shown the
  settled command and values: 3 more as the user's own correction and 4 as an offer.
  [experiments/rewording](experiments/rewording/README.md) has the method and the counts.
- A judgement takes 0.6 seconds, and a rule answers in 0.04.
- The student's line moves with the wording of a question: over five wordings it found free
  memory worrying only at 1%, or up to 15%. That is why its judgements are shown, can be set by
  hand, and are tested before a rule is made from them.

The "Built so far" section of [SPEC.md](SPEC.md) has the rest, with what each trial used.

## Layout

- `los/shell.py`: the shell and its own words
- `los/terminal.py`: history, completion with Tab, and a line to correct
- `los/plugins.py`, `los/parse.py`: manifests, the command table, structured command lines
- `los/sandbox.py`, `los/inside/`: running a command in the sandbox, and what it can ask the core for
- `los/route.py`, `los/cases.py`: asking the student about a line; the record of answers and needs
- `los/teach.py`: the teacher step and the trial of a new command
- `los/judge.py`, `los/rules.py`: judgements, and rules made from them
- `los/improve.py`: looking for improvements
- `los/models.py`, `los.toml`: providers and roles
- `plugins/`: the starter commands, in `fs`, `note` and `sys`
- `scripts/serve.sh`: starts the student
- `experiments/routing/`: the routing experiment and its results
- `experiments/rewording/`: the rewording experiment; its lines are a user's own and are not kept
- `showcase/`: one question followed from no command to no model, with its transcripts
- `tests/`: run with `python3 -m unittest discover -s tests -t .`

The tests use scripted models and never call a real one. They run commands in the real sandbox,
and those tests are skipped where bubblewrap cannot build one.

## Licence

MIT. See [LICENCE](LICENCE). llama.cpp, the model files and the `claude` program are not part of
this repository and come with their own terms.
