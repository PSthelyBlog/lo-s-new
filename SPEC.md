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
  - **paths the user named.** A parameter can be declared as a path: `read` to see it, `create`
    to make it where nothing is yet, `write` to change what is there. The core makes the value
    absolute and fills in a declared default, which is fixed, such as the current directory, or
    built from other parameters, such as `{source}.bak`. That one path is in the sandbox, at its
    own absolute path, and nothing around it;
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
  refusals included. Built: `move`, `remove`, `fetch`, and the two ways to a model, `judge` and
  `ask` (see Judgements). Planned: `run` a listed program outside the sandbox.
- **Proposed, and a change from the first design.** A path bound into a sandbox can be read and
  changed in place, but not renamed or removed: that is a change to the folder around it, which
  the command does not hold. Binding that folder would hand over everything else in it. So the
  core moves and removes things, on paths the user named for writing or inside folders they
  named for writing. A move never replaces anything. A link inside such a folder that leads out
  of it does not count.
- **Proposed.** Making something new works the other way round. For a path it may create, the
  command is given an empty scratch folder in place of the folder around that path. It builds
  the new thing there with ordinary code. When it ends well the core moves that one thing into
  place, and whatever else it left there is thrown away. If it fails, nothing appears.
- **Proposed.** `fetch` gets a page for a command with an https GET, from a host its manifest
  lists and from no other. A page that sends the request on to another host is refused.
- **Proposed.** The effect of a command is `read`, `write` or `destructive`, and each is a promise
  the sandbox keeps, not a label:
  - `read` can change nothing that outlasts the run. Its paths and its data folder are read-only.
  - `write` can add and cannot change what exists: it may create a path it was given for that,
    and change its plugin's data folder.
  - `destructive` can change what is at the paths the user named for writing, and move or remove
    them through the core.

  A manifest that asks for more than its effect allows is not loaded.
- **Proposed.** A typed command runs as typed. A destructive one asks first.
- **Proposed.** One plugin folder at fault does not stop the shell: it is left out, with a
  sentence that says why.
- **Proposed.** On a machine where bubblewrap cannot build a sandbox, lo-s says so when it starts.
  Commands nobody generated run without one. A command written by a model does not run, unless
  the user sets `LOS_NO_SANDBOX=1`.
- **Open.** A command cannot put something new into a folder that exists, as in "copy this into
  backups": the path it is given to create has to be the new name itself. A default built from
  other parameters covers the usual case.
- **Open.** The scratch folder for a new path is made inside the folder it stands in for, and is
  removed when the command ends. If lo-s is killed in between, a hidden `.los-new-` folder
  stays behind. It holds only what the command was making.

## Cases and the order of asking

- **Proposed.** A case is one answered question: what was asked, the answer, who gave it and what
  the user said about it (accepted, declined or wrong). Cases are appended to
  `state/cases.jsonl` and never changed. There are two kinds of question: which command a line
  means, and what a named judgement inside a command comes to.
- **Proposed.** A typed line is handled in this order:
  1. It is one of the shell's own words.
  2. It parses as a structured command. It runs as typed; a destructive one asks first.
  3. The user accepted a command for this exact line before. It is shown as remembered. A read
     command runs at once; anything else asks. This holds for as long as that command exists
     with those parameters, whatever other commands are installed.
  4. The student is asked, with its answer limited to one command and that command's
     parameters, or none. The typed form is shown. Enter accepts a read command; anything else
     needs an explicit yes. Accepting records a confirmed case. Declining settles nothing,
     because the choice may be right and simply unwanted.
  5. Nothing fits: the line is queued as a need. A need keeps its number for good, and a line
     that is waiting already is not queued a second time.
- **Proposed.** What is shown before a question is the command in full: a path left out is filled
  in, and every path is absolute, with the home folder written as `~`. That line is what will
  run and all that the command can touch. What is remembered is what was said, so a relative
  path in a remembered line points wherever the user is when they type it again.
- **Proposed.** `wrong` takes the latest choice back, whether it ran or not: the line is no longer
  remembered that way, and the shell offers to queue it as a need.
