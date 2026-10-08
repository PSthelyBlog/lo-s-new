# Routing experiment

**Questions.** With the server's prompt cache on, how long does the student take over a line as
the command table grows? And does showing it the user's nearest confirmed lines make its choice
better, or steadier?

## Method

- The lines, the command tables and the teacher's labels are those of the first build's dispatch
  experiment: 100 plain-language lines, a table of 200 commands of which the first 10, 50 or 200
  are shown, and the answer Claude Opus 5.5 gave for each line at each size. `run.py` reads them
  from that folder (`--data`). They are not copied here.
- The student is asked the way the shell asks: the instructions, then the command table, then the
  line, with its answer limited to one command and that command's parameters, or none
  (`los/route.py`). Nothing is sent that turns the server's prompt cache off.
- The server is started the plain way (`scripts/serve.sh`): llama.cpp decides which weights go on
  the GPU.
- **Plain.** The 100 lines in file order, at 10, 50 and 200 commands.
- **Nearest.** The same, but each line is shown with three other lines and the command the
  teacher chose for each, presented as lines this user accepted before. The three are the lines
  that share the most character trigrams with it, among those the teacher chose a command for.
  This is the best case for the idea: the other 99 lines are all on record.
- **Reversed.** The plain run at 50 commands again, last line first, to see how much answers move
  when nothing changes but the order.
- **Steady.** The 50 commands plus one more, six times over. Each added command is one that the
  teacher chose for some line at 200 commands, so it is a near miss for the lines around that
  one. For the 87 lines whose right command is the same at 50 and at 200 commands, the right
  command is the same in all seven tables. The examples in the nearest run carry the labels of
  the table of 50, as a user's confirmed lines would.
- Every answer is saved in `results/`, and `run.py report` prints the tables below from them.

"Same command as the teacher" is agreement with a reference, not correctness. Every run below is
one start of the server.

## Running it

```
LOS_RUNTIME=/path/to/runtime scripts/serve.sh             # in another terminal
experiments/routing/run.py --data /path/to/first-build/experiments/dispatch plain
experiments/routing/run.py --data ... nearest
experiments/routing/run.py --data ... reversed
experiments/routing/run.py --data ... steady
experiments/routing/run.py --data ... report
```

## Results, 2026-10-08 (Gemma 4 26B-A4B q4_0, llama.cpp b11146, RTX 3070 Laptop 8 GB)

In short:

- **Time per line does not grow with the table.** The median is 0.97, 1.12 and 1.06 seconds at
  10, 50 and 200 commands. The table is worked out once and reused for every line after it.
- **The first line after the table changes pays for the table**: 2.3, 3.7 and 9.0 seconds.
- **Nearest confirmed lines do not clearly help, and they cost 0.8 seconds a line.** The student
  picks the teacher's command exactly as often with them as without. They change which lines it
  gets wrong, not how many.
- **They do not make it steadier.** As commands were added, 2 of 87 lines changed command when
  asked plainly and 4 of 87 with nearest lines.
- So the shell does not show them.

### Time per line

| Commands in table | 10 | 50 | 200 |
|---|---|---|---|
| Median seconds per line | 0.97 | 1.12 | 1.06 |
| Mean seconds per line | 0.96 | 1.14 | 1.15 |
| Slowest line, the first apart | 1.42 | 1.54 | 1.50 |
| First line after the table changed | 2.30 | 3.68 | 8.96 |
| Prompt tokens | 403 | 933 | 3,028 |
| Of those, worked out again for a line (median) | 17 | 17 | 13 |
| Same command as the teacher | 91% | 95% | 94% |

- The server keeps what it worked out for the instructions and the table, and works out only
  the line: 13 to 17 tokens of a prompt of 403 to 3,028. That is why the layout puts the line
  last.
- About a second of every line is the answer itself: 31 or 32 tokens at about 42 a second.
- The first build asked with the cache off, to get the same answer every time, and measured
  2.4 seconds a line at 10 commands and about nine at 200.
- Agreement with the teacher is what the first build recorded for the same lines through its
  own shell (91%, 95%, 94%), under another start of the server and another placement of the
  weights.

### The same lines in another order

Asked last line first at 50 commands, all 100 lines got the same command and the same parameters
as before. The first build saw 5 of 116 answers change with the order. Its run mixed prompts
with different beginnings, so the server reused a different amount each time. Here every prompt
starts with the same instructions and table. This is one start and one table, and it says
nothing about the next start.

### Nearest confirmed lines

