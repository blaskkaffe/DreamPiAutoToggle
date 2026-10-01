"""Repo-level guards: the DreamPi hook must stay Python 2.7 compatible, the
shell scripts must parse, and every Python file must compile."""
import ast
import glob
import os
import py_compile
import shutil
import subprocess
import tempfile
import unittest

from support import ROOT


class HookCompatTests(unittest.TestCase):
    """netswitch_hook.py runs inside DreamPi on Python 2.7."""
    def test_no_python3_only_syntax(self):
        with open(os.path.join(ROOT, "netswitch_hook.py")) as f:
            tree = ast.parse(f.read())
        for node in ast.walk(tree):
            self.assertNotIsInstance(node, ast.JoinedStr, "f-string at line %d" % getattr(node, "lineno", 0))
            self.assertNotIsInstance(node, (ast.AnnAssign, ast.AsyncFunctionDef, ast.NamedExpr),
                                     "Python 3 syntax at line %d" % getattr(node, "lineno", 0))
            if isinstance(node, ast.FunctionDef):
                self.assertIsNone(node.returns, "return annotation on %s" % node.name)
                for a in node.args.args + node.args.kwonlyargs:
                    self.assertIsNone(a.annotation, "annotation on %s(%s)" % (node.name, a.arg))
                self.assertEqual(node.args.kwonlyargs, [], "keyword-only args in %s" % node.name)

    def test_no_python3_only_imports(self):
        with open(os.path.join(ROOT, "netswitch_hook.py")) as f:
            tree = ast.parse(f.read())
        top = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                top.update(a.name.split(".")[0] for a in node.names)
            elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
                top.add(node.module.split(".")[0])
        self.assertFalse(top & {"pathlib", "typing", "asyncio", "subprocess32", "dataclasses", "enum", "secrets"}, top)


class LayeringTests(unittest.TestCase):
    """The small services must not drag the web server in."""
    def test_led_and_buttons_do_not_import_the_web_module(self):
        for mod in ("netswitch_led", "netswitch_buttons", "netswitch_core", "netswitch_probes"):
            code = "import sys; sys.path.insert(0, %r); import %s; sys.exit(1 if 'netswitch_web' in sys.modules else 0)" % (ROOT, mod)
            self.assertEqual(subprocess.call(["python3", "-c", code]), 0, mod)

    def test_core_does_not_import_probes(self):
        code = "import sys; sys.path.insert(0, %r); import netswitch_core; sys.exit(1 if 'netswitch_probes' in sys.modules else 0)" % ROOT
        self.assertEqual(subprocess.call(["python3", "-c", code]), 0)


class CompileTests(unittest.TestCase):
    def test_python_files_compile(self):
        for path in glob.glob(os.path.join(ROOT, "*.py")) + glob.glob(os.path.join(ROOT, "tests", "*.py")):
            out = os.path.join(tempfile.mkdtemp(), "x.pyc")
            py_compile.compile(path, cfile=out, doraise=True)

    def test_shell_scripts_parse(self):
        sh = shutil.which("sh")
        for path in glob.glob(os.path.join(ROOT, "*.sh")) + glob.glob(os.path.join(ROOT, "tests", "*.sh")):
            p = subprocess.run([sh, "-n", path], stderr=subprocess.PIPE)
            self.assertEqual(p.returncode, 0, "%s: %s" % (path, p.stderr.decode()))


if __name__ == "__main__":
    unittest.main()
