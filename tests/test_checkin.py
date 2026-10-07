"""The contacts module (CSV import) and the check-in board (who is in, statuses, colours, the same state for every screen)."""
import json
import os
import threading
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from support import web, core, sandbox, cleanup
import netswitch_contacts as contacts
import netswitch_checkin as checkin

CSV = u"""# a comment line
name,department,role,phone,location,restrictToLocation
Anna Svensson,Kök,Kökschef,070-1,Område A,
Erik Lindqvist,Kök,Kock,,Område A,
Maja Berg,Servering,,,Område B,x
Ola Nordin,,Chef,,,
"""


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = sandbox()

    def tearDown(self):
        cleanup(self.tmp)

    def people(self):
        return dict((p["name"], p) for g in checkin.snapshot()["groups"] for p in g["people"])


class ImportTests(Base):
    def test_a_csv_makes_people_and_a_second_import_changes_nothing(self):
        r = contacts.import_csv(CSV)
        self.assertEqual((r["added"], r["changed"], r["unchanged"], r["skipped"]), (4, 0, 0, 0))
        again = contacts.import_csv(CSV)
        self.assertEqual((again["added"], again["changed"], again["unchanged"]), (0, 0, 4))
        self.assertEqual(len(contacts.read()["people"]), 4)

    def test_a_person_without_a_department_gets_a_name_for_it(self):
        contacts.import_csv(CSV)
        ola = [p for p in contacts.read()["people"] if p["name"] == "Ola Nordin"][0]
        self.assertEqual(ola["department"], contacts.NO_DEPARTMENT)

    def test_the_restrict_flag_and_changed_rows(self):
        contacts.import_csv(CSV)
        maja = [p for p in contacts.read()["people"] if p["name"] == "Maja Berg"][0]
        self.assertTrue(maja["restrictToLocation"])
        r = contacts.import_csv(CSV.replace("Kökschef", "Chef kök"))
        self.assertEqual((r["added"], r["changed"], r["unchanged"]), (0, 1, 3))

    def test_a_reimport_keeps_who_is_in(self):
        contacts.import_csv(CSV)
        anna = self.people()["Anna Svensson"]["id"]
        checkin.toggle(anna)
        contacts.import_csv(CSV.replace("Kökschef", "Chef kök"))
        self.assertTrue(self.people()["Anna Svensson"]["in"])

    def test_replace_switches_off_people_that_are_not_in_the_file(self):
        contacts.import_csv(CSV)
        r = contacts.import_csv(u"name,department,location\nAnna Svensson,Kök,Område A\n", replace=True)
        self.assertEqual(r["deactivated"], 3)
        self.assertEqual(sorted(self.people()), ["Anna Svensson"])          # the others are gone from the board, but still on file
        self.assertEqual(len(contacts.read()["people"]), 4)

    def test_delimiters_swedish_headers_and_bad_files(self):
        r = contacts.import_csv(u"namn;avdelning;telefon\nSara Ek;Lager;123\n")
        self.assertEqual(r["added"], 1)
        p = contacts.read()["people"][0]
        self.assertEqual((p["name"], p["department"], p["phone"]), ("Sara Ek", "Lager", "123"))
        with self.assertRaises(ValueError):
            contacts.import_csv(u"foo,bar\n1,2\n")
        self.assertEqual(contacts.import_csv(u"")["added"], 0)

    def test_the_view_counts_and_the_export_round_trips(self):
        contacts.import_csv(CSV)
        v = contacts.view()
        self.assertEqual(v["count"], 4)
        self.assertIn("4 people in 3 departments and 2 buildings", v["text"])
        out = contacts.export_csv()
        self.assertTrue(out.startswith("name,department,role,phone,location,restrictToLocation"))
        os.remove(core.CONTACTS)
        self.assertEqual(contacts.import_csv(out)["added"], 4)


