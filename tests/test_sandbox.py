"""What the sandbox lets a command do, tried with a command that does whatever a test asks.

`probe` has one command per effect. Each evaluates the Python it is given and returns the value,
or the name of the error it ran into, so a test can try something and see how it went.
"""
import io
import os
import urllib.error
import urllib.request
from unittest import mock

from los import plugins, sandbox, state
from tests.helpers import Folders, needs_sandbox

TOLD = 'other = "a path it is told about but not given"\ncode = "what to try"'
MANIFEST = f'''
name = "probe"

[commands.read]
description = "Try something as a command that only reads"
data = "read"
[commands.read.params]
path = {{ path = "read" }}
{TOLD}

[commands.write]
description = "Try something as a command that writes"
effect = "write"
data = "write"
[commands.write.params]
path = {{ path = "read" }}
{TOLD}

[commands.change]
description = "Try something as a destructive command"
effect = "destructive"
[commands.change.params]
path = {{ path = "write" }}
also = {{ path = "write" }}
{TOLD}

[commands.add]
description = "Try something as a command that may create what it is given"
effect = "write"
[commands.add.params]
path = {{ path = "create" }}
also = {{ path = "read" }}
{TOLD}

[commands.net]
description = "Try something as a command that may fetch from one host"
hosts = ["api.example.org"]
[commands.net.params]
code = "what to try"

[commands.fail]
description = "End in the way it is told to"
[commands.fail.params]
how = "refuse, raise, vanish or print"
'''
CODE = '''
import os, pathlib, shutil, socket
from los import DATA, CommandError, fetch, move, remove


def _attempt(code, path, other, also=None):
    try:
        return repr(eval(code))
    except CommandError:
        raise
    except Exception as error:
        return f"{type(error).__name__}: {error}"


def do_read(path=None, other=None, code=None):
    return _attempt(code, path, other)


def do_write(path=None, other=None, code=None):
    return _attempt(code, path, other)


def do_change(path=None, other=None, code=None, also=None):
    return _attempt(code, path, other, also)


def do_add(path=None, other=None, code=None, also=None):
    return _attempt(code, path, other, also)


def do_net(code=None):
    return _attempt(code, None, None)


def do_fail(how=None):
    if how == "refuse":
        raise CommandError("I would rather not.")
    if how == "raise":
        return 1 / 0
    if how == "vanish":
        os._exit(3)
    print("printed first")
    return "returned after"
'''


class GrantTest(Folders):
    def setUp(self):
        super().setUp()
        self.table, _ = plugins.load(state.ROOT / "plugins")

    def test_paths_are_made_absolute_and_a_missing_one_gets_its_default(self):
        granted = sandbox.grant(self.table["fs.list"], {"sort_by": "size"})
        self.assertEqual((granted.args, granted.paths), ({"path": os.getcwd(), "sort_by": "size"}, {os.getcwd(): False}))
        granted = sandbox.grant(self.table["fs.find"], {"path": "~/Documents/../Music", "name": "~/kept as typed"})
        music = os.path.expanduser("~/Music")
        self.assertEqual((granted.args, granted.paths), ({"path": music, "name": "~/kept as typed"}, {music: False}))

    def test_only_a_path_declared_for_writing_may_be_changed(self):
        granted = sandbox.grant(self.table["fs.move"], {"source": "/a/b", "dest": "/a/c"})
        self.assertEqual(granted.paths, {"/a/b": True, "/a/c": True})
        self.assertEqual((granted.data, granted.proc), ("", False))

    def test_fixed_paths_and_the_data_folder_come_from_the_manifest(self):
        granted = sandbox.grant(self.table["sys.status"], {})
        self.assertEqual((granted.paths, granted.proc, granted.data), ({"/sys": False}, True, ""))
        for name, writable in (("note.add", True), ("note.list", False)):
            granted = sandbox.grant(self.table[name], {})
            self.assertEqual((granted.data, granted.data_writable), (str(self.root / "state" / "data" / "note"), writable))

    def test_the_hosts_proc_is_never_handed_over(self):
        granted = sandbox.grant(self.table["fs.list"], {"path": "/proc/1"})
        self.assertEqual((granted.paths, granted.proc), ({}, True))

    def test_a_default_can_be_built_from_another_parameter(self):
        copy = plugins.Command("fs.copy", "Copy", {"source": plugins.Param("", "read"),
                                                   "dest": plugins.Param("", "create", "{source}.bak")}, "write")
        self.assertEqual(sandbox.complete(copy, {"source": "config.yaml"}, base="/work"),
                         {"source": "/work/config.yaml", "dest": "/work/config.yaml.bak"})
        self.assertEqual(sandbox.complete(copy, {"source": "~/config.yaml", "dest": "kept"}, base="/work"),
                         {"source": os.path.expanduser("~/config.yaml"), "dest": "/work/kept"})
        self.assertEqual(sandbox.complete(copy, {}), {})

    def test_a_path_to_create_is_one_where_nothing_is_yet(self):
        copy = plugins.Command("fs.copy", "Copy", {"source": plugins.Param("", "read"),
                                                   "dest": plugins.Param("", "create", "{source}.bak")}, "write")
        (self.files / "config.yaml").write_text("a: 1\n")
        granted = sandbox.grant(copy, {"source": "config.yaml"}, base=str(self.files))
        self.assertEqual((granted.paths, granted.creates),
                         ({f"{self.files}/config.yaml": False}, [f"{self.files}/config.yaml.bak"]))
        granted = sandbox.grant(copy, {"source": "config.yaml", "dest": "config.yaml"}, base=str(self.files))
        self.assertEqual((granted.paths, granted.creates), ({f"{self.files}/config.yaml": False}, []))


