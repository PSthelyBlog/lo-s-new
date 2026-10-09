# One question, from nothing to no model

lo-s starts with most of the machine missing, and models stand in for the missing parts: the
teacher for the programmer of a command that does not exist yet, the student for the parser of a
new line and for a judgement no code makes. This page follows one question until all three have
been replaced by something built from what they said:

> which of my projects have I abandoned

No ordinary command answers that, because "abandoned" is an opinion. At the start nothing in lo-s
can do it. At the end the question is answered in 0.64 seconds, in English and in French, with no
model running.

In short:

- **Three calls to the teacher**, of 62, 57 and 6 seconds: two for the command and one for a rule.
- **The teacher's first command was declined.** It settled "abandoned" with a number to pass. The
  second one asks for a judgement instead.
- **The student read the question in two languages** and made the first twelve judgements, each
  in under a second. Its idea of abandoned was not a person's: a project nobody had touched for
  918 days was "dormant".
- **The user said where their own two lines are**, with `trace`. The teacher turned that into a
  few lines of code, tried on every answer on record before it was used.
- **After that the settled lines need no model.** Memory answers the line, the rule answers every
  age, and the command is ordinary code in a sandbox.
- It is one run, by someone who knows lo-s. The last two sections say what was rough.

## The setting

- Run on 2026-10-09 on the machine the main README describes, with Gemma 4 26B-A4B as the student,
  its prompt cache on, and Claude Opus 5.5 as the teacher.
- A fresh state folder, and a copy of the plugin folder with 12 commands in it: the eight starter
  commands and four the teacher had written earlier.
- A made-up home folder. Its `~/Projects` holds twelve folders, last changed from a day to three
  and a half years ago. `projects.py` makes them.
- Time did not pass on its own. "A day on" and "a month on" mean that `projects.py` stamped the
  projects that much older.
- The student was not stopped for the last step. lo-s was pointed at an address where nothing
  answers, which is the same to it.
- The lines were typed one at a time, each after reading the answer to the one before. The steps
  were planned, and rehearsed once with a stand-in for the teacher.

The transcripts are as the terminal showed them, with the scratch folder's path taken out. This
page shows parts of them: output is cut where three dots say so, and not every line typed is
shown. The whole is in `transcript-1.txt`, `transcript-2-a-day-on.txt`, which is the same session
going on, and `transcript-3-a-month-on.txt`.

## 1. Nothing fits

```
lo-s> which of my projects have I abandoned
Nothing here does that yet. It is queued as need 1. delegate 1 asks claude-opus-5-5 about it, and forget 1 drops it.
lo-s> which of my projects have I abandoned
Nothing here does that yet. It is already queued as need 1. delegate 1 asks claude-opus-5-5 about it, and forget 1 drops it.
lo-s> lesquels de mes projets ai-je abandonnés
Nothing here does that yet. It is queued as need 2. delegate 2 asks claude-opus-5-5 about it, and forget 2 drops it.
lo-s> improve
1. You have asked 2 times for something nothing does: "which of my projects have I abandoned".
   delegate 1   (one call to the teacher)
improve lines puts each written command's own example lines to the student again, to see whether they reach it. That is free.
```

The student found no command for the line, so it waits as a need. Asked a second time, it turns up
in `improve`, which says what to type and what that costs. lo-s does not call the teacher by itself.

## 2. The teacher writes a command, and then another

```
lo-s> delegate 1
Asking claude-opus-5-5 about: which of my projects have I abandoned
Running 5 checks of fs.stale in the sandbox.
Trying 3 descriptions of it on gemma-4-26B-A4B-it-qat-q4_0.gguf.
fs.stale  Show which project folders inside a directory have been abandoned: the ones where no file has changed for a long time, longest first; not for finding single old files  (effect: read)
  --path        directory that holds the projects, default the current one
  --older-than  how long untouched counts as abandoned, such as 3 months or 1 year; default 6 months
Why: No command yet looks at when the folders inside a directory were last worked on, so this adds fs.stale. ...

It may read what you give as --path.
It sees no other file of yours and has no network.

Checks: 5 of 5 passed.
Lines: with this description the student sent 10 of 10 where they belong. The other descriptions got 10 of 10, 10 of 10.

... 65 lines of code ...

Install fs.stale? [y/N] n
Not installed. What it wrote is kept in the state folder, in delegations.jsonl. Need 1 stays queued.
```