- **Proposed.** When the student gives a line the very answer the user took back for it, the
  answer is shown as one they said was wrong, and Enter no longer runs it. A yes still does,
  and settles the line. Another answer to that line, or the same answer to another line, is
  treated as new.
- **Proposed.** `stats` counts the lines memory answered and the lines the student answered, and
  the model time memory saved.
- **Proposed.** When a command is installed, remembered lines stay where they are. The ones
  closest to the new command are asked of the student again, as a suggestion only, and the user
  chooses whether to move one.
- **Proposed.** The student is not shown the user's confirmed lines as examples. It was measured
  (`experiments/routing/`): with each line's three nearest confirmed lines shown, the student
  picked the teacher's command exactly as often, was no steadier as commands were added, and
  took 0.8 seconds longer over each line.
- **Proposed.** `means COMMAND --parameter value` is the user saying what the latest line means.
  It is recorded as theirs, remembered for that line and run. The student often picks the right
  command with a wrong value, such as `home` for the home folder; this settles such a line
  without a model.
- **Proposed.** A question that takes yes or no is answered by `y`, `yes`, `n` or `no`, and
  Enter gives the default. Anything else may be the next line typed too soon. It is taken for
  neither, and the question is asked again. Before, any answer that began with a y was a yes.
- **Proposed.** At a terminal, the question about a command a model chose takes a third answer,
  `e`. The command is put on the input line for the user to correct, and what they leave is
  recorded and run as `means` would. Left as it was, it counts as a yes. It is offered as the
  model gave it and not in the full form shown above the question: what the user leaves is
  what is remembered, and the full form would write the folder they happen to be in into it.
- **Proposed.** The lines typed at the prompt are kept in `state/history` from one session to the
  next. Memory answers a line only when it is typed word for word, so getting the same words
  back is what makes a line free the second time. Answers to the shell's questions are not
  lines and are kept out.
- **Proposed.** Tab completes what is being typed: a command, its parameters, a path where a
  parameter names one, the shell's own words and what follows them, and a line the user has
  settled, from the word being typed on.
- **Proposed.** A typed line is not matched to the settled lines by likeness, with or without a
  model. It was measured (`experiments/rewording/`): the student gives a rewording the settled
  command and values as often as it gives them to the settled line itself, and a line with
  another value is more like the settled line than a rewording is, so matching hands the old
  value to the lines that changed it.
- **Open.** A rewording of a line the user had to correct gets the student's mistake again.
  Two uses of the record would have covered every such miss in that measurement: showing the
  user's correction when the student gives an answer they corrected for another line, and
  offering the most alike settled line's command when the student finds nothing. They were
  worked out after the fact from the same answers and are not built.
- **Open.** A path with a space in it completes once, written the way the shell reads it, and Tab
  cannot go on inside it.
- **Open.** A line the student finds nothing for is queued without a question, so a typing
  mistake lands in the queue too. `forget` drops it.

## The teacher step

- **Proposed.** `delegate WHAT YOU NEED` sends the user's words to the teacher, and
  `delegate NUMBER` a queued need. One call gives one of four answers: **run** a command that
  exists, **write** a new one, **ask** one question, or **cannot**, with the reason. There is no
  separate step for writing.
- **Proposed.** The teacher is told how lo-s works, the contract for commands, the command
  table, which models fill which role and how they are reached, and one plugin as an example of
  the style. It returns text only.
- **Proposed.** A command to run is shown in full and runs if the user agrees. Agreeing settles
  those words, so that typed plainly later they are answered from memory.
- **Proposed.** A question is put to the user, and their answer goes back with their words in
  another call.
- **Proposed.** A written command arrives complete: name, two or three candidate descriptions,
  effect, parameters, what it needs granted, code, lines that should reach it, lines that look
  similar and should not, and checks of what it does.
- **Proposed.** Before the user is asked, the core does what is free:
  1. It writes the proposal into a scratch folder and reads it back the way any plugin is read.
  2. It runs the checks in the sandbox, each in an empty folder with its own data folder. A check
     gives parameters, files to set up, whether to expect output or an error, words the text
     must contain, and what must be on disk afterwards. Checks of a command that lists hosts
     use the network only if the user allows it.
  3. It asks the student the lines once for each description, with the command in the table,
     and keeps the description under which most lines go where they belong.