@needs_sandbox
class SandboxTest(Folders):
    def setUp(self):
        super().setUp()
        self.table, problems = self.plugin(MANIFEST, CODE)
        self.assertEqual(problems, [])
        self.given = self.files / "given.txt"
        self.given.write_text("given\n")
        self.secret = self.files / "secret.txt"
        self.secret.write_text("secret\n")
        (self.files / "folder").mkdir()
        (self.files / "folder" / "inside.txt").write_text("inside\n")

    def attempt(self, verb, code, path=None, **args):
        result = sandbox.run(self.table[f"probe.{verb}"], {"path": str(path or self.given), "code": code, **args})
        return result.text

    def unchanged(self):
        """Everything the test put on the host is still exactly as it was."""
        return (sorted(path.name for path in self.files.iterdir()) == ["folder", "given.txt", "secret.txt"]
                and self.given.read_text() == "given\n" and self.secret.read_text() == "secret\n"
                and [path.name for path in (self.files / "folder").iterdir()] == ["inside.txt"])

    def test_a_command_reads_what_it_was_given(self):
        self.assertEqual(self.attempt("read", "open(path).read()"), "'given\\n'")
        self.assertEqual(self.attempt("read", "sorted(os.listdir(path))", path=self.files),
                         "['folder', 'given.txt', 'secret.txt']")

    def test_a_command_cannot_read_what_it_was_not_given(self):
        self.assertIn("FileNotFoundError", self.attempt("read", "open(other).read()", other=str(self.secret)))
        self.assertEqual(self.attempt("read", "os.listdir(os.path.dirname(path))"), "['given.txt']")
        for elsewhere in (os.path.expanduser("~"), str(state.ROOT), str(state.ROOT / "los" / "sandbox.py"), "/etc/passwd"):
            self.assertIn("Error", self.attempt("read", "os.listdir(other) if os.path.isdir(other) else open(other).read()",
                                                other=elsewhere), elsewhere)
        self.assertEqual(self.attempt("read", "os.path.exists(other)", other=os.path.expanduser("~")), "False")
        self.assertEqual(self.attempt("read", "sorted(os.environ)"), "['LANG', 'PATH', 'PWD']")

    def test_a_command_has_no_network(self):
        self.assertIn("OSError", self.attempt("read", "socket.create_connection(('192.0.2.1', 80), timeout=3)"))
        self.assertEqual(self.attempt("read", "[name for _, name in socket.if_nameindex()]"), "['lo']")

    def test_a_read_command_cannot_write(self):
        for code in ("open(path, 'a').write('more')", "open(path, 'w').write('')", "os.remove(path)",
                     "os.rename(path, path + '.moved')", "open(os.path.dirname(path) + '/new.txt', 'w').write('new')",
                     "open(DATA + '/kept.txt', 'w').write('kept')", "os.mkdir('/made')", "open('/usr/made', 'w')"):
            self.attempt("read", code)
            self.assertTrue(self.unchanged(), code)
        self.assertIn("Read-only file system", self.attempt("read", "open(path, 'a').write('more')"))
        self.assertIn("Read-only file system", self.attempt("read", "open(DATA + '/kept.txt', 'w').write('kept')"))
        self.assertEqual(list(state.data("probe").iterdir()), [])

    def test_a_read_command_given_a_folder_cannot_change_what_is_in_it(self):
        for code in ("shutil.rmtree(path)", "os.remove(path + '/given.txt')", "open(path + '/new.txt', 'w').write('new')",
                     "open(path + '/folder/inside.txt', 'a').write('more')"):
            self.attempt("read", code, path=self.files)
            self.assertTrue(self.unchanged(), code)

    def test_a_read_command_cannot_ask_the_core_to_move_anything(self):
        result = sandbox.run(self.table["probe.read"], {"path": str(self.given), "code": "move(path, path + '.moved')"})
        self.assertEqual((result.ok, result.broke), (False, False))
        self.assertIn("not marked destructive", result.text)
        self.assertTrue(self.unchanged())

    def test_a_file_made_beside_a_granted_path_is_refused_rather_than_lost(self):
        if os.path.commonpath([os.path.realpath(self.root), "/tmp"]) == "/tmp":
            self.skipTest("the test's files are under /tmp, which inside the sandbox is the command's own scratch space")
        self.assertIn("Read-only file system",
                      self.attempt("change", "open(os.path.dirname(path) + '/new.txt', 'w').write('new')"))

    def test_scratch_space_does_not_outlive_the_command(self):
        self.assertEqual(self.attempt("read", "open('/tmp/los-test-scratch.txt', 'w').write('x')"), "1")
        self.assertEqual(self.attempt("read", "os.path.exists('/tmp/los-test-scratch.txt')"), "False")
        self.assertFalse(os.path.exists("/tmp/los-test-scratch.txt"))

    def test_a_write_command_changes_its_data_folder_and_nothing_else(self):
        self.assertEqual(self.attempt("write", "open(DATA + '/kept.txt', 'w').write('kept')"), "4")
        self.assertEqual((state.data("probe") / "kept.txt").read_text(), "kept")
        self.assertEqual(self.attempt("read", "open(DATA + '/kept.txt').read()"), "'kept'")
        for code in ("open(path, 'a').write('more')", "os.remove(path)", "open(os.path.dirname(path) + '/new.txt', 'w').write('n')"):
            self.attempt("write", code)
            self.assertTrue(self.unchanged(), code)
        self.assertIn("not marked destructive", self.attempt("write", "move(path, path + '.moved')"))

    def test_a_destructive_command_changes_what_it_was_given_and_only_that(self):
        self.assertEqual(self.attempt("change", "open(path, 'a').write('more\\n')"), "5")
        self.assertEqual(self.given.read_text(), "given\nmore\n")
        self.attempt("change", "open(other, 'a').write('more')", other=str(self.secret))
        self.assertEqual(self.secret.read_text(), "secret\n")
        # It cannot remove or rename the path itself: that is a change to the folder around it.
        self.assertIn("OSError", self.attempt("change", "os.remove(path)"))
        self.assertIn("OSError", self.attempt("change", "os.rename(path, path + '.moved')"))
        self.assertEqual(sorted(path.name for path in self.files.iterdir()), ["folder", "given.txt", "secret.txt"])

    def test_the_core_moves_a_named_path_to_a_named_path(self):
        new = self.files / "renamed.txt"
        self.assertEqual(self.attempt("change", "move(path, also)", also=str(new)), "None")
        self.assertEqual((self.given.exists(), new.read_text()), (False, "given\n"))
        self.assertEqual(self.attempt("change", "move(path, also + '/renamed.txt')", path=new, also=str(self.files / "folder")), "None")
        self.assertEqual((self.files / "folder" / "renamed.txt").read_text(), "given\n")
        calls = state.read("calls")
        self.assertEqual([(call["command"], call["call"], call["outcome"]) for call in calls],
                         [("probe.change", "move", "done")] * 2)
        self.assertEqual((calls[0]["source"], calls[0]["dest"]), (str(self.given), str(new)))

    def test_a_command_cannot_write_the_record_of_what_it_asked(self):
        self.attempt("read", "__import__('los')._core('move', source=path, dest=path, command='fs.move', outcome='done', date='then')")
        call, = state.read("calls")
        self.assertEqual(call["command"], "probe.read")
        self.assertIn("not marked destructive", call["outcome"])
        self.assertNotEqual(call["date"], "then")

    def test_the_core_replaces_nothing(self):
        result = sandbox.run(self.table["probe.change"], {"path": str(self.given), "also": str(self.secret),
                                                          "code": "move(path, also)"})
        self.assertEqual((result.ok, result.broke), (False, False))
        self.assertIn("already exists; nothing was moved", result.text)
        self.assertTrue(self.unchanged())

    def test_the_core_moves_nothing_the_user_did_not_name(self):
        outside = self.root / "outside"
        outside.mkdir()
        (outside / "theirs.txt").write_text("theirs\n")
        os.symlink(outside, self.files / "folder" / "way-out")
        folder = str(self.files / "folder")
        for code in ("move(other, also + '/taken.txt')",                     # from a path it was only told about
                     "move(path, other + '.moved')",                         # to one
                     "move(path, os.path.dirname(path) + '/unnamed.txt')",   # to a name beside the one it was given
                     "move(also + '/way-out/theirs.txt', also + '/taken.txt')",     # through a link that leads out
                     "move(path, also + '/way-out/planted.txt')",
                     "move(also + '/../secret.txt', also + '/taken.txt')",
                     "move('given.txt', also + '/taken.txt')"):
            result = sandbox.run(self.table["probe.change"], {"path": str(self.given), "also": folder, "code": code,
                                                              "other": str(self.secret)})
            self.assertEqual((result.ok, result.broke), (False, False), code)
            self.assertTrue(self.given.read_text() == "given\n" and self.secret.read_text() == "secret\n", code)
            self.assertEqual(sorted(path.name for path in outside.iterdir()), ["theirs.txt"], code)
            self.assertEqual(sorted(path.name for path in (self.files / "folder").iterdir()), ["inside.txt", "way-out"], code)
        self.assertTrue(all(call["outcome"] != "done" for call in state.read("calls")))

    def test_a_command_makes_what_it_was_given_to_create(self):
        new = self.files / "new.txt"
        self.assertEqual(self.attempt("add", "(os.listdir(os.path.dirname(path)), open(path, 'w').write('made'))",
                                      path=new, also=str(self.given)), "(['given.txt'], 4)")
        self.assertEqual(new.read_text(), "made")
        tree = self.files / "tree"
        self.attempt("add", "(os.mkdir(path), open(path + '/leaf.txt', 'w').write('leaf'))", path=tree)
        self.assertEqual((tree / "leaf.txt").read_text(), "leaf")
        self.assertEqual(sorted(path.name for path in self.files.iterdir()),
                         ["folder", "given.txt", "new.txt", "secret.txt", "tree"])       # and no scratch folder is left

    def test_nothing_appears_when_the_command_does_not_end_well(self):
        new = self.files / "new.txt"
        for code in ("(open(path, 'w').write('made'), move(path, path + '2'))",     # refused by the core, so it fails
                     "(open(path, 'w').write('made'), os._exit(1))"):
            result = sandbox.run(self.table["probe.add"], {"path": str(new), "code": code})
            self.assertFalse(result.ok, code)
            self.assertTrue(self.unchanged(), code)

    def test_what_a_command_makes_beside_the_path_it_was_given_is_thrown_away(self):
        new = self.files / "new.txt"
        self.attempt("add", "[open(os.path.dirname(path) + '/' + name, 'w').write('x') for name in ('new.txt', 'stray.txt', "
                            "'secret.txt')]", path=new)
        self.assertEqual(sorted(path.name for path in self.files.iterdir()), ["folder", "given.txt", "new.txt", "secret.txt"])
        self.assertEqual((new.read_text(), self.secret.read_text()), ("x", "secret\n"))

    def test_a_path_to_create_that_is_there_already_can_be_seen_and_not_changed(self):
        self.assertEqual(self.attempt("add", "open(path).read()"), "'given\\n'")
        for code in ("open(path, 'w').write('other')", "os.remove(path)", "remove(path)"):
            self.attempt("add", code)
            self.assertTrue(self.unchanged(), code)

    def test_nothing_can_be_made_where_the_user_may_not_write(self):
        result = sandbox.run(self.table["probe.add"], {"path": "/usr/los-test-new.txt", "code": "open(path, 'w').write('x')"})
        self.assertEqual((result.ok, result.broke), (False, False))
        self.assertIn("Permission denied", result.text)

    def test_the_core_removes_a_named_path_for_a_destructive_command(self):
        self.assertEqual(self.attempt("change", "remove(path)"), "None")
        self.assertFalse(self.given.exists())
        self.assertEqual(self.attempt("change", "remove(also)", path=self.secret, also=str(self.files / "folder")), "None")
        self.assertEqual(sorted(path.name for path in self.files.iterdir()), ["secret.txt"])
        self.assertEqual([(call["call"], call["path"], call["outcome"]) for call in state.read("calls")],
                         [("remove", str(self.given), "done"), ("remove", str(self.files / "folder"), "done")])

    def test_the_core_removes_nothing_the_user_did_not_name(self):
        for verb, code in (("change", "remove(other)"), ("change", "remove(os.path.dirname(path))"),
                           ("change", "remove(path + '/../secret.txt')"), ("read", "remove(path)"), ("write", "remove(path)")):
            result = sandbox.run(self.table[f"probe.{verb}"], {"path": str(self.given), "code": code, "other": str(self.secret)})
            self.assertEqual((result.ok, result.broke), (False, False), code)
            self.assertTrue(self.unchanged(), code)

    def page(self, code, **how):
        return sandbox.run(self.table["probe.net"], {"code": code}, **how)

    def test_a_page_is_fetched_from_a_listed_host_by_the_core(self):
        class Page(io.BytesIO):
            def __enter__(self):
                return self

            def __exit__(self, *_):
                pass

        with mock.patch.object(urllib.request.OpenerDirector, "open", return_value=Page("météo: 12 °C".encode())) as opened:
            result = self.page("fetch('https://api.example.org/v1/forecast?day=tomorrow')")
        self.assertEqual((result.ok, result.text), (True, repr("météo: 12 °C")))
        self.assertEqual(opened.call_args.args[0].full_url, "https://api.example.org/v1/forecast?day=tomorrow")
        call, = state.read("calls")
        self.assertEqual((call["call"], call["url"], call["outcome"]),
                         ("fetch", "https://api.example.org/v1/forecast?day=tomorrow", "done"))

    def test_nothing_is_fetched_from_anywhere_else(self):
        with mock.patch.object(urllib.request.OpenerDirector, "open") as opened:
            for url in ("https://example.org/", "http://api.example.org/", "https://api.example.org:8443/",
                        "https://api.example.org@example.net/", "https://api.example.org.example.net/", "ftp://api.example.org/",
                        "file:///etc/passwd", ""):
                result = self.page(f"fetch({url!r})")
                self.assertEqual((result.ok, result.broke), (False, False), url)
                self.assertIn("probe.net may fetch over https from api.example.org", result.text)
            result = sandbox.run(self.table["probe.read"], {"path": str(self.given), "code": "fetch('https://api.example.org/')"})
            self.assertIn("from no host at all", result.text)
            self.assertIn(sandbox.OFFLINE, self.page("fetch('https://api.example.org/')", offline=True).text)
        opened.assert_not_called()
        granted = sandbox.grant(self.table["probe.net"], {})
        with self.assertRaises(sandbox.Refused):        # a listed host that sends the request on elsewhere
            sandbox._Listed(self.table["probe.net"], granted).redirect_request(None, None, 302, "", {}, "https://example.net/")

    def test_a_host_that_cannot_be_reached_is_an_error_the_user_can_read(self):
        with mock.patch.object(urllib.request.OpenerDirector, "open", side_effect=urllib.error.URLError("no route")):
            result = self.page("fetch('https://api.example.org/')")
        self.assertEqual((result.ok, result.text), (False, "api.example.org could not be reached (no route)"))

    def test_a_trial_run_stays_away_from_the_users_things(self):
        elsewhere = self.root / "trial"
        (elsewhere / "work").mkdir(parents=True)
        (elsewhere / "work" / "given.txt").write_text("trial\n")
        result = sandbox.run(self.table["probe.write"], {"path": "given.txt", "code": "(open(path).read(), open(DATA + '/x', 'w').write('x'))"},
                             base=str(elsewhere / "work"), data=str(elsewhere))
        self.assertEqual(result.text, "('trial\\n', 1)")
        self.assertEqual(((elsewhere / "x").read_text(), list(state.data("probe").iterdir())), ("x", []))

    def test_how_a_command_ends_is_told_apart(self):
        def end(how):
            result = sandbox.run(self.table["probe.fail"], {"how": how})
            return result.ok, result.broke, result.text

        self.assertEqual(end("print"), (True, False, "printed first\nreturned after"))
        self.assertEqual(end("refuse"), (False, False, "I would rather not."))
        ok, broke, text = end("raise")
        self.assertEqual((ok, broke), (False, True))
        self.assertIn("ZeroDivisionError", text)
        self.assertRegex(text, r'File "probe/commands.py", line \d+, in do_fail\n +return 1 / 0')
        self.assertEqual(end("vanish"), (False, True, "It stopped without an answer."))

    def test_an_error_of_the_system_reads_as_a_sentence(self):
        result = sandbox.run(self.table["probe.fail"], {"how": "print"})
        self.assertTrue(result.ok)
        listed = sandbox.run(plugins.load(state.ROOT / "plugins")[0]["fs.list"], {"path": str(self.files / "missing")})
        self.assertEqual((listed.ok, listed.text), (False, f"{self.files / 'missing'} is not a directory"))