That call took 62 seconds, and the command works. But it settles what abandoned means with a
number: six months, unless another is passed. That is a fair reading of the bare question. It is
not what was wanted, which is for lo-s to learn where this user's lines are. Nothing is installed
without a yes, so it was left, and the second call said what was wanted:

```
lo-s> delegate say which of my projects are active, dormant or abandoned, going by how long since anything in each one changed. Where those lines fall is my own opinion, so do not fix a number of days in the code and do not make me pass one: have each age judged
Asking claude-opus-5-5 about: say which of my projects are active, dormant or abandoned, ...
Running 5 checks of project.activity in the sandbox.
Trying 3 descriptions of it on gemma-4-26B-A4B-it-qat-q4_0.gguf.
project.activity  Say which projects in a folder are active, dormant or abandoned, going by how long since anything in each one last changed  (effect: read)
  --path  folder that holds the projects, one subfolder each; default the current one
  --only  show only one kind: active, dormant or abandoned; leave out for all
Why: No command sorts projects by how recently they changed: fs.find and fs.list show ages but do not classify them. This new read-only command works out the days since each project folder last changed and has each age judged as active, dormant or abandoned, so where the lines fall is yours to see and set, with no number of days in the code.

It may read what you give as --path.
It sees no other file of yours and has no network.
It asks for a judgement of activity: one of a few answers for a value, from what is on record, a rule or the student. trace shows them.

Checks: 5 of 5 passed.
Lines: with this description the student sent 10 of 10 where they belong. The other descriptions got 10 of 10, 10 of 10.

... 47 lines of code ...

Install project.activity? [y/N] y
Installed project.activity in plugins/project.activity. Delete that folder to remove it.
```

That took 57 seconds. The folder `project.activity` here is the command as it was installed. The
lines of its code that matter:

```python
STATES = ["active", "dormant", "abandoned"]
QUESTION = "Nothing in a project has changed for this long. Is the project active, dormant or abandoned?"

    for days, name in projects:
        value = f"{days} days"
        # Where active ends and abandoned begins is the user's opinion, so it is judged, not coded.
        state = judge("activity", QUESTION, value, STATES)
```

- **One call returned everything that could then be tried for free**: three descriptions, six lines
  that should reach the command, four that should not, and five checks. `proposal.json` has them.
- **lo-s tried it before asking.** The checks ran in the sandbox, in empty folders. The student was
  asked the ten lines once under each description.
- **Its manifest says what it may touch**: the folder you name, and nothing else. It also says that
  it asks for one judgement, of a value between 0 and 3650 days.
- **The sandbox holds it to that.** The code is shown, but agreeing does not rest on reading it.

## 3. Plain words

```
lo-s> which of my projects have I abandoned
→ project.activity --only abandoned --path ~
Run it? [Y/n/edit] e
Correct it: project.activity --only abandoned --path ~/Projects
Remembered: "which of my projects have I abandoned" means project.activity --only abandoned --path ~/Projects.
That answers need 1, so it left the queue.
abandoned  1310 days  lantern
6 active, 5 dormant, 1 abandoned
lo-s> show me the projects I gave up on
The student gave project.activity --only abandoned. You corrected that for "which of my projects have I abandoned".
→ project.activity --path ~/Projects --only abandoned  (your correction)
Run it? [Y/n/edit]
abandoned  1310 days  lantern
6 active, 5 dormant, 1 abandoned
lo-s> lesquels de mes projets ai-je abandonnés
The student gave project.activity --only abandoned. You corrected that for "which of my projects have I abandoned".
→ project.activity --path ~/Projects --only abandoned  (your correction)
Run it? [Y/n/edit]
abandoned  1310 days  lantern
6 active, 5 dormant, 1 abandoned
That answers need 2, so it left the queue.
```

