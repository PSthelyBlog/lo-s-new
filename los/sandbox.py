"""Running a command: a process of its own, in a sandbox that holds only what the command was granted.

The core is the only part of lo-s that touches the host directly. A command's code runs under
bubblewrap, with no network, no view of the home folder and a read-only root. What it sees beyond
/usr is a grant, worked out for each run from the command's manifest and the line the user typed:

- the paths the user named in parameters declared as paths, each at its own absolute path, for
  reading or for writing as the manifest says;
- the fixed paths the manifest lists, for reading;
- its plugin's data folder, if the manifest asks for it;
- a /tmp of its own, which is gone when the command ends.

The command and the core talk over one socket, in JSON lines. The first line carries the code to
run and its parameters, and the last says how it ended. In between, the command can ask the core
for what it cannot do itself. Each request is checked against the grant and recorded.

A path bound into the sandbox can be read and changed in place, but not renamed or removed: that
changes the folder around it, which the command does not hold. Giving it that folder would give
it everything else in there too. So the core does it: `move` and `remove`, on paths the user
named. `fetch` gets a page from a host the manifest lists, since the sandbox has no network.
`judge` and `ask` are the one way to a model: a judgement the manifest names, or a question of
the command's own to a model the manifest lists. Who answers is decided outside this module,
by whatever started the run.

Making something new works the other way round. For a path the command may create, it is given
an empty scratch folder in place of the folder around that path. It builds the new thing there
with ordinary code, and when it ends well the core moves that one thing into place. Whatever
else it left there is thrown away, and if it fails nothing appears at all.
"""
import dataclasses
import datetime
import functools
import json
import os
import pathlib
import shutil
import socket
import subprocess
import sys
import tempfile
import urllib.error
import urllib.parse
import urllib.request

from . import state

PYTHON = "/usr/bin/python3"     # the interpreter inside the sandbox, where /usr is all there is of the system
INSIDE = pathlib.Path(__file__).parent / "inside"
# All that the command line of the process inside carries. The rest arrives on the socket.
BOOT = ("import json, socket, sys; channel = socket.socket(fileno=int(sys.argv[1])).makefile('rw', encoding='utf-8'); "
        "start = json.loads(channel.readline()); names = {'__name__': 'los_runner'}; "
        "exec(compile(start['runner'], '<lo-s runner>', 'exec'), names); names['main'](channel, start)")
ENVIRONMENT = {"PATH": "/usr/bin", "LANG": "C.UTF-8"}
LARGEST = 2_000_000             # bytes of a page that fetch hands to a command
LONGEST = 12_000                # characters of a question a command may put to a model
OFFLINE = "the network is not used here"


class Refused(Exception):
    """The core will not do what a command asked for. The message goes back to the command."""


@dataclasses.dataclass
class Result:
    text: str               # what the command returned, or why it did not do what was asked
    ok: bool = True         # False when it refused, was refused or broke
    broke: bool = False     # True when the fault is in the command or the sandbox, not in the request


@dataclasses.dataclass
class Grant:
    """What one run of a command may touch."""
    args: dict              # the parameters as the command receives them, with every path made absolute
    paths: dict             # absolute path -> whether the command may change it
    creates: list = dataclasses.field(default_factory=list)     # paths it may create; nothing is there yet
    proc: bool = False      # a /proc of its own
    data: str = ""          # its plugin's data folder, or empty
    data_writable: bool = False
    hosts: tuple = ()       # hosts it may fetch from
    offline: bool = False   # True when this run is to stay off the network whatever the manifest says
    run: str = ""           # what tells this run from every other, in the records
    minds: object = None    # how a model is reached for this run: judge and ask (see judge.py), or nothing