| Commands in table | 10 | 50 | 200 |
|---|---|---|---|
| Same command as the teacher, asked plainly | 91% | 95% | 94% |
| Same command as the teacher, with nearest lines | 91% | 95% | 94% |
| Same command and same parameters, asked plainly | 44 of 61 | 60 of 76 | 65 of 85 |
| Same command and same parameters, with nearest lines | 42 of 61 | 59 of 76 | 61 of 85 |
| Teacher picked a command, student said none: plainly | 6 of 61 | 3 of 76 | 4 of 85 |
| Teacher picked a command, student said none: with nearest lines | 4 of 61 | 2 of 76 | 3 of 85 |
| Teacher picked a command, student picked another: plainly | 0 of 61 | 1 of 76 | 2 of 85 |
| Teacher picked a command, student picked another: with nearest lines | 1 of 61 | 1 of 76 | 3 of 85 |
| Teacher said none, student ran a command: plainly | 3 of 39 | 1 of 24 | 0 of 15 |
| Teacher said none, student ran a command: with nearest lines | 4 of 39 | 2 of 24 | 0 of 15 |
| Median seconds per line, asked plainly | 0.97 | 1.12 | 1.06 |
| Median seconds per line, with nearest lines | 1.78 | 1.96 | 1.83 |

- **Agreement is the same to the line**, at every size.
- **The lines are not the same ones.** With nearest lines 7, 4 and 8 lines got another command.
  About half of those moved to the teacher's command and half away from it. Since asking in
  another order moved nothing, this is the examples at work and not chance.
- **What they fix is a line answered with nothing.** "remember that the spare key is with Dana"
  and "note: the wifi password is on the fridge" reached `note.add` once a neighbour showed a
  note being taken.
- **What they break is worse.** "put notes.md into the archive folder" went from `fs.move` to
  `fs.copy` at 50 commands and to `fs.archive` at 200. "is the docker container web still
  running", which nothing fits, got `proc.list`. A wrong command is worse than none.
- **Parameters got slightly worse**, not better: 42, 59 and 61 lines with the teacher's values,
  against 44, 60 and 65.
- **Each line takes 0.8 seconds longer.** The examples come after the table, so they are worked
  out for every line: about 80 to 100 tokens more.
- The nearest lines by trigrams are often lines for another command. "write down 'buy oat milk'"
  is nearest to "turn the volume down to 30".

### Steadiness as commands are added

The 87 lines whose right command does not change, asked with the table of 50 and with six tables
of 51. The six added commands are `img.resize`, `pdf.merge`, `cal.list`, `weather.forecast`,
`dict.define` and `docker.ps`.

| | Asked plainly | With nearest lines |
|---|---|---|
| Lines that got more than one command | 2 of 87 | 4 of 87 |
| Answers that are the teacher's command | 593 of 609 | 601 of 609 |

- Asked plainly, the two lines that moved are the two notes above, which went between `note.add`
  and nothing.
- With nearest lines, those two held, and four others moved that had been steady and right:
  "put notes.md into the archive folder" (`fs.copy`, `fs.move`, `fs.archive`), "call this folder
  old-site instead of site", "is firefox running?" and "what's the cpu load like", each of which
  reached nothing under one or two of the tables.
- The eight more answers that match the teacher: three lines gained sixteen between them, and
  those four lost eight. The three are the two notes and "show me the biggest files in my
  downloads folder", which went from `fs.find` to the teacher's `fs.list` in all seven tables.

### The project owner's own lines

The same two ways of asking were tried on the 23 lines the project owner had accepted in the
first build, with their own table of 13 commands and then with a weather command added under
six wordings. Each line was asked as if it were new. Those lines are theirs and are not kept
here; these are the counts.

| | Asked plainly | With nearest lines |
|---|---|---|
| Lines that got more than one command | 1 of 23 | 2 of 23 |
| Answers that are the command they accepted | 155 of 161 | 154 of 161 |

- Asked plainly, one line moved: a question about the machine's temperature reached
  `sys.status` with their own table and nothing under all six wordings of the weather command.
  This is the failure that removed a working weather command four times in the first build.
- With nearest lines the same line reached `sys.status` under four of the six wordings, and
  another line that had been steady reached nothing under five of the seven tables.
- In the shell this line is answered from memory, because it was accepted before. No wording of
  another command can move it.

## What it means

- The student can be served the fast way. Nothing in this build needs the same answer twice,
  and a line costs a second whatever the size of the table.
- A command installed or removed costs one slow line, up to nine seconds at 200 commands.
- Nearest confirmed lines are left out. They settle a few lines and unsettle as many that were
  right, they make the student no steadier, and they nearly double the time per line.
- The lines the student is unsure about are few and specific, such as the two notes. What
  settles one of them is the user accepting it once, after which memory answers.
- Parameters are the weak spot, with or without examples: about one line in five that reaches
  the right command gets values other than the teacher's.

## Caveats

- One start of the server for each run, one machine, one model.
- The lines and the commands have one author, so the lines may be easier than real use.
- The teacher is a reference, not ground truth. Parameter values are compared as lower-cased
  strings, so "2G" and "2 GB" count as different.
- The nearest run is the best case: 99 labelled lines to choose from. A user starts with none.
- One way of choosing neighbours and one way of showing them were tried: three lines by shared
  character trigrams, listed before the line. Another measure, or lines for the same command
  only, might do better.
- The six wordings of the weather command were written by hand for the trial on the owner's
  lines.
