"""Repo-level guards: the shell scripts must parse, every Python file must compile, the docs link to files that exist."""
import glob
import os
import py_compile
import shutil
import subprocess
import tempfile
import unittest

from support import ROOT


class LayeringTests(unittest.TestCase):
    """The small services must not drag the web server in."""
    def test_services_do_not_import_the_web_module(self):
        for mod in ("base_core", "netswitch_probes", "netswitch_contacts", "netswitch_checkin"):
            code = ("import sys; sys.path[:0] = %r; import %s; sys.exit(1 if 'base_web' in sys.modules else 0)"
                    % ([ROOT, os.path.join(ROOT, "base")] + [os.path.join(ROOT, "modules", m) for m in os.listdir(os.path.join(ROOT, "modules"))], mod))
            self.assertEqual(subprocess.call(["python3", "-c", code]), 0, mod)

    def test_core_does_not_import_probes(self):
        code = "import sys; sys.path[:0] = %r; import base_core; sys.exit(1 if 'netswitch_probes' in sys.modules else 0)" % [ROOT, os.path.join(ROOT, "base")]
        self.assertEqual(subprocess.call(["python3", "-c", code]), 0)


class DocsTests(unittest.TestCase):
    def test_markdown_links_resolve(self):
        import re
        files = [os.path.join(ROOT, "CLAUDE.md"), os.path.join(ROOT, "README.md")] + glob.glob(os.path.join(ROOT, "docs", "*.md"))
        for path in files:
            with open(path, encoding="utf-8") as f:
                text = f.read()
            heads = set(re.sub(r"[^a-z0-9 -]", "", h.lower()).strip().replace(" ", "-") for h in re.findall(r"^#+\s+(.*)$", text, re.M))
            for target in re.findall(r"\]\(([^)\s]+)\)", text):
                if target.startswith(("http://", "https://", "mailto:")):
                    continue
                if target.startswith("#"):
                    self.assertIn(target[1:], heads, "%s: broken anchor %s" % (os.path.basename(path), target))
                else:
                    rel = target.split("#")[0]
                    self.assertTrue(os.path.exists(os.path.join(os.path.dirname(path), rel)),
                                    "%s: missing %s" % (os.path.basename(path), target))


class CompileTests(unittest.TestCase):
    def test_python_files_compile(self):
        for path in glob.glob(os.path.join(ROOT, "*.py")) + glob.glob(os.path.join(ROOT, "tests", "*.py")) + glob.glob(os.path.join(ROOT, "modules", "*", "*.py")):
            out = os.path.join(tempfile.mkdtemp(), "x.pyc")
            py_compile.compile(path, cfile=out, doraise=True)

    def test_shell_scripts_parse(self):
        sh = shutil.which("sh")
        for path in glob.glob(os.path.join(ROOT, "*.sh")) + glob.glob(os.path.join(ROOT, "tests", "*.sh")) + glob.glob(os.path.join(ROOT, "modules", "*", "*.sh")):
            p = subprocess.run([sh, "-n", path], stderr=subprocess.PIPE)
            self.assertEqual(p.returncode, 0, "%s: %s" % (path, p.stderr.decode()))


if __name__ == "__main__":
    unittest.main()