def complete(command, args, base=None):
    """The parameters as the command will receive them: a path left out gets its default, and
    every path is made absolute, from `base` (the current directory unless given) or the home
    folder."""
    given = {name: args[name] for name in command.params if args.get(name)}
    for name, param in command.params.items():
        if name not in given and param.default:
            try:
                given[name] = param.default.format(**given)     # "." as it is, "{source}.bak" from what was given
            except KeyError:    # built from a parameter that was left out too
                pass
    for name, value in given.items():
        if command.params[name].path:
            given[name] = os.path.normpath(os.path.join(base or os.getcwd(), os.path.expanduser(value)))
    return given


def grant(command, args, base=None):
    """Work out what this run may touch, from the manifest and the parameters the user gave."""
    given, paths, creates = complete(command, args, base), {}, []
    for name, value in given.items():
        access = command.params[name].path
        if access == "create" and not os.path.lexists(value):
            creates.append(value)
        elif access:    # something already at a path to create is there to be seen, and nothing more
            paths[value] = paths.get(value, False) or access == "write"
    for path in command.reads:
        paths.setdefault(os.path.normpath(path), False)
    # The host's /proc shows every process of the user. The sandbox gets one of its own instead.
    proc = [path for path in paths if path == "/proc" or path.startswith("/proc/")]
    for path in proc:
        del paths[path]
    data = str(state.data(command.plugin)) if command.data else ""
    return Grant(given, paths, creates, bool(proc), data, command.data == "write", command.hosts)


def run(command, args, base=None, data=None, offline=False, minds=None):
    """Run a command with the parameters the user gave. Whatever the command does, the answer is
    a Result: nothing it raises reaches the shell.

    A trial run can be kept away from the user's things: `base` is the folder relative paths start
    from, `data` stands in for the plugin's data folder, and `offline` refuses every fetch.
    `minds` answers what the command asks of a model; without it nothing can be asked."""
    in_the_open = os.environ.get("LOS_NO_SANDBOX") == "1"
    if not in_the_open and unusable():
        if command.written_by:
            return Result(f"It was written by a model ({command.written_by}), and commands cannot be sandboxed here: "
                          f"{unusable()}. Set LOS_NO_SANDBOX=1 to run it with all of your permissions.", ok=False)
        in_the_open = True
    granted = grant(command, args, base)
    granted.offline, granted.minds = offline, minds
    granted.run = datetime.datetime.now().isoformat(timespec="microseconds")
    if data and command.data:
        granted.data = str(data)
    stages = {}     # folder around a path to create -> the scratch folder that stands in for it
    try:
        if not in_the_open:
            _stage(granted, stages)
        start = {"code": command.source.read_text(), "file": f"{command.source.parent.name}/commands.py",
                 "function": "do_" + command.verb, "args": granted.args, "data": granted.data or None}
        result = _converse(start, granted, stages, in_the_open, lambda message: _answer(command, granted, message))
        lost = _keep(granted, stages) if result.ok else []
    except OSError as error:    # a scratch folder could not be made, or what was made could not be moved in
        return Result(f"{error.strerror}: {error.filename}" if error.filename else str(error), ok=False)
    finally:
        for stage in stages.values():
            shutil.rmtree(stage, ignore_errors=True)
    return dataclasses.replace(result, text="\n".join([result.text] + lost).strip("\n")) if lost else result


def call(code, function, args, file="<code>"):
    """Call one function of a piece of code in a sandbox that holds nothing: no path of the
    user's, no data folder, no network, and nothing the core will do for it. For code that only
    works something out, such as a rule. Code a model wrote does not run where there is no sandbox."""
    in_the_open = os.environ.get("LOS_NO_SANDBOX") == "1"
    if not in_the_open and unusable():
        return Result(f"Code written by a model cannot be sandboxed here: {unusable()}.", ok=False)
    start = {"code": code, "file": file, "function": function, "args": args, "data": None}
    return _converse(start, Grant(args, {}), {}, in_the_open,
                     lambda message: {"refused": "this code may not ask the core for anything"})