- **Proposed.** The user then sees what the command does, what it may touch, how its checks and
  its lines fared, and the code. They decide. Installing writes the plugin folder, with the
  words it was written for, which model wrote it and when, and everything the teacher returned.
- **Proposed.** When the words were a request, it is carried out once the command exists.
- **Proposed.** Nothing is removed afterwards on a model's say-so. A poor score is information
  for the user, not a gate.
- **Proposed.** When something went wrong with a proposal, the user can send it back with what
  was found, for one more call. No call is repeated without the user saying so, and every
  answer is kept in `state/delegations.jsonl`, installed or not.
- **Proposed.** When no answer comes back, the words can be queued as a need to ask again later.
- **Proposed.** A need the teacher answered with cannot stays queued, and `needs` says so beside
  it, because asking again is another call.
- **Proposed.** The teacher is told to give the reason for a cannot in a sentence or two, to name
  a command in the table that does part of it, and to offer nothing else: the user cannot reply
  to it. This wording has not been tried on the teacher yet.
- **Proposed.** The teacher is told never to write a catch-all command, and never to contact a
  service to find out where the user is.

## Judgements

A command reaches a model only through the core, and only as its manifest says. There are two
ways: a judgement, which is a closed question, and a question of the command's own.

- **Proposed.** A command that needs a judgement no code makes calls
  `judge(name, question, value, choices)` and gets one of the choices back. Its manifest lists
  the names under `judges`, and the core refuses any other. A judgement has 2 to 12 answers.
- **Proposed.** The core answers from the surest source and records the case, with the run it was
  asked in:
  1. an answer on record for this exact value: the one the user set, otherwise what the student
     said before;
  2. a rule, if one is in force and it covers the value;
  3. the student, limited to the choices.
- **Proposed.** The record holds for one question only: the same command, name, wording and
  choices. Under another wording an old answer would be an answer to something else.
- **Proposed, and not in the first design.** What a rule answered is recorded but never answered
  from. It is worked out again each time, so removing a rule removes its answers with it.
- **Proposed.** `trace` shows the judgements the latest run asked for and where each answer came
  from. `trace NUMBER ANSWER` sets one as the user's own. It comes first from then on, before a
  rule too.
- **Proposed.** `trace COMMAND NAME` shows every answer on record for one judgement, as stretches
  of values that got the same answer. `trace COMMAND NAME VALUE is ANSWER` sets the answer for
  any value, judged before or not. This is how the user moves the line before a rule is made
  from it.
- **Proposed.** The student is asked with the question and the allowed answers at the start of
  the prompt and the value alone after it. Measured: that is what lets the server reuse its work
  when two kinds of judgement are asked in turn.
- **Proposed.** `rule COMMAND NAME` asks the teacher for a small pure function `rule(value)` that
  reproduces the answers on record for one judgement, and returns nothing for a value they do
  not settle.
  - It needs six different values and two different answers.
  - A command's own runs may never give that: a machine that stays cool only ever has "fine" on
    record. So a manifest can give, under `ranges`, the lowest and highest number a judged value
    can hold. When too little is on record, `rule` offers to put values from across that range
    to the student first, which is free: nine evenly spaced, then up to eight more, each halfway
    between two neighbours that got different answers. Those answers are recorded as the
    student's, in no run. The user then sees the record and is asked before the teacher is.
  - `rule` always shows the record in a few lines before it calls the teacher.
  - A quarter of the answers are held back, spread over the values. An answer the user set is
    never held back, and the teacher is told which ones are the user's.
  - The teacher also judges the answers, and may decline.
  - The function is tried on every answer on record, in a sandbox that holds nothing, once for
    each value. It is refused if it misses an answer it was shown or contradicts one it was not.
  - The user sees the code, the reason and the result, and decides. An approved rule is a file
    in `state/rules/`. Deleting the file removes the rule.
  - A rule that failed can be sent back with what was found, for one more call, if the user
    says so. The teacher is not asked at all when nothing could come of it: too few answers, no
    teacher, or no sandbox to run the rule in.