class WithoutBubblewrapTest(Folders):
    def setUp(self):
        super().setUp()
        self.table, _ = self.plugin(MANIFEST, CODE)
        written, _ = self.plugin(MANIFEST.replace('"probe"', '"learnt"') + '\n[origin]\nwritten_by = "some-model"\n',
                                 CODE, folder="learnt.read")
        self.table.update(written)
        missing = mock.patch.object(sandbox, "unusable", lambda: "bubblewrap (the bwrap program) is not installed")
        missing.start()
        self.addCleanup(missing.stop)

    def test_a_command_nobody_generated_still_runs(self):
        result = sandbox.run(self.table["probe.read"], {"path": str(self.files), "code": "os.path.isdir(path)"})
        self.assertEqual((result.ok, result.text), (True, "True"))

    def test_a_command_written_by_a_model_does_not_run_unless_the_user_says_so(self):
        args = {"path": str(self.files), "code": "os.path.isdir(path)"}
        result = sandbox.run(self.table["learnt.read"], args)
        self.assertEqual((result.ok, result.broke), (False, False))
        self.assertIn("written by a model (some-model)", result.text)
        self.assertIn("LOS_NO_SANDBOX=1", result.text)
        with mock.patch.dict(os.environ, {"LOS_NO_SANDBOX": "1"}):
            self.assertEqual(sandbox.run(self.table["learnt.read"], args).text, "True")

    def test_the_core_still_checks_what_it_is_asked(self):
        target = self.files / "a.txt"
        target.write_text("a")
        result = sandbox.run(self.table["probe.change"], {"path": str(target), "code": "move(path, other)",
                                                          "other": str(self.files / "b.txt")})
        self.assertIn("not among the paths", result.text)
        self.assertTrue(target.exists())