- **The student found the new command** and took `--only abandoned` from the question. It could not
  know which folder holds the projects. The line shown is the command in full, so the mistake is
  there to see: it would have looked at the home folder, where lo-s was started.
- **Answering `e` put the command on the line**, and the folder was added once.
- **The next two wordings got the same answer from the student.** lo-s showed the correction in its
  place and named the line it was made for. Enter ran it, because the command only reads.
- All three lines are remembered from here on, word for word.

## 4. Whose opinion?

```
lo-s> project.activity --path ~/Projects
active        1 days  atlas
active        6 days  birdsong
active       19 days  cellar-map
active       44 days  drift
active       88 days  ember-cli
active      131 days  fathom
dormant     203 days  glasswing
dormant     297 days  harbor-log
dormant     412 days  inkwell
dormant     655 days  juniper
dormant     918 days  kiln
abandoned  1310 days  lantern
6 active, 5 dormant, 1 abandoned
lo-s> trace
project.activity asked for 12 judgements the last time it needed any:
1. activity of 1 days: active  (on record, from the student)
...
11. activity of 918 days: dormant  (on record, from the student)
12. activity of 1310 days: abandoned  (on record, from the student)
To set one yourself: trace NUMBER ANSWER, such as trace 1 dormant.
```

Every one of these is the student's opinion, and `trace` says so. It calls a project active after
131 days without a change, and dormant after 918. It is not steady either: in the rehearsal, under
a question that differed by a few words, it called 88 days dormant.

So the user says where their lines are:

```
lo-s> trace project.activity activity 90 days is active
Set: project.activity takes activity of 90 days as active from now on.
lo-s> trace project.activity activity 91 days is dormant
Set: project.activity takes activity of 91 days as dormant from now on.
lo-s> trace project.activity activity 364 days is dormant
Set: project.activity takes activity of 364 days as dormant from now on.
lo-s> trace project.activity activity 365 days is abandoned
Set: project.activity takes activity of 365 days as abandoned from now on.
lo-s> trace 6 dormant
Set: project.activity takes activity of 131 days as dormant from now on.
lo-s> trace 9 abandoned
Set: project.activity takes activity of 412 days as abandoned from now on.
lo-s> trace 10 abandoned
Set: project.activity takes activity of 655 days as abandoned from now on.
lo-s> trace 11 abandoned
Set: project.activity takes activity of 918 days as abandoned from now on.
lo-s> project.activity --path ~/Projects
active        1 days  atlas
active        6 days  birdsong
active       19 days  cellar-map
active       44 days  drift
active       88 days  ember-cli
dormant     131 days  fathom
dormant     203 days  glasswing
dormant     297 days  harbor-log
abandoned   412 days  inkwell
abandoned   655 days  juniper
abandoned   918 days  kiln
abandoned  1310 days  lantern
5 active, 3 dormant, 4 abandoned
lo-s> trace project.activity activity
On record for activity in project.activity, 16 answers, 8 of them set by you:
  1 to 90 days: active
  91 to 364 days: dormant
  365 to 1310 days: abandoned
To set one yourself: trace project.activity activity VALUE is ANSWER, such as trace project.activity activity 1 days is dormant.
```

- **Four lines say where the two lines are**, by giving the age on each side: three months, and a
  year.
- **Four more overrule the student** where it had answered on the wrong side of them.
- An answer the user sets comes first from then on, before the student and before any rule.

## 5. lo-s proposes the next step

The record answers only an exact age, and tomorrow every project is a day older. The student would
be asked about all twelve again, and would give its own lines again. `improve` sees that:

```
lo-s> improve
1. project.activity has asked the student about activity 12 times, 7.9 s in all. 16 answers are on record, enough for a rule to answer in its place.
   rule project.activity activity   (one call to the teacher)
improve lines puts each written command's own example lines to the student again, to see whether they reach it. That is free.
lo-s> rule project.activity activity
On record for activity in project.activity, 16 answers:
  1 to 90 days: active
  91 to 364 days: dormant
  365 to 1310 days: abandoned
Asking claude-opus-5-5 for a rule from 15 answers on record for activity in project.activity. 1 more is held back to test it.
Trying it on all 16 in the sandbox.
import re

def rule(value):
    # Expects text like "90 days"; anything else goes back to the student.
    if not isinstance(value, str):
        return None
    m = re.fullmatch(r"\s*(\d+) days?\s*", value)
    if not m:
        return None
    days = int(m.group(1))
    if days <= 90:
        return "active"
    if days <= 364:
        return "dormant"
    return "abandoned"

Why: The answers draw two sharp lines: up to 90 days unchanged is active, 91 to 364 days is dormant, and 365 days or more is abandoned. Both boundaries are pinned by the user's own answers (90/91 and 364/365), and the student's answers all agree with them. Three months and one year are sensible cut-offs for this question. The rule returns None for anything not written as a whole number of days.
It gives the answer on record for all 15 it was shown. Of the 1 held back, it gives the answer on record for 1 and leaves 0 to the student.
Use this rule for activity in project.activity? [y/N] y
Installed. project.activity now asks the rule for activity before the student, and the student only when the rule has no answer.
Delete state/rules/project.activity.activity.py to remove it.
```

- **That call took 6 seconds.** The teacher saw the answers on record, with the user's marked as
  theirs, and no file of the user's.
- **The rule was not trusted.** lo-s ran it on all sixteen answers, in a sandbox that holds
  nothing, before asking whether to use it. One answer had been kept from the teacher for that.
- **It is one small file.** Deleting it brings the student back.

## 6. Nothing left to ask

A day on:

```
lo-s> which of my projects have I abandoned
→ project.activity --path ~/Projects --only abandoned  (remembered)
abandoned   413 days  inkwell
abandoned   656 days  juniper
abandoned   919 days  kiln
abandoned  1311 days  lantern
5 active, 3 dormant, 4 abandoned
lo-s> trace
project.activity asked for 12 judgements the last time it needed any:
1. activity of 2 days: active  (a rule)
...
12. activity of 1311 days: abandoned  (a rule)
To set one yourself: trace NUMBER ANSWER, such as trace 1 dormant.
```

Twelve new ages, and all twelve were answered by the rule. A month on, with the student
unreachable:

```
lo-s> lesquels de mes projets ai-je abandonnés
→ project.activity --path ~/Projects --only abandoned  (remembered)
abandoned   442 days  inkwell
abandoned   685 days  juniper
abandoned   948 days  kiln
abandoned  1340 days  lantern
4 active, 4 dormant, 4 abandoned
lo-s> project.activity --path ~/Projects
active       31 days  atlas
active       36 days  birdsong
active       49 days  cellar-map
active       74 days  drift
dormant     118 days  ember-cli
dormant     161 days  fathom
...
lo-s> which projects are still alive
That is not a command, and the student, which reads plain language, did not answer: no answer from http://127.0.0.1:9/v1 ([Errno 111] Connection refused).
If it is the local model, scripts/serve.sh starts it. Structured commands still work; type help to list them.
```

- **No model took part in the first two.** Memory gave the command for the line, the rule judged
  every age, and the command ran in its sandbox.
- **`ember-cli` crossed a line.** It went from 88 days to 118 and is listed as dormant: an age that
  nobody had judged, on the far side of the user's three months.
- **It took 0.64 seconds** from starting lo-s with the line to the answer, three times out of three.
  The first time, the twelve judgements alone took the student 7.9 seconds.
- **A line never typed before still needs the student**, and lo-s says so.

## What was asked of whom