- **Proposed.** A command whose purpose is to consult a model calls `ask(to, message)` and gets
  the answer as text. Its manifest lists `student`, `teacher` or both under `asks`. A question
  to the student is free. A question to the teacher is a call the user counts: the core shows
  them the question and sends it only on a yes, every time, and the teacher gets one try.
  Questions that were sent are recorded in `state/asks.jsonl`.
- **Proposed.** While a proposal's checks run, a judgement goes straight to the student and
  leaves no record, and a question to the teacher is not sent.
- **Proposed.** The teacher is told about both calls, and that a command which puts a question to
  a model is for lines that name that model.
- **Open.** The student's line depends on how the question is worded. Of five wordings of the
  memory judgement, it found free memory worrying only at 1%, or up to 2%, 8%, 10% or 15%. So a
  judgement the user never looks at stays the student's opinion. `trace` is how it becomes theirs.
- **Open.** The record answers only an exact value, so a command has to round what it has judged.
  `sys.health` judges whole degrees and whole per cent.
- **Open.** A spread varies the first number in a value and nothing else, so a judgement of
  something that is not a number in fixed text cannot be spread.
- **Open.** An answer the user set cannot be handed back to the student. It can only be set again.
- **Open.** A command that asks a model can draw lines that name nobody. In the trial one such
  line of fifteen went to it.

## Models

- **Proposed.** One contract for every provider: a system prompt, a user message and a JSON schema
  go in, and a validated dict comes out, with retries. Any provider can fill any role, and
  `los.toml` says which fills which. There are two roles, `student` and `teacher`. A caller that
  expects a long answer may say how many output tokens to allow.
- **Proposed.** Claude is reached only by running the user's own `claude` program, with tools off
  and no session kept. lo-s never touches the login.
- **Proposed.** The student is served the simple way: one start, llama.cpp's own placement of the
  weights, prompt cache on (`scripts/serve.sh`). Each prompt is laid out with the part that does
  not change first: the instructions, then the command table, then the line.

## Looking for improvements

- **Proposed.** `improve` lists what lo-s could do better, found in its own records, each with
  what to type and what that costs. Nothing is done there: most of it costs a call to the
  teacher, so lo-s proposes and the user decides.
- **Proposed.** Each kind of opportunity has a small function of its own (`los/improve.py`):
  - **a need that keeps being asked**: a waiting line the student found nothing for twice or
    more. What the teacher already turned down is left out.
  - **a line the student keeps getting wrong**: a line it answered twice or more with none of
    its answers standing.
  - **a judgement that deserves a rule**: one the student was asked in a run, when enough is on
    record for a rule; or three times or more, when the manifest gives a range to spread over.
  - **a rule to make again**: one the user has overruled, or one that left the student to answer
    three times or more since it was made while the record grew.
  - **example lines gone astray**: a written command's own example lines that reached it at one
    check and went elsewhere at the next. A line that never reached its command is not raised:
    the user saw that when they installed it.
  - **lines grown slow**: the middle one of the latest twenty lines the student answered took
    more than two seconds. Nothing in lo-s cures that yet; it is the measurement that would ask
    for a shortlist of commands.
- **Proposed, and a change from the first design**, which put the largest saving first. What
  cost the user something comes first: a request that went unanswered, an answer they did not
  take, an answer they had to set against a rule. What only took model time comes after, the
  most first. A second of the student is not noticed, and asking three times for nothing is.
- **Proposed.** Whether example lines still reach their command cannot be read from the records.
  `improve lines` asks the student each written command's lines again, which is free, and
  records where each went. Where they went is also recorded when a command is installed, so the
  first check has something to compare with. A line the user has settled is left out: memory
  answers it, so where the student would send it no longer matters. The first build tested
  exactly those lines.
- **Proposed.** `stats` counts what each source answered and the model time that saved, for lines
  and for judgements.
- **Open.** A line gone astray has no cure but `means` for that one line. The candidate
  descriptions the teacher gave with a command could be tried again for free; that is not built.
- **Open.** Needs are counted by their exact words, so two wordings of one need are two needs.
- **Open.** The thresholds (twice, three times, two seconds) are guesses. Only model time is
  measured, not the user's.

## Left out on purpose