def _stage(granted, stages):
    """Make a scratch folder for each folder the command may create something in. It is made
    inside the folder it stands in for, so that moving the result into place is a rename."""
    for path in granted.creates:
        around = os.path.dirname(path)
        # Inside a folder the command already holds there is nothing to stand in for.
        held = any(os.path.commonpath([named, around]) == named for named in granted.paths)
        if around not in stages and os.path.isdir(around) and not held:
            stages[around] = tempfile.mkdtemp(prefix=".los-new-", dir=around)


def _keep(granted, stages):
    """Move what the command created into place. Returns a sentence for anything that could not be kept."""
    lost = []
    for path in granted.creates:
        made = os.path.join(stages.get(os.path.dirname(path), ""), os.path.basename(path))
        if os.path.dirname(path) in stages and os.path.lexists(made):
            if os.path.lexists(path):
                lost.append(f"{path} appeared while the command ran, so what it made was not kept.")
            else:
                os.rename(made, path)
    return lost


def _converse(start, granted, stages, in_the_open, answer):
    """Start the process, hand it the code to run and answer what it asks until it says how it ended."""
    start = {"runner": (INSIDE / "runner.py").read_text(), "api": (INSIDE / "api.py").read_text(), **start}
    ours, theirs = socket.socketpair()
    with ours, tempfile.TemporaryFile() as noise:    # noise: whatever the process writes outside the socket
        with theirs:
            line = [sys.executable] if in_the_open else _bubblewrap(granted, stages) + [PYTHON]
            process = subprocess.Popen(line + ["-I", "-X", "utf8", "-c", BOOT, str(theirs.fileno())],
                                       pass_fds=[theirs.fileno()], stdin=subprocess.DEVNULL, stdout=noise,
                                       stderr=noise, cwd="/", env=ENVIRONMENT)
        channel, end = ours.makefile("rw", encoding="utf-8"), None
        try:
            _send(channel, start)
            for row in channel:
                message = json.loads(row)
                if not isinstance(message, dict) or "call" not in message:
                    end = message
                    break
                _send(channel, answer(message))
        except (OSError, ValueError):       # the process went away mid-sentence, or sent something that is not JSON
            pass
        finally:                            # also on Ctrl-C: nothing is left running
            try:
                process.wait(timeout=5 if end else 0)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            try:
                channel.close()
            except OSError:                 # something was still unsent to a process that is gone
                pass
        noise.seek(0)
        said = noise.read().decode(errors="replace").strip()
    if isinstance(end, dict) and "returned" in end:
        return Result(str(end["returned"]))
    if isinstance(end, dict) and "failed" in end:
        return Result(str(end["failed"]), ok=False)
    if isinstance(end, dict) and "broke" in end:
        return Result(str(end["broke"]).rstrip(), ok=False, broke=True)
    if not in_the_open and said.startswith("bwrap:"):
        return Result(f"The sandbox did not start. {said}", ok=False, broke=True)
    return Result("It stopped without an answer." + (f"\n{said}" if said else ""), ok=False, broke=True)


def _send(channel, message):
    channel.write(json.dumps(message) + "\n")
    channel.flush()


def _bubblewrap(granted, stages=None):
    """The bubblewrap command line that builds the sandbox for one grant. Everything is bound at
    its own absolute path, so a path means the same inside as outside. The one exception is a
    scratch folder, which stands where the folder around a path to create is."""
    def bind(path, held):
        source, writable = held
        return ["--bind" if writable else "--ro-bind", source, path]

    binds = {path: (path, writable) for path, writable in granted.paths.items() if os.path.exists(path)}
    if granted.data:
        binds[granted.data] = (granted.data, granted.data_writable)
    binds.update({around: (scratch, True) for around, scratch in (stages or {}).items()})
    line = [shutil.which("bwrap"), "--unshare-all", "--die-with-parent", "--new-session", "--clearenv", "--chdir", "/"]
    for name, value in ENVIRONMENT.items():
        line += ["--setenv", name, value]
    if "/" in binds:                    # the user named the whole machine: it lies underneath the rest
        line += bind("/", binds.pop("/"))
    line += ["--ro-bind", "/usr", "/usr"]
    for path in ("/bin", "/sbin", "/lib", "/lib64"):
        if os.path.islink(path):
            line += ["--symlink", os.readlink(path), path]
        elif os.path.isdir(path):
            line += ["--ro-bind", path, path]
    line += ["--dev", "/dev", "--tmpfs", "/tmp"]
    if os.path.exists("/etc/localtime") and "/" not in granted.paths:    # so that times read as the user's
        line += ["--ro-bind", "/etc/localtime", "/etc/localtime"]
    if granted.proc:
        line += ["--proc", "/proc"]
    for path in sorted(binds):          # a folder sorts before what is inside it
        line += bind(path, binds[path])
    # Last, the root itself becomes read-only. Without this a file created beside a granted path
    # would land in the sandbox's own root and vanish with it, and the command would think it had
    # written something.
    return line + ["--remount-ro", "/"]