| | Asked | Took |
|---|---|---|
| The teacher, for a command | twice | 62 and 57 seconds |
| The teacher, for a rule | once | 6 seconds |
| The student, to read a line | 6 times | 9.1 seconds in all |
| The student, to judge an age | 12 times | 7.9 seconds in all |
| The student, while the two proposals were tried | 64 times: 60 lines and 4 judgements | not kept |
| Any model, for a settled line once the rule was in | never | 0.64 seconds a line |

And lo-s's own count at the end:

```
lo-s> stats
Plain-language lines: 9
Answered from memory: 3, saving about 3.4 s of model time
Answered by the student: 6, taking 9.1 s (0 accepted, 3 declined, 3 where nothing fitted)
Offered from another line of yours: 2 (2 as your correction of the student's answer, 0 where it found nothing; 2 accepted)
Settled by you with means: 1
Taken back with wrong: 0
Judgements inside commands: 120 (48 from the record and 60 by a rule, saving about 68.0 s; 12 by the student, taking 7.9 s)
Set by you with trace: 8
Calls to the teacher: 3 (2 by delegate, 1 for rules, 0 by commands)
Needs waiting: 0
```

## Where it was rough

- **The bare question did not get a judgement.** The teacher only asked for one when told that the
  lines were a matter of opinion. That cost a second call, and a user has to know to say it.
- **Saying where two lines are took eight `trace` lines.** An answer the user sets says nothing
  about the ages beyond it, so each of the student's answers on the wrong side had to be overruled
  by hand.
- **A rule can leave a stretch open.** In the rehearsal the rule was made from the projects' own
  ages and said nothing between 44 and 88 days. A day later a project stood at 45 days, and the
  student was asked about it. The day after, with the student unreachable, the whole command
  stopped. Giving the age on each side of a line, as in step 4, is what closed it. lo-s does not
  suggest that yet.
- **The student's lines are its own.** They were far from a person's here, and they moved with a
  few words of the question.
- **A new wording still goes to the student.** Only the lines that were accepted are remembered.
- The command writes "1 days".

The second of these has been dealt with since. `trace` now takes `from VALUE` and `up to VALUE`,
for a value and every one above or below it, so step 4 is three lines:

```
trace project.activity activity up to 90 days is active
trace project.activity activity from 91 days is dormant
trace project.activity activity from 365 days is abandoned
```

Replayed on the same projects, those gave the record that the eight lines gave here. They also
answer every age themselves, so no rule was needed and `improve` proposed none: step 5 and its call
to the teacher fall away for a user who knows where their lines are. A month on, with the student
unreachable, the listing took 0.18 seconds. SPEC.md lists the third and fourth as open.

## Caveats

- One run of one question, with one student and one teacher. Asked again, the teacher would write
  something else.
- The projects are made up and their ages were set by hand. The ages the command printed are the
  ages they were made with.
- Whoever typed knew lo-s and had rehearsed. A newcomer would not think of step 4 unaided.
- The times are single measurements. The count of what the student was asked while the proposals
  were tried is worked out from the proposals, since those questions leave no record.

## Running it

```
demo=$(mktemp -d)
cp -r plugins $demo/plugins                  # the commands you have, and room for a new one
showcase/projects.py make $demo/Projects
LOS_STATE=$demo/state LOS_PLUGINS=$demo/plugins ./lo-s
```

Then type the lines above, with the path of `$demo/Projects` where they say `~/Projects`. Your own
records and commands stay out of it: everything the run writes is in `$demo`.

- **It is three calls to your teacher** if it goes as it did here. It will not go quite the same:
  the teacher is asked afresh.
- **To spend none on the command**, copy `showcase/project.activity` into `$demo/plugins/` before
  you start. Steps 3 and 4 then need only the student. The rule in step 5 is still one call.
- **For a day on**, leave lo-s and run `showcase/projects.py age $demo/Projects 1`.
- **For the last step**, stop the student, or give `LOS_CONFIG` a copy of `los.toml` in which the
  student's address has nothing behind it.
