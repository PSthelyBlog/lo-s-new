# lo-s

A personal command line that grows as it is used. You type a command, or you type what you want
in your own words. lo-s starts with a handful of commands. When you ask for something it cannot
do, a strong remote model (the teacher) writes a command for it, once, and from then on that
command is ordinary code on your machine. A small local model (the student) turns plain language
into commands. What either model decides is recorded, and a decision you have confirmed is not
asked of a model again.

At the start most of the machine is missing, and models stand in for the missing parts: the
teacher for the programmer of a command that does not exist yet, the student for the parser of a
line nobody has typed before and for a judgement no code makes yet. Each time a model stands in,
lo-s keeps what it produced and builds the missing part from it. That replacement is how the
system improves itself, and it is meant to be one mechanism.

This is the second build. The first one works and was measured; this one starts over from what
it taught. Each item below is marked **Decided** (chosen by the project owner), **Proposed**
(designed, not yet confirmed by use) or **Open**.

## Decided

- **Decided.** The optimizer's objective: "optimize any aspect, searches for optimization
  opportunities".
- **Decided.** Claude Opus 5.5 is the teacher, through the owner's own `claude` login, and
  "the user should be free to use any provider/model".
- **Decided.** The student is a mixture-of-experts model, loaded in system RAM with the active
  parameters on the GPU.
- **Decided.** The workload is "a plugin based core command line operating system: the core is
  extensible via plugins, the user extends the system on the go from its needs."
- **Decided.** Input is "structured commands with natural language fallback".
- **Decided.** A new need that arises offline is queued for the teacher.
- **Decided.** A user does not have to know lo-s to use it. `delegate`, followed by what they
  need, has the teacher work out what to send. The teacher may be told which models the machine
  is set up with and how they are reached. When the answer is a new command, teaching is offered
  at once.

## Principles

- **Proposed.** A confirmed answer is a fact. A model's answer is a suggestion. Facts are recorded
  and reused. Suggestions are shown to the user or checked before anything relies on them.
- **Proposed.** Nothing depends on a model answering the same way twice.
- **Proposed.** Code does what is mechanical. A model is asked only where judgement is needed,
  through one narrow door, and every answer is recorded.
- **Proposed.** One teacher call returns everything that can then be checked locally for free.
- **Proposed.** What a command may touch is declared, shown to the user in a line or two, and
  enforced by the system. The code is there to read, but approval does not rest on reading it.
- **Proposed.** Every part a model stands in for is handled the same way: the cheapest and surest
  source first, a model last, and what the model said kept as a case from which something
  cheaper can be built.

## Commands and the sandbox

- **Proposed.** A command is named `plugin.verb`. It is a Python function `do_<verb>` in a plugin
  folder, which takes named parameters as strings, returns the text to show, and raises
  `CommandError` with a message the user can act on. A plugin is a folder with `plugin.toml` and
  `commands.py`. A command written by a model lives in a folder of its own, named `plugin.verb`.
- **Proposed.** The core is the only part that touches the host directly. It reads manifests and
  parses code but never runs a command's code itself. Each command runs as a process of its own
  under bubblewrap, with no network, no view of the home folder, a read-only root and an
  environment of its own. It holds:
  - **paths the user named.** A parameter can be declared as a path, for reading or for writing.
    The core makes the value absolute, fills in a declared default such as the current
    directory, and binds that one path into the sandbox at its own absolute path;
  - **fixed paths** the manifest lists, read-only. `/proc` is always a fresh one, never the
    host's, which would show every process of the user;
  - **its plugin's data folder**, when the manifest asks for it, for reading or for writing;
  - `/usr` read-only, the time zone, and a `/tmp` of its own that is gone when the command ends.
- **Proposed.** The command's code is not bound into the sandbox. The core sends it over a socket
  it hands to the process, together with a small module the command imports as `los`. That
  module gives it `CommandError`, `DATA` and the calls below. The same socket carries the
  parameters in and the result out, as JSON lines.
- **Proposed.** A command asks the core for what it cannot do itself. The core checks each
  request against the manifest and what the user typed, and records it in `state/calls.jsonl`,
  refusals included. Built: `move`. Planned: `fetch` a URL on a listed host, `run` a listed
  program outside the sandbox, ask a model.
- **Proposed, and a change from the first design.** A path bound into a sandbox can be read and
  changed in place, but not renamed or removed: that is a change to the folder around it, which
  the command does not hold. Binding that folder would hand over everything else in it. So the
  core moves things, between paths the user named for writing or inside folders they named for
  writing, and it never replaces anything. A link inside such a folder that leads out of it does
  not count.
- **Proposed.** The effect of a command is `read`, `write` or `destructive`, and each is a promise
  the sandbox keeps, not a label:
  - `read` can change nothing that outlasts the run. Its paths and its data folder are read-only.
  - `write` can change its plugin's data folder, and no path.
  - `destructive` can change the paths the user named for writing, and move them through the core.

  A manifest that asks for more than its effect allows is not loaded.
- **Proposed.** A typed command runs as typed. A destructive one asks first.
- **Proposed.** One plugin folder at fault does not stop the shell: it is left out, with a
  sentence that says why.
- **Proposed.** On a machine where bubblewrap cannot build a sandbox, lo-s says so when it starts.
  Commands nobody generated run without one. A command written by a model does not run, unless
  the user sets `LOS_NO_SANDBOX=1`.
- **Open.** How a command creates a path it was given that does not exist yet, such as the copy
  made by a backup command. A file created beside a granted path is refused today, because the
  root is read-only. The proposal: the command builds the new thing in a scratch folder it sees
  at that place, and the core moves it in when the command succeeds. Then `write` could mean
  "adds, and changes nothing that exists".