- Commands written as plain-language instructions that a model decodes on every run.
- An acceptance check that removes a command, and memory tied to a version of the command table.
- A fixed split of weights, serving with the prompt cache off, a search over server settings.
- An embedding model, or a shortlist of commands for large tables, until a measurement asks for one.
  For matching a typed line to the settled lines, one was made (`experiments/rewording/`) and
  it does not ask for one.
- Anything that spends teacher calls without the user saying so.

## Built so far

All five steps: the core, plain language, the teacher step, judgements, and looking for
improvements.

- Manifests and the command table (`los/plugins.py`): parameters with hints, paths and defaults,
  fixed paths, the data folder, the effect, and the check that grants do not exceed it.
- Structured commands (`los/parse.py`), carried over from the first build.
- The sandboxed runner (`los/sandbox.py`, `los/inside/`): the grant for one run, the bubblewrap
  command line, the conversation over the socket, the `move` call and its record.
- The shell (`los/shell.py`, started with `./lo-s`): structured commands, `help`, and
  `help NAME`, which says what a command may touch.
- Eight starter commands in three plugins: `fs.list`, `fs.find`, `fs.usage`, `fs.move`,
  `note.add`, `note.list`, `sys.status`, and `sys.health`, which has each reading judged.
- Tests (`python3 -m unittest discover -s tests -t .`) run commands in the real sandbox. They
  show that a command cannot read a file it was not given, sees no home folder and has no
  network; that a read command cannot write, to its path, beside it, to its data folder or
  through the core; that a write command changes its data folder only; and that the core moves
  nothing the user did not name.
- A starter command takes about 41 ms from start to answer on the test machine (median of 20
  runs), against 36 ms for the same process without the sandbox. The rest is Python starting.
- Providers and roles (`los/models.py`, `los.toml`), carried over from the first build. Only the
  student is used so far.
- Routing (`los/route.py`): the student is shown the instructions, the table and then the line,
  and answers with one command and its own parameters, or none.
- Cases and needs (`los/cases.py`): every answer to a plain-language line is recorded with what
  the user said about it. An accepted line is answered from memory whatever else is installed.
- In the shell: the order of asking, the full form before every question, `wrong`, `needs`,
  `forget NUMBER` and `stats`.
- `scripts/serve.sh` starts the student from a llama.cpp build and a model the user already has.
- Tests use a scripted student and never call a real model.
- Measured on the student (`experiments/routing/`), with the prompt cache on: a line takes about
  a second whether the table holds 10, 50 or 200 commands, and the first line after the table
  changes takes 2 to 9 seconds. Nearest confirmed lines did not clearly help and are left out.
- Paths a command may create, defaults built from other parameters, and the `remove` and
  `fetch` calls (`los/sandbox.py`).
- The teacher step (`los/teach.py`, `delegate` in the shell): the four answers, the trial of a
  proposal, installing, sending a proposal back, and suggestions for remembered lines.
- `means`, and two corrections: `wrong` names what it takes back in full, and `stats` counts what
  memory saved at the student's usual time for a line.
- After the owner's own trial of the teacher step: an answer taken back is marked when the
  student gives it again, a declined choice points to `means` as well as `wrong`, and `needs`
  marks what the teacher has already said cannot be done.
- Tried on 2026-10-08 on the owner's four requests, in scratch folders, with four teacher calls.
  "order a large pizza" got cannot. The other three each got a command in one call: `fs.copy`,
  `fs.delete` and `weather.forecast`. Each passed all five of its own checks the first time, and
  9, 10 and 9 of their 10 lines went where they belong under the description that was kept. The
  weather command listed two hosts of one forecast service and fetched from no other. With it
  installed, a question about the temperature that the owner had accepted before was still
  answered from memory as `sys.status`; asked afresh, the student alone sent it nowhere.
- Judgements (`los/judge.py`, the `judge` and `ask` calls in `los/sandbox.py`): the order of
  answering, the record, a command's own question to the student or the teacher. In the shell:
  `trace`, `trace NUMBER ANSWER`, and the judgements in `stats`.
- Rules (`los/rules.py`, `rule COMMAND NAME` in the shell): which answers can become a rule, what
  the teacher is shown, the trial of its code in a sandbox that holds nothing, and installing.
