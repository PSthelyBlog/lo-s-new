"""What runs inside the sandbox: load one command's code, call it, and say how it ended.

The core starts a fresh Python process and hands it one socket. The first line on the socket
carries this file, the module commands import as `los`, the command's code and its parameters.
`main` gets the socket as a text file and that first line. It answers with one line: what the
command returned, why it refused, or how it broke.

Nothing here is trusted by the core. Whatever a command asks for is checked on the other side.
"""
import contextlib
import io
import json
import linecache
import sys
import types


def main(channel, start):
    def tell(message):
        channel.write(json.dumps(message) + "\n")
        channel.flush()

    def core(call, **request):
        """Ask the core for something the command cannot do itself."""
        tell({"call": call, **request})
        answer = json.loads(channel.readline() or "{}")
        if "refused" in answer:
            raise api.CommandError(answer["refused"])
        return answer.get("value")

    api = types.ModuleType("los")
    exec(compile(start["api"], "<los>", "exec"), api.__dict__)
    api._core, api.DATA = core, start["data"]
    sys.modules["los"] = api

    code, file = start["code"], start["file"]
    linecache.cache[file] = (len(code), None, code.splitlines(True), file)      # so a traceback shows the line
    module, printed = types.ModuleType("commands"), io.StringIO()
    try:
        with contextlib.redirect_stdout(printed):   # a command returns its text; what it prints is kept too
            exec(compile(code, file, "exec"), module.__dict__)
            value = getattr(module, "do_" + start["verb"])(**start["args"])
        tell({"returned": printed.getvalue() + ("" if value is None else str(value))})
    except api.CommandError as error:
        tell({"failed": str(error)})
    except OSError as error:        # permission denied, a missing file, a read-only path
        where = error.filename if isinstance(error.filename, str) else ""
        tell({"failed": f"{error.strerror}: {where}" if error.strerror and where else str(error)})
    except BaseException:           # anything else is a fault in the command
        import traceback            # here and not at the top: it takes longer to load than a command to run
        tell({"broke": traceback.format_exc()})