- **Open.** Removing a named path: a `remove` call like `move`, when a command first needs it.

## Cases and the order of asking

Not built yet.

- **Proposed.** A case is one answered question: what was asked, the answer, who gave it (the
  user, the student, the teacher, a rule) and what the user said about it. Cases are append-only
  JSON lines. There are two kinds of question: which command a line means, and what a named
  judgement inside a command comes to.
- **Proposed.** A typed line is handled in this order:
  1. It is one of the shell's own words.
  2. It parses as a structured command.
  3. The user accepted a command for this exact line before. It is shown as remembered. A read
     command runs at once; anything else asks. This holds for as long as that command exists
     with those parameters, whatever other commands are installed.
  4. The student is asked, with its answer limited to one command and that command's
     parameters, or none. The typed form is shown. Enter accepts a read command; anything else
     needs an explicit yes. Accepting records a confirmed case. Declining records nothing
     lasting. `wrong` takes the latest answer back.
  5. Nothing fits: the line is queued as a need.
- **Proposed.** When a command is installed, remembered lines stay where they are. The ones
  closest to the new command are asked of the student again, as a suggestion only, and the user
  chooses whether to move one.
- **Open.** Whether showing the student the user's nearest confirmed lines as examples makes it
  steadier. To be measured before anything is built on it.

## The teacher step

Not built yet.

- **Proposed.** `delegate WHAT YOU NEED` sends the user's words to the teacher, and
  `delegate NUMBER` a queued need. One call gives one of four answers: **run** a command that
  exists, **write** a new one, **ask** one question, or **cannot**, with the reason.
- **Proposed.** A written command arrives complete: name, candidate descriptions, effect,
  parameters, what it needs granted, code, lines that should reach it, lines that look similar
  and should not, and checks of what it does.
- **Proposed.** Before the user is asked, the core does what is free: it reads the manifest and
  parses the code, runs the checks in the sandbox, and tries each description on the student.
  The user then sees what the command does, what it may touch, how it fared, and the code.
- **Proposed.** Nothing is removed afterwards on a model's say-so. A poor score is information
  for the user, not a gate.

## Judgements

Not built yet.

- **Proposed.** A command that needs a judgement no code makes calls
  `judge(name, question, value, choices)`. The core answers from a recorded answer for that exact
  value, then a rule, then the student limited to the choices, and records the case. `trace`
  shows where each answer came from, and the user can correct one.
- **Proposed.** `rule COMMAND NAME` asks the teacher for a small pure function that reproduces a
  judgement's cases. A quarter are held back to test it. It runs in the sandbox with nothing
  granted.

## Models

Not built yet.

- **Proposed.** One contract for every provider: a system prompt, a user message and a JSON schema
  go in, and a validated dict comes out, with retries. Any provider can fill any role.
- **Proposed.** Claude is reached only by running the user's own `claude` program, with tools off
  and no session kept. lo-s never touches the login.
- **Proposed.** The student is served the simple way: one start, llama.cpp's own placement of the
  weights, prompt cache on, each prompt laid out with the part that does not change first.

## Looking for improvements

Not built yet.

- **Proposed.** A set of small functions over the case log, each finding one kind of opportunity
  and saying what it would save. One shell word lists what they find, largest saving first, with
  what to type for each. The system proposes and the user decides.

## Left out on purpose

- Commands written as plain-language instructions that a model decodes on every run.
- An acceptance check that removes a command, and memory tied to a version of the command table.
- A fixed split of weights, serving with the prompt cache off, a search over server settings.
- An embedding model, or a shortlist of commands for large tables, until a measurement asks for one.
- Anything that spends teacher calls without the user saying so.

## Built so far

Step 1 of five: the core, with no model.

- Manifests and the command table (`los/plugins.py`): parameters with hints, paths and defaults,
  fixed paths, the data folder, the effect, and the check that grants do not exceed it.
- Structured commands (`los/parse.py`), carried over from the first build.
- The sandboxed runner (`los/sandbox.py`, `los/inside/`): the grant for one run, the bubblewrap
  command line, the conversation over the socket, the `move` call and its record.
- The shell (`los/shell.py`, started with `./lo-s`): structured commands, `help`, and
  `help NAME`, which says what a command may touch.
- Seven starter commands in three plugins: `fs.list`, `fs.find`, `fs.usage`, `fs.move`,
  `note.add`, `note.list`, `sys.status`.
- Tests (`python3 -m unittest discover -s tests -t .`) run commands in the real sandbox. They
  show that a command cannot read a file it was not given, sees no home folder and has no
  network; that a read command cannot write, to its path, beside it, to its data folder or
  through the core; that a write command changes its data folder only; and that the core moves
  nothing the user did not name.
- A starter command takes about 41 ms from start to answer on the test machine (median of 20
  runs), against 36 ms for the same process without the sandbox. The rest is Python starting.

## What the first build measured

Its repository holds the method and every recorded answer. In short:

- The student (Gemma 4 26B-A4B) picked the teacher's command on 91% to 95% of 100 lines, with
  tables of 10, 50 and 200 commands, in about a second per line.
- Its answers are not stable. They changed with small rewordings of another command's
  description, with which weights sat on the GPU, and with the server's prompt cache.
- An acceptance check that asked the student the user's remembered lines again failed working
  commands, and each failure had cost a teacher call.
- A new command can be the better answer for an old line, and a catch-all command hides gaps.
