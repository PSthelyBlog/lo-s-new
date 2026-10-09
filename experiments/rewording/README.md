# Rewording experiment

**Questions.** Memory answers a line only when it is typed word for word. When the user says a
settled line in other words, does the student still give the command and the values they
accepted? And could likeness of wording tell such a line from the same request with another
value, so that something cheaper than the student could answer it?

It was run to decide whether to add an embedding model that matches a typed line to the settled
lines. SPEC.md leaves that out until a measurement asks for one.

## Method

- **The settled lines** are the project owner's own: the 17 lines they accepted, in the first
  build's test copy and in this build, for commands this build's table has. Each comes with the
  command and values they accepted. Those lines are theirs and are not kept here, and neither
  are the answers; these are the counts. `run.py` reads them from a file (`--data`) and writes
  the answers beside it.
- **Rewordings** were written by hand for the trial: for each settled line, three other ways of
  saying it with the same values, and one more in another language. Where a line has a value,
  two or three lines with one value changed were written too, each with the command and values
  that would be right for it.
- The student is asked the way the shell asks (`los/route.py`), each line once and as if new,
  with the shell's own table of 12 commands: the eight starter commands and four the teacher
  wrote. Nothing is sent that turns the server's prompt cache off.
- An answer counts as the same when it would run the same: defaults filled in and paths made
  absolute, as the shell shows a command before it runs. Other values are compared without
  regard to capitals or spacing.
- **Likeness** is the measure lo-s already has (`los/cases.py`): shared character trigrams, with
  no model in it. Each new line is taken for the settled line it is most like, if the two are at
  least so much alike, and given that line's answer.

For a rewording, "the same command and values" is agreement with what the user accepted, which
is a fact. For a line with another value it is agreement with what the trial's author expected,
which is a reference.

## Running it

```
LOS_RUNTIME=/path/to/runtime scripts/serve.sh             # in another terminal
experiments/rewording/run.py --data /path/to/lines.json ask
experiments/rewording/run.py --data /path/to/lines.json report
```

`run.py --help` gives the form of the file.

## Results, 2026-10-09 (Gemma 4 26B-A4B q4_0, llama.cpp b11146, RTX 3070 Laptop 8 GB)

In short:

- **A rewording fares as well as the settled line itself.** The student gave the accepted command
  and values to 60 of 68 rewordings, and to 15 of the 17 settled lines when they were asked as
  if new. That is 88% both times.
- **It never chose another command.** Every miss was no command at all, or the right command with
  another value.
- **The misses sit on two lines**, the two where the user's answer is not the student's. Six of
  the eight rewordings that missed are rewordings of those two.
- **Likeness of wording cannot stand in for the student.** A line with another value is more like
  the settled line than a rewording is, so whatever finds the rewordings also hands the old
  value to the lines that changed it.
- So no embedding model is added. Two cheaper uses of the record would have covered every miss
  here; they are described at the end and are not built.

### What the student gave

| | Lines | Same command | Same command and values | No command | Another command | Median seconds |
|---|---|---|---|---|---|---|
| The settled lines themselves, asked as if new | 17 | 16 | 15 | 1 | 0 | 1.14 |
| The same request and values, in other words | 51 | 47 | 44 | 4 | 0 | 1.07 |
| The same again, in another language | 17 | 16 | 16 | 1 | 0 | 1.11 |
| The same request with another value | 42 | 40 | 39 | 2 | 0 | 1.12 |

- **The two settled lines the student gets wrong as new** are a question about the home folder,
  where it gives `home` for the path and the user had corrected that to `~` with `means`, and a
  question about the temperature in French, which reached `sys.status` when the user accepted
  it and reaches nothing with the table as it is now. The routing experiment saw the same of a
  temperature question once a weather command was added. In the shell both lines are answered
  from memory.
- **Their rewordings go wrong the same way.** All three rewordings of the first got `home` again.
  All three French rewordings of the second reached nothing; its English version reached the
  right command.
- The other two rewordings that missed reached nothing: one way of filing a note, and a request
  to list notes in French.
- Of the lines with another value, two reached nothing (notes of one tag) and one got a folder
  name where a path under the home folder was expected.
- No value was counted as different for its spelling alone, such as a size written another way.
- A line took about 1.1 seconds, and all 127 took two and a half minutes.

### Likeness of wording

| Lines at least this much alike are taken as one | 0.2 | 0.3 | 0.4 | 0.5 | 0.6 |
|---|---|---|---|---|---|
| Rewordings answered rightly from a settled line, of 68 | 57 | 47 | 37 | 21 | 9 |
| Rewordings given another line's answer, of 68 | 1 | 0 | 0 | 0 | 0 |
| Lines with another value given the old value, of 42 | 42 | 39 | 35 | 31 | 23 |

- **There is no level that works.** Asking for lines to be 0.3 alike answers 47 of 68 rewordings
  and gives 39 of the 42 changed lines the old value. At 0.6 it answers 9 and still gets 23
  wrong.
- The reason is in the middle values: a line with another value is 0.62 like its settled line, a
  rewording 0.45, and a rewording in another language 0.22.
- A changed line differs by the one word that matters, and a rewording by all the words that do
  not. A measure of meaning would bring the rewordings closer. It was not tried here, and
  nothing in these numbers suggests it would push the changed lines away.

## What it means

- **Rewording is not what makes the student miss.** It answers a rewording as well as the line
  itself, in about a second. A miss is paid once for each wording, because an accepted rewording
  is remembered as a line of its own.
- **What a rewording loses is the user's correction.** Where the user had to say what a line
  means, the student repeats its mistake on the next wording of it.
- **Matching lines by likeness is unsafe**, and not for want of a better measure: the lines most
  like a settled line are the ones that ask for something else.
- An embedding model is left out. It would need a download, a second server and a third role,
  to answer a kind of line that the records hold two of in 92.

## Two cheaper uses of the record

Both were worked out from the same answers afterwards, so these counts describe this trial and
are not a test of the idea.

- **An answer the user corrected before.** The student gave three rewordings the very command
  and value the user had corrected for another line. The user's correction was right for all
  three. No other line among the 110 new ones got such an answer.
- **A line the student finds nothing for.** For the seven new lines that reached nothing, the
  settled line most alike had the right answer for five and the right command with another
  value for two. Here nothing else is on offer, so a suggestion costs little, and the user can
  correct its values on the line.
- Together they cover all eight rewordings that missed and both changed lines that reached
  nothing, and touch no line the student got right.

## Caveats

- One user's 17 lines, one table, one start of the server, one model.
- The rewordings have one author, who also wrote this, so they may be easier or harder than what
  the user would type. The user's own record holds two rewordings in 92 lines.
- Likeness was tried one way: character trigrams, the nearest settled line, one level for all.
- The settled lines are few. With hundreds, more of them would lie near any new line.