@functools.cache
def unusable():
    """Why commands cannot be sandboxed on this machine, or an empty string when they can."""
    if not shutil.which("bwrap"):
        return "bubblewrap (the bwrap program) is not installed"
    try:
        probe = subprocess.run(_bubblewrap(Grant({}, {})) + [PYTHON, "-I", "-c", "pass"], stdin=subprocess.DEVNULL,
                               capture_output=True, text=True, timeout=20)
    except (OSError, subprocess.TimeoutExpired) as error:
        return f"bubblewrap did not start ({error})"
    return "" if probe.returncode == 0 else \
        f"bubblewrap could not build a sandbox ({probe.stderr.strip() or f'exit code {probe.returncode}'})"


def _answer(command, granted, message):
    """Do what a command asked the core for, if its grant allows it, and record the request."""
    asked = {key: value for key, value in message.items()
             if isinstance(value, str) or (isinstance(value, list) and all(isinstance(one, str) for one in value))}
    try:
        if not isinstance(asked.get("call"), str) or asked["call"] not in CALLS:
            raise Refused(f"the core has no call named {message.get('call')!r}")
        reply = {"value": CALLS[asked["call"]](command, granted, asked)}
    except Refused as refusal:
        reply = {"refused": str(refusal)}
    # What the command sent goes first, so that it cannot pass for the date, the name or the outcome.
    state.append("calls", {**asked, "date": datetime.datetime.now().isoformat(timespec="seconds"),
                           "command": command.name, "outcome": reply.get("refused", "done")})
    return reply


def _fetch(command, granted, asked):
    """Get a page for a command, from a host its manifest lists and no other, over https."""
    url = asked.get("url", "")
    if granted.offline:
        raise Refused(OFFLINE)
    _listed(command, granted, url)
    try:
        with urllib.request.build_opener(_Listed(command, granted)).open(
                urllib.request.Request(url, headers={"User-Agent": "lo-s"}), timeout=20) as response:
            page = response.read(LARGEST + 1)
    except urllib.error.HTTPError as error:
        raise Refused(f"{urllib.parse.urlsplit(url).hostname} answered {error.code} {error.reason}")
    except (urllib.error.URLError, OSError) as error:
        raise Refused(f"{urllib.parse.urlsplit(url).hostname} could not be reached ({getattr(error, 'reason', error)})")
    if len(page) > LARGEST:
        raise Refused(f"the page at {url} is larger than {LARGEST // 1_000_000} MB")
    return page.decode("utf-8", errors="replace")


def _listed(command, granted, url):
    parts = urllib.parse.urlsplit(url)
    try:
        port = parts.port
    except ValueError:
        port = -1
    if parts.scheme != "https" or parts.hostname not in granted.hosts or port not in (None, 443):
        raise Refused(f"{command.name} may fetch over https from {', '.join(granted.hosts) or 'no host at all'}, "
                      f"and {url or 'an empty address'} is not that")


class _Listed(urllib.request.HTTPRedirectHandler):
    """Holds a page that sends the request on elsewhere to the same list of hosts."""

    def __init__(self, command, granted):
        self.command, self.granted = command, granted

    def redirect_request(self, request, fp, code, msg, headers, newurl):
        _listed(self.command, self.granted, newurl)
        return super().redirect_request(request, fp, code, msg, headers, newurl)