class BoardTests(Base):
    def setUp(self):
        Base.setUp(self)
        contacts.import_csv(CSV)

    def test_everyone_starts_out_and_grey(self):
        snap = checkin.snapshot()
        self.assertEqual((snap["total"], snap["in"]), (4, 0))
        self.assertEqual([g["title"] for g in snap["groups"]], ["Kök", "No department", "Servering"])
        for p in self.people().values():
            self.assertEqual((p["in"], p["colour"], p["state"]), (False, "", "Out"))

    def test_a_tap_switches_in_and_out_and_the_colour_follows_the_department(self):
        anna, erik = self.people()["Anna Svensson"], self.people()["Erik Lindqvist"]
        checkin.toggle(anna["id"])
        a = self.people()["Anna Svensson"]
        self.assertTrue(a["in"])
        self.assertIn(a["colour"], core.PALETTE_IDS)
        checkin.toggle(erik["id"])
        self.assertEqual(self.people()["Erik Lindqvist"]["colour"], a["colour"])        # same department, same colour
        checkin.toggle(anna["id"])
        self.assertEqual(self.people()["Anna Svensson"]["colour"], "")
        self.assertEqual(checkin.snapshot()["in"], 1)

    def test_colour_by_building_and_own_picks(self):
        checkin.save_config({"colour_by": "building"})
        for n in ("Anna Svensson", "Erik Lindqvist", "Maja Berg"):
            checkin.toggle(self.people()[n]["id"])
        got = self.people()
        self.assertEqual(got["Anna Svensson"]["colour"], got["Erik Lindqvist"]["colour"])       # both in Område A
        self.assertNotEqual(got["Anna Svensson"]["colour"], got["Maja Berg"]["colour"])
        checkin.set_group_colour("building", "Område B", "purple")
        self.assertEqual(self.people()["Maja Berg"]["colour"], "purple")
        checkin.set_group_colour("building", "Område B", "")                                    # back to the automatic one
        self.assertNotEqual(self.people()["Maja Berg"]["colour"], "purple")
        self.assertIsNone(checkin.set_group_colour("building", "Område B", "network"))          # not a palette colour
        self.assertIsNone(checkin.set_group_colour("floor", "x", "red"))

    def test_grouping_by_building(self):
        checkin.save_config({"group_by": "building"})
        self.assertEqual([g["title"] for g in checkin.snapshot()["groups"]], ["No building", "Område A", "Område B"])

    def test_a_status_takes_its_colour_and_name_and_checks_out(self):
        anna = self.people()["Anna Svensson"]["id"]
        checkin.toggle(anna)
        checkin.set_status(anna, "SICK")
        a = self.people()["Anna Svensson"]
        self.assertEqual((a["status"], a["text"], a["colour"], a["in"], a["state"]), ("SICK", "Sjuk", "red", False, "Status"))
        checkin.set_status(anna, "FYS")                      # a neutral status keeps in / out
        checkin.set_status(anna, "IN")
        self.assertEqual((self.people()["Anna Svensson"]["status"], self.people()["Anna Svensson"]["in"]), ("", True))

    def test_statuses_that_need_a_time_a_date_or_a_note(self):
        anna = self.people()["Anna Svensson"]["id"]
        checkin.set_status(anna, "LATE", "8:15")
        self.assertEqual(self.people()["Anna Svensson"]["text"], "Kommer sent · 8:15")
        checkin.set_status(anna, "LATE", "soon")             # not a time: the status' own default
        self.assertEqual(self.people()["Anna Svensson"]["text"], "Kommer sent · 07:30")
        checkin.set_status(anna, "TRAVEL", "2026-12-24")
        self.assertEqual(self.people()["Anna Svensson"]["text"], "Tjänsteresa · tillbaka 24/12")
        checkin.set_status(anna, "OTHER", "  Dentist   at   3 ")
        self.assertEqual(self.people()["Anna Svensson"]["text"], "Annat · Dentist at 3")
        checkin.set_status(anna, "OTHER", "x" * 200)
        self.assertEqual(len(self.people()["Anna Svensson"]["detail"]), checkin.DETAIL_MAX)

    def test_a_tap_clears_a_status(self):
        anna = self.people()["Anna Svensson"]["id"]
        checkin.set_status(anna, "SICK")
        checkin.toggle(anna)
        a = self.people()["Anna Svensson"]
        self.assertEqual((a["status"], a["in"]), ("", True))

    def test_unknown_people_and_statuses_are_refused(self):
        anna = self.people()["Anna Svensson"]["id"]
        self.assertIsNone(checkin.toggle("nobody"))
        self.assertIsNone(checkin.set_status("nobody", "SICK"))
        self.assertIsNone(checkin.set_status(anna, "NOPE"))
        self.assertEqual(checkin.snapshot()["in"], 0)

    def test_all_in_and_all_out(self):
        checkin.set_status(self.people()["Anna Svensson"]["id"], "SICK")
        self.assertEqual(checkin.set_all(True)["in"], 4)
        self.assertEqual(self.people()["Anna Svensson"]["status"], "")
        self.assertEqual(checkin.set_all(False)["in"], 0)

    def test_every_change_bumps_the_revision(self):
        anna = self.people()["Anna Svensson"]["id"]
        before = checkin.snapshot()["rev"]
        checkin.toggle(anna)
        self.assertEqual(int(checkin.snapshot()["rev"].split(".")[0]), int(before.split(".")[0]) + 1)

    def test_an_import_changes_the_revision_too(self):
        before = checkin.snapshot()["rev"]
        contacts.import_csv(u"name,department\nNy Person,Lager\n")
        self.assertNotEqual(checkin.snapshot()["rev"], before)          # so every screen draws the new person

    def test_default_statuses_use_only_palette_colours(self):
        for s in checkin.statuses():
            self.assertIn(s["colour"], core.PALETTE_IDS, s)
        self.assertGreaterEqual(len(checkin.statuses()), 10)

    def test_a_damaged_state_file_starts_over(self):
        with open(core.CHECKIN, "w") as f:
            f.write("{oops")
        self.assertEqual(checkin.snapshot()["in"], 0)
        self.assertEqual(checkin.snapshot()["total"], 4)


    def test_a_person_can_be_edited_and_keeps_the_status_and_a_reimport_finds_them(self):
        anna = self.people()["Anna Svensson"]
        checkin.toggle(anna["id"])
        got = contacts.update_person(anna["id"], {"name": "Anna S", "role": "Köksmästare", "phone": "070-9", "department": "Servering"})
        self.assertEqual((got["id"], got["name"], got["department"]), (anna["id"], "Anna S", "Servering"))
        p = self.people()["Anna S"]
        self.assertEqual((p["id"], p["in"], p["department"], p["role"]), (anna["id"], True, "Servering", "Köksmästare"))      # still in, same person
        r = contacts.import_csv(u"name,department,location\nAnna S,Servering,Område A\n")
        self.assertEqual((r["added"], len(contacts.read()["people"])), (0, 4))                                                  # found by the edited values
        with self.assertRaises(ValueError):
            contacts.update_person(anna["id"], {"name": " "})
        with self.assertRaises(ValueError):
            contacts.update_person("pnobody", {"name": "x"})
        erik = self.people()["Erik Lindqvist"]
        with self.assertRaises(ValueError):
            contacts.update_person(erik["id"], {"name": "Anna S", "department": "Servering", "location": "Område A"})            # would be a double

    def test_a_person_can_be_deleted_with_the_photo(self):
        anna = self.people()["Anna Svensson"]
        os.makedirs(core.PHOTOS_DIR, exist_ok=True)
        open(os.path.join(core.PHOTOS_DIR, anna["id"] + ".jpg"), "wb").write(b"x")
        self.assertTrue(contacts.delete_person(anna["id"]))
        self.assertNotIn("Anna Svensson", self.people())
        self.assertEqual(checkin.snapshot()["total"], 3)
        self.assertFalse(os.path.exists(os.path.join(core.PHOTOS_DIR, anna["id"] + ".jpg")))
        self.assertFalse(contacts.delete_person(anna["id"]))
        self.assertFalse(contacts.delete_person(""))

    def test_the_order_of_the_boxes_is_kept(self):
        self.assertEqual([g["title"] for g in checkin.snapshot()["groups"]], ["Kök", "No department", "Servering"])
        checkin.set_group_order(["Servering", "Kök"])
        self.assertEqual([g["title"] for g in checkin.snapshot()["groups"]], ["Servering", "Kök", "No department"])       # unknown ones follow
        self.assertIsNone(checkin.set_group_order("Kök"))
        self.assertIsNone(checkin.set_group_order([1]))
        checkin.set_group_order(["Servering", "Servering", "Gone"])                                                    # doubles dropped, a missing name is harmless
        self.assertEqual(checkin.config()["group_order"], ["Servering", "Gone"])
        self.assertEqual([g["title"] for g in checkin.snapshot()["groups"]], ["Servering", "Kök", "No department"])