- Measured on the student on 2026-10-08, with the prompt cache on and one start of the server.
  These are times and the student's own answers, not a check that the answers are right.
  - A judgement takes 0.6 seconds once its question has been asked before, and 1.6 the first time.
  - With the instructions at the start of the prompt and the question after them, two kinds of
    judgement asked in turn took 1.5 seconds each, because the server worked the whole prompt
    out again. With the question at the start, 0.6.
  - A routed line asked after judgements was no slower than before them.
  - Asked about temperatures from 30 to 105 °C in steps of five, the student called everything up
    to 80 °C fine and everything from 85 °C worrying.
  - A rule answers in 0.04 seconds.
- Tried on 2026-10-08 in scratch folders, with two teacher calls.
  - `rule sys.health temperature`, from 17 answers of the student: one call of 8 seconds gave a
    rule that says fine up to 80 °C, worrying from 85 °C and nothing in between. It gave the
    answer on record for all 13 it was shown and all 4 held back. Afterwards new temperatures
    were answered by the rule, and the ones between 80 and 85 °C by the student.
  - "ask the student what a mutex is": one call of 28 seconds gave `student.ask`, which lists
    the student only. It passed its 4 checks, 9 of its 10 lines went where they belong, and the
    request was then carried out. With it installed, 3 of 17 other lines went somewhere new: the
    two that name the student, and "what is a semaphore", which names nobody.
- Looking for improvements (`los/improve.py`, `improve` and `improve lines` in the shell): the
  finders, their order, and the check of example lines.
- For a rule: `ranges` in a manifest, the spread of values put to the student, the record shown
  before the call, and `trace COMMAND NAME` to see it and set any value.
- Tried on 2026-10-08 on the student, in scratch folders, with no teacher call.
  - From one real reading each, the spread found where the student draws its line in 12 and 13
    questions of about 0.6 seconds: free memory worrying up to 13% and fine from 14%, a
    temperature fine up to 82 °C and worrying from 83 °C. These are the student's answers, not
    a check that they are right.
  - `improve lines` put 24 example lines of four written commands to the student. 23 reached
    their command. "copy the src directory to src.orig" went to `fs.move`, as it had when
    `fs.copy` was first tried, so nothing had changed.
- Not tried on the teacher yet: what it is told about `ranges`.
- Line editing (`los/terminal.py`): history kept in the state folder, completion with Tab, and a
  command put on the line to correct. In the shell: `e` as an answer about a command a model
  chose, and questions that take only a clear yes or no.
- Tried on 2026-10-09 in a pseudo-terminal, with the student and a scratch state folder. The
  student gave `home` for the home folder, `e` put its command on the line, and the corrected
  command was remembered and run. Up then brought the line back and not the `e`, and memory
  answered it. Tab completed a command, a parameter and a path. "yes but later" at a question
  about a destructive command was asked again and not taken for a yes.
- The owner's own trial the same day, at their prompt and with their own record, went the same
  way, and the history was there again after leaving and starting anew. One thing it showed: a
  Tab listing gives each path in full and not the name alone, which is wide in a deep folder.
- Measured on 2026-10-09 on the student (`experiments/rewording/`), with the prompt cache on and
  no teacher call: 17 lines the project owner had settled, 68 rewordings of them and 42 lines
  with one value changed, each asked once as if new.
  - The student gave the settled command and values to 60 of 68 rewordings and to 15 of the 17
    settled lines themselves, and never another command. This is agreement with what the user
    accepted.
  - Six of the eight rewordings that missed are rewordings of the two lines where the user's
    answer is not the student's.
  - Taking lines that share enough character trigrams as one answers 47 of 68 rewordings at one
    level and gives 39 of the 42 changed lines the old value.

## What the first build measured

Its repository holds the method and every recorded answer. In short:

- The student (Gemma 4 26B-A4B) picked the teacher's command on 91% to 95% of 100 lines, with
  tables of 10, 50 and 200 commands, in about a second per line.
- Its answers are not stable. They changed with small rewordings of another command's
  description, with which weights sat on the GPU, and with the server's prompt cache.
- An acceptance check that asked the student the user's remembered lines again failed working
  commands, and each failure had cost a teacher call.
- A new command can be the better answer for an old line, and a catch-all command hides gaps.
