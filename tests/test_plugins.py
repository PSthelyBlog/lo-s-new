from los import plugins, state
from tests.helpers import Folders

CODE = "def do_go(path=None, text=None):\n    return 'gone'\n"


def manifest(command="", params='path = { path = "read" }\ntext = "words"'):
    return f'name = "x"\n[commands.go]\ndescription = "Go"\n{command}\n[commands.go.params]\n{params}\n'


class PluginsTest(Folders):
    def test_starter_plugins_load(self):
        table, problems = plugins.load(state.ROOT / "plugins")
        self.assertEqual(problems, [])
        self.assertEqual(set(table), {"fs.find", "fs.list", "fs.move", "fs.usage", "note.add", "note.list", "sys.status"})
        self.assertEqual((table["fs.move"].effect, table["note.add"].effect, table["fs.find"].effect),
                         ("destructive", "write", "read"))
        self.assertEqual(table["fs.list"].params["path"], plugins.Param("directory, default the current one", "read", "."))
        self.assertEqual(table["fs.list"].params["sort_by"], plugins.Param("name, size or time"))
        self.assertEqual((table["sys.status"].reads, table["note.add"].data, table["note.list"].data),
                         (("/proc", "/sys"), "write", "read"))
        self.assertEqual((table["fs.move"].plugin, table["fs.move"].verb, table["fs.move"].written_by), ("fs", "move", ""))

    def test_a_manifest_says_what_a_command_may_touch(self):
        table, problems = self.plugin(manifest('reads = ["/proc"]\ndata = "read"'), CODE)
        self.assertEqual(problems, [])
        self.assertEqual(plugins.touches(table["x.go"]), [
            "It may read what you give as --path.", "It may read /proc.",
            "It may read the data lo-s keeps for the x commands.", "It sees no other file of yours and has no network."])
        table, problems = self.plugin(
            manifest('effect = "write"\nhosts = ["api.example.org", "example.org"]',
                     'path = { path = "create", default = "{text}.bak" }\ntext = { path = "read" }').replace('"x"', '"y"'),
            CODE, folder="adds")
        self.assertEqual(problems, [])
        self.assertEqual((table["y.go"].hosts, table["y.go"].params["path"].default),
                         (("api.example.org", "example.org"), "{text}.bak"))
        self.assertEqual(plugins.touches(table["y.go"]), [
            "It may read what you give as --text.", "It may create what you give as --path, if nothing is there yet.",
            "It may fetch pages from api.example.org, example.org.",
            "It sees no other file of yours and reaches nothing else on the network."])

    def test_a_command_written_by_a_model_says_so(self):
        table, _ = self.plugin(manifest() + '[origin]\nwritten_by = "some-model"\n', CODE)
        self.assertEqual(table["x.go"].written_by, "some-model")

    def test_a_grant_may_not_exceed_the_effect(self):
        for number, (command, params, said) in enumerate((
                ('effect = "read"', 'path = { path = "write" }\ntext = ""', "marked read but asks to change --path"),
                ('', 'path = { path = "create" }\ntext = ""', "marked read but asks to create --path"),
                ('effect = "write"', 'path = { path = "write" }\ntext = ""', "only a destructive command may change a path"),
                ('data = "write"', 'path = ""\ntext = ""', "marked read but asks to change its data folder"))):
            table, problems = self.plugin(manifest(command, params), CODE, folder=f"fault-{number}")
            self.assertEqual(table, {}, command)
            self.assertIn(said, problems[-1])
        table, problems = self.plugin(manifest('effect = "destructive"\ndata = "write"', 'path = { path = "write" }\ntext = ""'),
                                      CODE, folder="allowed")
        self.assertIn("x.go", table)

    def test_a_faulty_plugin_is_left_out_and_the_others_load(self):
        faults = {
            "effect": (manifest('effect = "maybe"'), CODE, "effect is one of read, write, destructive"),
            "entry": (manifest('programs = ["git"]'), CODE, "an entry the core does not know: programs"),
            "access": (manifest(params='path = { path = "all" }\ntext = ""'), CODE, "the path of path is read, create or write"),
            "default": (manifest(params='path = ""\ntext = { default = "x" }'), CODE, "only a path can have a default"),
            "built": (manifest(params='path = { path = "read", default = "{other}.bak" }\ntext = ""'), CODE,
                      "{other} is not one"),
            "format": (manifest(params='path = { path = "read", default = "{text.__class__}" }\ntext = ""'), CODE,
                       "is not one"),
            "hosts": (manifest('hosts = ["https://example.org/x"]'), CODE, "hosts is a list of host names"),
            "reads": (manifest('reads = ["proc"]'), CODE, "reads is a list of absolute paths"),
            "missing": (manifest(), "def do_other():\n    pass\n", "does not define do_go"),
            "params": (manifest(), "def do_go(path=None):\n    pass\n", "exactly the declared parameters: path, text"),
            "defaults": (manifest(), "def do_go(path, text=None):\n    pass\n", "must give every parameter of do_go a default"),
            "syntax": (manifest(), "def do_go(:\n", "commands.py does not parse"),
            "toml": ("name = ", CODE, "was left out"),
            "name": (manifest().replace('"x"', '"X y"'), CODE, "a plugin name is lower-case letters and digits"),
        }
        for folder, (text, code, _) in faults.items():
            table, problems = self.plugin(text, code, folder=folder)
        table, problems = self.plugin(manifest().replace('"x"', '"good"'), CODE, folder="zz-good")
        self.assertEqual(set(table), {"good.go"})
        self.assertEqual(len(problems), len(faults))
        for problem, (folder, (_, _, said)) in zip(problems, sorted(faults.items())):
            self.assertIn(f"plugins/{folder} was left out", problem)
            self.assertIn(said, problem)

    def test_two_folders_cannot_define_one_command(self):
        self.plugin(manifest(), CODE, folder="a")
        table, problems = self.plugin(manifest(), CODE, folder="b")
        self.assertEqual(table["x.go"].source.parent.name, "a")
        self.assertIn("x.go is already defined in", problems[0])
