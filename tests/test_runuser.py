"""The web service is an ordinary user: the code is root's, the state is the service's, and the service can only ask systemd for three things."""
import json
import os
import re
import subprocess
import unittest

from support import ROOT, core
import rebootupdate_update as up
import rebootupdate_web as ru


def read(*parts):
    with open(os.path.join(ROOT, *parts)) as f:
        return f.read()


class FoldersTests(unittest.TestCase):
    def test_project_json_and_the_installer_agree_on_the_folders(self):
        project = json.loads(read("project.json"))
        install = read("install.sh")
        self.assertEqual(re.search(r"^DEST=(\S+)", install, re.M).group(1), project["install_dir"])
        self.assertEqual(re.search(r"^DATA=(\S+)", install, re.M).group(1), project["data_dir"])
        self.assertEqual(re.search(r"^RUN_USER=(\S+)", install, re.M).group(1), project["run_user"])
        self.assertNotEqual(project["install_dir"], project["data_dir"])
        self.assertIn(project["install_dir"], read("uninstall.sh"))
        self.assertIn(project["data_dir"], read("uninstall.sh"))

    def test_what_only_the_installer_writes_is_not_in_the_services_folder(self):
        for path in (core.ADMIN_PIN, up.ADDON_SRC, up.UPDATE_ORIGIN, up.UPDATE_BRANCH, up.INSTALL_PORTS, up.ADDON_COMMIT, up.VERSION_FILE):
            self.assertTrue(path.startswith(core.INSTALL_DIR + "/"), path)
        project = json.loads(read("project.json"))
        self.assertFalse(project["data_dir"].startswith(project["install_dir"] + "/"))
        self.assertFalse(project["install_dir"].startswith(project["data_dir"] + "/"))

    def test_the_updater_status_is_in_a_folder_the_service_can_not_write(self):
        self.assertNotEqual(os.path.dirname(up.UPDATE_STATUS), os.path.dirname(core.TMP_PREFIX))      # not the folder the service owns
        self.assertEqual(os.path.dirname(up.UPDATE_STATUS), os.path.dirname(up.UPDATE_LOG))


class UnitTests(unittest.TestCase):
    def test_the_service_unit_is_not_root(self):
        unit = read("install.sh")
        unit = unit[unit.index("[Service]"):unit.index("[Install]")]
        for line in ("User=$RUN_USER", "NoNewPrivileges=yes", "ProtectSystem=strict", "ReadWritePaths=$DATA",
                     "CapabilityBoundingSet=CAP_NET_BIND_SERVICE", "AmbientCapabilities=CAP_NET_BIND_SERVICE"):
            self.assertIn(line, unit)
        self.assertNotIn("Nice=", unit)                         # a negative nice value needs a capability the service does not have

    def test_install_refuses_root_as_the_service_user(self):
        install = read("install.sh")
        self.assertRegex(install, r"case \"\$RUN_USER\" in [^\n]*root[^\n]*exit 1")

    def test_the_polkit_rule_names_exactly_three_units_and_the_verb_start(self):
        rule = read("modules", "rebootupdate", "install.sh")
        units = re.findall(r'unit == "([^"]+)"', rule)
        self.assertEqual(sorted(units), ["checkin-board-reboot.service", "checkin-board-update@git.service", "checkin-board-update@usb.service"])
        self.assertIn('action.lookup("verb") == "start"', rule)
        self.assertIn('subject.user == "$RUN_USER"', rule)
        self.assertEqual(up.UPDATE_UNIT % "git", "checkin-board-update@git.service")
        self.assertEqual(up.UPDATE_UNIT % "usb", "checkin-board-update@usb.service")
        self.assertEqual(ru.REBOOT_UNIT, "checkin-board-reboot.service")

    def test_scripts_are_valid_shell(self):
        for path in ("install.sh", "uninstall.sh", "modules/rebootupdate/install.sh", "modules/rebootupdate/remove.sh", "modules/rebootupdate/update-run.sh"):
            p = subprocess.run(["sh", "-n", os.path.join(ROOT, path)], stderr=subprocess.PIPE)
            self.assertEqual(p.returncode, 0, path + p.stderr.decode())

    def test_an_update_keeps_the_user_and_migrates_the_old_state_folder(self):
        install = read("install.sh")
        self.assertIn('"$DEST/run_user"', install)
        self.assertIn('mv "$DEST/$ns_name" "$DATA/$ns_name"', install)
        self.assertIn('chown -R "$RUN_USER:$RUN_GROUP" "$DATA"', install)
        self.assertIn("umask 022", install)          # copied files must be readable by the service whatever the shell's umask


if __name__ == "__main__":
    unittest.main()
