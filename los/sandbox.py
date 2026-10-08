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

There is one such request so far, `move`. A path bound into the sandbox can be read and changed
in place, but not renamed or removed: that changes the folder around it, which the command does
not hold. Giving it that folder would give it everything else in there too. So the core does the
move, between paths the user named.
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

from . import state

PYTHON = "/usr/bin/python3"     # the interpreter inside the sandbox, where /usr is all there is of the system
INSIDE = pathlib.Path(__file__).parent / "inside"
# All that the command line of the process inside carries. The rest arrives on the socket.
BOOT = ("import json, socket, sys; channel = socket.socket(fileno=int(sys.argv[1])).makefile('rw', encoding='utf-8'); "
        "start = json.loads(channel.readline()); names = {'__name__': 'los_runner'}; "
        "exec(compile(start['runner'], '<lo-s runner>', 'exec'), names); names['main'](channel, start)")
ENVIRONMENT = {"PATH": "/usr/bin", "LANG": "C.UTF-8"}


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
    proc: bool = False      # a /proc of its own
    data: str = ""          # its plugin's data folder, or empty
    data_writable: bool = False


def complete(command, args):
    """The parameters as the command will receive them: a path left out gets its default, and
    every path is made absolute, from the current directory or the home folder."""
    given = {}
    for name, param in command.params.items():
        value = args.get(name) or param.default
        if value:
            given[name] = os.path.abspath(os.path.expanduser(value)) if param.path else value
    return given


def grant(command, args):
    """Work out what this run may touch, from the manifest and the parameters the user gave."""
    given, paths = complete(command, args), {}
    for name, value in given.items():
        if command.params[name].path:
            paths[value] = paths.get(value, False) or command.params[name].path == "write"
    for path in command.reads:
        paths.setdefault(os.path.normpath(path), False)
    # The host's /proc shows every process of the user. The sandbox gets one of its own instead.
    proc = [path for path in paths if path == "/proc" or path.startswith("/proc/")]
    for path in proc:
        del paths[path]
    data = str(state.data(command.plugin)) if command.data else ""
    return Grant(given, paths, bool(proc), data, command.data == "write")


def run(command, args):
    """Run a command with the parameters the user gave. Whatever the command does, the answer is
    a Result: nothing it raises reaches the shell."""
    in_the_open = os.environ.get("LOS_NO_SANDBOX") == "1"
    if not in_the_open and unusable():
        if command.written_by:
            return Result(f"It was written by a model ({command.written_by}), and commands cannot be sandboxed here: "
                          f"{unusable()}. Set LOS_NO_SANDBOX=1 to run it with all of your permissions.", ok=False)
        in_the_open = True
    granted = grant(command, args)
    start = {"runner": (INSIDE / "runner.py").read_text(), "api": (INSIDE / "api.py").read_text(),
             "code": command.source.read_text(), "file": f"{command.source.parent.name}/commands.py",
             "verb": command.verb, "args": granted.args, "data": granted.data or None}
    ours, theirs = socket.socketpair()
    with ours, tempfile.TemporaryFile() as noise:    # noise: whatever the process writes outside the socket
        with theirs:
            line = [sys.executable] if in_the_open else _bubblewrap(granted) + [PYTHON]
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
                _send(channel, _answer(command, granted, message))
        except (OSError, ValueError):       # the process went away mid-sentence, or sent something that is not JSON
            pass
        finally:                            # also on Ctrl-C: nothing is left running
            try:
                process.wait(timeout=5 if end else 0)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
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


def _bubblewrap(granted):
    """The bubblewrap command line that builds the sandbox for one grant. Everything is bound at
    its own absolute path, so a path means the same inside as outside."""
    def bind(path, writable):
        return ["--bind" if writable else "--ro-bind", path, path]

    binds = {path: writable for path, writable in granted.paths.items() if os.path.exists(path)}
    if granted.data:
        binds[granted.data] = granted.data_writable
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
    asked = {key: value for key, value in message.items() if isinstance(value, str)}
    try:
        if asked.get("call") not in CALLS:
            raise Refused(f"the core has no call named {message.get('call')!r}")
        reply = {"value": CALLS[asked["call"]](command, granted, asked)}
    except Refused as refusal:
        reply = {"refused": str(refusal)}
    # What the command sent goes first, so that it cannot pass for the date, the name or the outcome.
    state.append("calls", {**asked, "date": datetime.datetime.now().isoformat(timespec="seconds"),
                           "command": command.name, "outcome": reply.get("refused", "done")})
    return reply


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


CALLS = {"move": _move}