def _remove(command, granted, asked):
    """Remove a path the user named for writing, with everything in it."""
    if command.effect != "destructive":
        raise Refused(f"{command.name} is not marked destructive, so it may not remove anything")
    path = _changeable(granted, asked.get("path"))
    if not os.path.lexists(path):
        raise Refused(f"{path} does not exist")
    try:
        if os.path.isdir(path) and not os.path.islink(path):
            shutil.rmtree(path)
        else:
            os.remove(path)
    except OSError as error:
        raise Refused(f"{path} could not be removed: {error}")


def _move(command, granted, asked):
    """Move one path to another, both of them named by the user. Nothing is ever replaced."""
    if command.effect != "destructive":
        raise Refused(f"{command.name} is not marked destructive, so it may not move anything")
    source, dest = _changeable(granted, asked.get("source")), _changeable(granted, asked.get("dest"))
    if not os.path.lexists(source):
        raise Refused(f"{source} does not exist")
    if os.path.lexists(dest):
        raise Refused(f"{dest} already exists; nothing was moved")
    try:
        shutil.move(source, dest)
    except (OSError, shutil.Error) as error:
        raise Refused(f"{source} could not be moved: {error}")


def _changeable(granted, path):
    """Where on the host a path lies that a command wants the core to change. It has to be a path
    the user named for writing, or lie inside a folder they named for writing. A link inside such
    a folder that leads out of it does not count, so the folder the path is in is resolved first."""
    if not path or not os.path.isabs(path):
        raise Refused("the core changes absolute paths only")
    path = os.path.normpath(path)
    real = os.path.join(os.path.realpath(os.path.dirname(path)), os.path.basename(path))
    for named, writable in granted.paths.items():
        if writable and path == named:
            return path
        if writable and os.path.commonpath([os.path.realpath(named), real]) == os.path.realpath(named):
            return real
    raise Refused(f"{path} is not among the paths this command was given to change")


def _judge(command, granted, asked):
    """One of a few answers for one value, for a judgement the manifest names."""
    name, question, value, choices = (asked.get(key) for key in ("name", "question", "value", "choices"))
    if not isinstance(name, str) or name not in command.judges:
        raise Refused(f"{command.name} may ask for a judgement of {', '.join(command.judges) or 'nothing'}, "
                      f"and {name!r} is not that")
    if not all(isinstance(text, str) and text.strip() for text in (question, value)):
        raise Refused("a judgement needs a question and a value, both as text")
    if not isinstance(choices, list) or not 2 <= len(choices) <= 12 or len(set(choices)) != len(choices) \
            or not all(choice.strip() for choice in choices):
        raise Refused("a judgement needs 2 to 12 different answers to choose from")
    if len(question) > 500 or len(value) > 2000 or max(map(len, choices)) > 100:
        raise Refused("a judgement takes a question of at most 500 characters, a value of at most 2000 and "
                      "answers of at most 100")
    if not granted.minds:
        raise Refused("no model can be asked here")
    return granted.minds.judge(command, granted.run, name, question, value, choices)


def _ask(command, granted, asked):
    """An answer in free text to a question of the command's own, from a model the manifest lists."""
    to, message = asked.get("to"), asked.get("message")
    if not isinstance(to, str) or to not in command.asks:
        raise Refused(f"{command.name} may put a question to {' or '.join(command.asks) or 'no model'}, "
                      f"and {to!r} is not that")
    if not isinstance(message, str) or not message.strip():
        raise Refused("a question needs some text")
    if len(message) > LONGEST:
        raise Refused(f"a question may be at most {LONGEST} characters, and this one has {len(message)}")
    if not granted.minds:
        raise Refused("no model can be asked here")
    return granted.minds.ask(command, to, message)


CALLS = {"move": _move, "remove": _remove, "fetch": _fetch, "judge": _judge, "ask": _ask}
