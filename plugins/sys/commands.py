"""Status of the machine, read from /proc and /sys, and whether it looks healthy."""
import glob
import os
import pathlib

from los import CommandError, judge


def _read(path):
    return pathlib.Path(path).read_text().strip()


def _battery():
    return [f"Battery: {_read(supply + '/capacity')}%, {_read(supply + '/status').lower()}"
            for supply in sorted(glob.glob("/sys/class/power_supply/BAT*"))] or ["Battery: none found"]


def _cpu():
    one, five, fifteen = _read("/proc/loadavg").split()[:3]
    return [f"CPU: load {one} over 1 minute, {five} over 5, {fifteen} over 15, on {os.cpu_count()} cores"]


def _gigabytes():
    """Memory available and memory in all."""
    kilobytes = {line.split(":")[0]: int(line.split()[1]) for line in _read("/proc/meminfo").splitlines()}
    return kilobytes["MemAvailable"] / 1048576, kilobytes["MemTotal"] / 1048576


def _memory():
    available, total = _gigabytes()
    return [f"Memory: {available:.1f} GB available of {total:.1f} GB"]


def _hottest():
    """The highest reading as (degrees, sensor), or None when there is no sensor."""
    readings = []
    for zone in glob.glob("/sys/class/thermal/thermal_zone*"):
        try:
            readings.append((int(_read(zone + "/temp")) / 1000, _read(zone + "/type")))
        except (OSError, ValueError):
            pass
    return max(readings) if readings else None


def _temperature():
    if not _hottest():
        return ["Temperature: no sensor found"]
    degrees, sensor = _hottest()
    return [f"Temperature: {degrees:.0f} °C at the hottest sensor ({sensor})"]


PARTS = {"battery": _battery, "cpu": _cpu, "memory": _memory, "temperature": _temperature}


def do_status(what=None):
    wanted = (what or "all").lower()
    if wanted != "all" and wanted not in PARTS:
        raise CommandError(f"--what is {', '.join(PARTS)} or all, not {what!r}")
    return "\n".join(line for name, part in PARTS.items() if wanted in ("all", name) for line in part())


LEVELS = ["fine", "worrying"]


def do_health():
    # Each value is short and rounded, so that the same one comes round again and is answered
    # from the record without a model. The questions are worded plainly: of five wordings tried
    # for memory, the student drew its line anywhere between 1% and 15% free.
    available, total = _gigabytes()
    readings = [("memory", "A computer in use has this much of its memory free. Is that fine or worrying?",
                 f"{available / total:.0%} free, of {total:.0f} GB")]
    if _hottest():
        readings.append(("temperature", "Is this temperature at a computer's hottest sensor fine or worrying "
                                        "while it is in use?", f"{_hottest()[0]:.0f} °C"))
    found = {level: [] for level in LEVELS}
    for name, question, value in readings:
        found[judge(name, question, value, LEVELS)].append(f"{name} {value}")
    if not found["worrying"]:
        return "The machine looks healthy: " + "; ".join(found["fine"]) + "."
    return "Worrying: " + "; ".join(found["worrying"]) + "." + (f" Fine: {'; '.join(found['fine'])}." if found["fine"] else "")