class HttpTests(Base):
    """Two 'screens' (two clients) see the same board: a change made by one is in the other's next /api answer."""
    def setUp(self):
        Base.setUp(self)
        contacts.import_csv(CSV)
        self.srv = web.Server(("127.0.0.1", 0), web.Handler)
        self.base = "http://127.0.0.1:%d" % self.srv.server_address[1]
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()
        Base.tearDown(self)

    def get(self, path):
        return json.loads(urlopen(self.base + path, timeout=10).read().decode())

    def post(self, path, body):
        req = Request(self.base + path, data=json.dumps(body).encode(), method="POST",
                      headers={"X-Requested-With": "x", "Content-Type": "application/json"})
        return json.loads(urlopen(req, timeout=10).read().decode())

    def test_the_api_carries_the_board_and_a_tap_shows_in_the_next_answer(self):
        board = self.get("/api")["checkin"]
        self.assertEqual(board["total"], 4)
        anna = [p for g in board["groups"] for p in g["people"] if p["name"] == "Anna Svensson"][0]["id"]
        r = self.post("/checkin/toggle", {"id": anna})
        self.assertEqual(r["checkin"]["in"], 1)
        after = self.get("/api")["checkin"]                  # what the other screen reads a second later
        self.assertEqual((after["in"], after["rev"]), (1, r["checkin"]["rev"]))
        self.post("/checkin/status", {"id": anna, "code": "VACATION", "detail": "2026-07-01"})
        text = [p["text"] for g in self.get("/api")["checkin"]["groups"] for p in g["people"] if p["id"] == anna][0]
        self.assertEqual(text, "Semester · tillbaka 1/7")

    def test_a_person_is_edited_over_http(self):
        board = self.get("/api")["checkin"]
        anna = [p for g in board["groups"] for p in g["people"] if p["name"] == "Anna Svensson"][0]["id"]
        self.assertEqual(self.post("/contacts/person", {"id": anna, "role": "Chef"})["ok"], True)
        got = [p for g in self.get("/api")["checkin"]["groups"] for p in g["people"] if p["id"] == anna][0]
        self.assertEqual(got["role"], "Chef")
        with self.assertRaises(HTTPError) as e:
            self.post("/contacts/person", {"id": anna, "name": ""})
        self.assertEqual(e.exception.code, 400)

    def test_a_person_is_deleted_over_http(self):
        board = self.get("/api")["checkin"]
        anna = [p for g in board["groups"] for p in g["people"] if p["name"] == "Anna Svensson"][0]["id"]
        self.assertTrue(self.post("/contacts/delete", {"id": anna})["ok"])
        self.assertEqual(self.get("/api")["checkin"]["total"], 3)
        with self.assertRaises(HTTPError) as e:
            self.post("/contacts/delete", {"id": anna})
        self.assertEqual(e.exception.code, 400)

    def test_the_order_of_the_boxes_is_posted_and_seen_by_the_other_screen(self):
        r = self.post("/checkin/order", {"order": ["Servering", "Kök"]})
        self.assertEqual([g["title"] for g in r["checkin"]["groups"]][:2], ["Servering", "Kök"])
        self.assertEqual([g["title"] for g in self.get("/api")["checkin"]["groups"]][:2], ["Servering", "Kök"])
        with self.assertRaises(HTTPError) as e:
            self.post("/checkin/order", {"order": "Kök"})
        self.assertEqual(e.exception.code, 400)

    def test_bad_requests(self):
        for path, body in (("/checkin/toggle", {"id": "nobody"}), ("/checkin/status", {"id": "x", "code": "SICK"}), ("/checkin/colour", {"kind": "floor", "name": "x"})):
            with self.assertRaises(HTTPError) as e:
                self.post(path, body)
            self.assertEqual(e.exception.code, 400, path)
        req = Request(self.base + "/checkin/toggle", data=b"{}", method="POST")          # not from the page
        with self.assertRaises(HTTPError) as e:
            urlopen(req, timeout=10)
        self.assertEqual(e.exception.code, 403)

    def test_settings_and_colour_endpoints(self):
        r = self.get("/checkin/config")
        self.assertEqual(r["values"], {"show_title": True, "group_by": "department", "colour_by": "department", "show_roles": True, "show_buildings": False,
                                       "keyboard": False, "roles_shown": None, "buildings_shown": None})
        self.assertEqual([x["key"] for x in r["colours"]["department"]], ["Kök", "No department", "Servering"])
        r = self.post("/checkin/config", {"values": {"colour_by": "building", "group_by": "nonsense", "show_title": False}})
        self.assertEqual((r["values"]["show_title"], r["values"]["group_by"], r["values"]["colour_by"]), (False, "department", "building"))
        r = self.post("/checkin/config", {"values": {"show_buildings": True, "keyboard": True, "roles_shown": ["Chef", 3], "buildings_shown": "x", "show_roles": "no"}})
        v = r["values"]
        self.assertEqual((v["show_buildings"], v["keyboard"], v["roles_shown"], v["buildings_shown"], v["show_roles"]), (True, True, ["Chef"], None, True))     # bad values are ignored
        self.assertIn("Kökschef", [o["value"] for o in r["options"]["roles"]])
        self.assertEqual([o["value"] for o in r["options"]["buildings"]], ["Område A", "Område B"])
        board = self.get("/api")["checkin"]
        self.assertEqual((board["show_buildings"], board["keyboard"], board["roles_shown"]), (True, True, ["Chef"]))
        self.post("/checkin/config", {"values": {"roles_shown": None}})
        self.assertFalse(self.get("/api")["checkin"]["show_title"])
        r = self.post("/checkin/colour", {"kind": "department", "name": "Kök", "colour": "bright-pink"})
        self.assertEqual([x for x in r["colours"]["department"] if x["key"] == "Kök"][0]["colour"], "bright-pink")

    def test_people_can_be_switched_off_and_on_the_board(self):
        anna = [p for g in self.get("/api")["checkin"]["groups"] for p in g["people"] if p["name"] == "Anna Svensson"][0]["id"]
        self.post("/contacts/active", {"id": anna, "value": False})
        self.assertEqual(self.get("/api")["checkin"]["total"], 3)
        self.assertEqual([p["active"] for p in self.get("/contacts")["people"] if p["title"] == "Anna Svensson"], [False])
        self.post("/contacts/active", {"id": anna, "value": True})
        self.assertEqual(self.get("/api")["checkin"]["total"], 4)

    def test_import_over_http(self):
        r = self.post("/contacts/import", {"csv": u"name,department\nNy Person,Lager\n"})
        self.assertTrue(r["ok"])
        self.assertIn("1 new", r["message"])
        self.assertEqual(self.get("/contacts")["count"], 5)
        with self.assertRaises(HTTPError) as e:
            self.post("/contacts/import", {"csv": u"nothing useful"})
        self.assertEqual(e.exception.code, 400)
        self.assertIn("Ny Person", urlopen(self.base + "/contacts.csv", timeout=10).read().decode())

    def test_a_photo_is_kept_served_and_shown_on_the_board(self):
        import base64
        board = self.get("/api")["checkin"]
        anna = [p for g in board["groups"] for p in g["people"] if p["name"] == "Anna Svensson"][0]
        self.assertEqual(anna["photo"], "")
        png = base64.b64encode(b"\x89PNG\r\n\x1a\n" + b"x" * 40).decode()
        r = self.post("/contacts/photo", {"id": anna["id"], "photo": "data:image/png;base64," + png})
        self.assertTrue(r["ok"])
        after = [p for g in self.get("/api")["checkin"]["groups"] for p in g["people"] if p["id"] == anna["id"]][0]
        self.assertTrue(after["photo"].startswith("/contacts/photo/" + anna["id"] + "?v="))
        got = urlopen(self.base + after["photo"], timeout=10)
        self.assertEqual((got.status, got.headers["Content-Type"]), (200, "image/png"))
        self.assertNotEqual(self.get("/api")["checkin"]["rev"], board["rev"])        # every screen draws the new photo
        self.post("/contacts/photo", {"id": anna["id"], "photo": ""})                # removing it
        with self.assertRaises(HTTPError) as e:
            urlopen(self.base + "/contacts/photo/" + anna["id"], timeout=10)
        self.assertEqual(e.exception.code, 404)

    def test_bad_photos_are_refused(self):
        import base64
        anna = [p for g in self.get("/api")["checkin"]["groups"] for p in g["people"]][0]["id"]
        for photo in ("data:image/gif;base64,AAAA", "data:image/png;base64," + base64.b64encode(b"not a png").decode(),
                      "data:image/jpeg;base64," + base64.b64encode(b"\xff\xd8\xff" + b"x" * 200000).decode(), "javascript:alert(1)"):
            with self.assertRaises(HTTPError) as e:
                self.post("/contacts/photo", {"id": anna, "photo": photo})
            self.assertEqual(e.exception.code, 400, photo[:30])
        with self.assertRaises(HTTPError) as e:
            self.post("/contacts/photo", {"id": "p0000000000", "photo": ""})            # nobody by that id
        self.assertEqual(e.exception.code, 400)
        with self.assertRaises(HTTPError) as e:
            urlopen(self.base + "/contacts/photo/..%2f..%2fetc%2fpasswd", timeout=10)    # no way out of the photo folder
        self.assertEqual(e.exception.code, 404)

    def test_the_board_works_with_the_contacts_module_off(self):
        core.save_module_enabled("contacts", False)
        web.refresh_page(force=True)
        self.assertEqual(self.get("/api")["checkin"]["total"], 4)           # the roster stays; only its import box is gone
        with self.assertRaises(HTTPError) as e:
            self.get("/contacts")
        self.assertEqual(e.exception.code, 404)


if __name__ == "__main__":
    unittest.main()
