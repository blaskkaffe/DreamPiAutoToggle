"""The base is a framework that other projects can use: no word of this project (its modules, its hardware, its networks) is in base/."""
import glob
import os
import re
import unittest

from support import ROOT

FORBIDDEN = re.compile(r"switcher|dcnow|dcnet|dreampi|netswitch|modem|wifi|wi-fi|openmenu|dtmf|netlink|dreamcast|raspberry|"
                       r"debuglog|rebootupdate|imagebg|\bleds?\b", re.I)


def base_files():
    return sorted(glob.glob(os.path.join(ROOT, "base", "*.py")) + glob.glob(os.path.join(ROOT, "base", "*.json")) +
                  glob.glob(os.path.join(ROOT, "base", "page", "*")))


class BaseIsNeutral(unittest.TestCase):
    def test_no_project_words_in_the_base(self):
        found = []
        for path in base_files():
            with open(path) as f:
                for n, line in enumerate(f, 1):
                    m = FORBIDDEN.search(line)
                    if m:
                        found.append("%s:%d: %s" % (os.path.relpath(path, ROOT), n, m.group(0)))
        self.assertEqual(found, [], "\n".join(found[:20]))

    def test_the_base_imports_only_itself_and_the_standard_library(self):
        for path in glob.glob(os.path.join(ROOT, "base", "*.py")):
            with open(path) as f:
                for line in f:
                    m = re.match(r"\s*(?:import|from)\s+(\w+)", line)
                    if m and m.group(1).startswith(("netswitch_", "tests")):
                        self.fail("%s imports %s" % (path, m.group(1)))

    def test_the_project_is_named_in_project_json_only(self):
        import json
        with open(os.path.join(ROOT, "project.json")) as f:
            project = json.load(f)
        for key in ("name", "title", "data_dir", "tmp_prefix", "service", "icon", "touch_icon"):
            self.assertIn(key, project)


if __name__ == "__main__":
    unittest.main()
