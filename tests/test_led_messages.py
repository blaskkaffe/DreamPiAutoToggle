"""The LED messages and colour groups: the catalogue, the saved groups, what is true when, and which look wins."""
import json
import os
import unittest

from support import ledconfig, core, sandbox, cleanup
import netswitch_led as led

KEYS = [m[0] for m in ledconfig.MESSAGES]
DEFAULT_ON = {"busy", "ready-dcnow", "ready-dcnet", "notrunning", "call-dcnow", "call-dcnet", "call-other", "sel-dcnow", "sel-dcnet", "event-soon"}


def ctx(state="ok", selected="dcnow", net=None, wifi="idle", update="idle", info=None, reboot=False, dcnet_problem=False, players=None):
    return {"state": state, "selected": selected, "net": net or {}, "wifi": wifi, "update": update,
            "update_info": info or {}, "reboot": reboot, "dcnet_problem": dcnet_problem, "players": players or {}}


GOOD = {"network": True, "internet": True, "modem": True}          # a healthy Pi, as the web service reports it


def group(gid, colour, messages, **kw):
    g = {"id": gid, "colour": colour, "effect": "solid", "speed": "slow", "brightness": None, "leds": None, "messages": messages}
    g.update(kw)
    return g


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = sandbox()

    def tearDown(self):
        cleanup(self.tmp)

    def groups(self, *groups):
        cfg = ledconfig.led_config()
        cfg["groups"] = list(groups)
        ledconfig.save_led_config(cfg)

    def looks(self, c):
        return ledconfig.active_messages(c)


class CatalogueTests(Base):
    def test_every_message_has_a_category_a_priority_and_a_description(self):
        cats = set(c[0] for c in ledconfig.CATEGORIES)
        for m in ledconfig.MESSAGES:
            self.assertIn(m[2], cats, m[0])
            self.assertTrue(m[1] and m[3], m[0])
            if m[0] != "off":
                self.assertIn(m[0], ledconfig.PRIORITY_ORDER, m[0])
        self.assertEqual(sorted(ledconfig.PRIORITY_ORDER), sorted(k for k in KEYS if k != "off"))
        self.assertEqual(len(KEYS), len(set(KEYS)))
        for c in cats:
            self.assertTrue([m for m in ledconfig.MESSAGES if m[2] == c], c)

    def test_the_requested_messages_are_there(self):
        for key in ("busy", "ready-dcnow", "ready-dcnet", "notrunning", "unknown", "call-dcnow", "call-dcnet", "call-other", "sel-dcnow", "sel-dcnet", "no-ip",
                    "no-network", "no-internet", "internet-ok", "dns-fail", "ethernet", "wifi", "wifi-weak", "net-slow", "modem-ok", "modem-missing",
                    "undervoltage", "throttled", "hot", "warm", "wifisetup-scan", "wifisetup-choose", "wifisetup-connecting", "wifisetup-ok",
                    "wifisetup-failed", "update-addon", "update-dreampi", "update-running", "update-ok", "update-failed", "reboot", "players-game",
                    "players-friend", "ok", "error", "warning", "off"):
            self.assertIn(key, KEYS)

    def test_state_unknown_explains_itself(self):
        text = ledconfig.MESSAGE["unknown"][3]
        self.assertIn("state file", text)
        self.assertIn("last resort", text)

    def test_only_the_default_messages_are_in_a_group_at_the_start(self):
        placed = [k for g in ledconfig.default_groups() for k in g["messages"]]
        self.assertEqual(set(placed), DEFAULT_ON)
        self.assertEqual(len(placed), len(set(placed)))                  # none twice

    def test_the_default_looks(self):
        by = dict((g["id"], g) for g in ledconfig.default_groups())
        self.assertEqual([(g["colour"], g["effect"]) for g in ledconfig.default_groups()],
                         [("dcnow", "solid"), ("dcnet", "solid"), ("purple", "solid"), ("yellow", "blink"), ("red", "blink"), ("bright-pink", "blink")])
        self.assertEqual(by["g1"]["messages"], ["sel-dcnow", "ready-dcnow", "call-dcnow"])
        for g in by.values():
            self.assertIn(g["colour"], ledconfig.TOKEN_IDS + core.PALETTE_IDS)

    def test_every_message_is_detected(self):
        self.assertEqual(sorted(m[0] for m in ledconfig.MESSAGES if not m[4]), [])

    def test_the_effects(self):
        self.assertEqual([e[0] for e in ledconfig.EFFECTS], ["solid", "blink", "fade", "breathe", "blink1", "blink2", "blink3", "rainbow"])


class ConfigTests(Base):
    def test_round_trip(self):
        cfg = ledconfig.led_config()
        cfg["groups"] = [group("a", "bright-pink", ["error", "no-network"], effect="blink", speed="fast", brightness=0.5, leds=[2, 3])]
        ledconfig.save_led_config(cfg)
        got = ledconfig.led_config()["groups"]
        self.assertEqual(got, cfg["groups"])

    def test_bad_values_fall_back(self):
        got = ledconfig.clean_groups([group("a", "chartreuse", ["ready"], effect="disco", speed="warp", brightness="lots", leds=[0, 5])])[0]
        self.assertEqual((got["colour"], got["effect"], got["speed"], got["brightness"], got["leds"]), ("orange", "solid", "slow", None, None))

    def test_a_range_is_put_in_order_and_levels_are_clamped(self):
        got = ledconfig.clean_groups([group("a", "red", [], leds=[5, 2], brightness=4)])[0]
        self.assertEqual((got["leds"], got["brightness"]), ([2, 5], 1.0))

    def test_a_message_can_be_in_one_group_only_and_unknown_ones_are_dropped(self):
        got = ledconfig.clean_groups([group("a", "red", ["ready", "nonsense", "busy"]), group("b", "blue", ["busy", "error"])])
        self.assertEqual([g["messages"] for g in got], [["ready-dcnow", "ready-dcnet", "busy"], ["error"]])      # "ready" of an older file is the two that replaced it

    def test_ids_are_made_unique(self):
        got = ledconfig.clean_groups([group("a", "red", []), group("a", "blue", []), {"colour": "green"}])
        self.assertEqual(len(set(g["id"] for g in got)), 3)

    def test_at_most_24_groups_and_an_empty_list_is_allowed(self):
        self.assertEqual(len(ledconfig.clean_groups([group("g%d" % i, "red", []) for i in range(40)])), ledconfig.MAX_GROUPS)
        self.assertEqual(ledconfig.clean_groups([]), [])
        cfg = ledconfig.clean_led_config({"groups": []})
        self.assertEqual(cfg["groups"], [])                              # the user removed every row: nothing lights

    def test_not_a_list_gives_the_defaults_and_an_older_file_too(self):
        d = ledconfig.default_groups()
        self.assertEqual(ledconfig.clean_led_config({"groups": "x"})["groups"], d)
        old = ledconfig.clean_led_config({"max_brightness": 0.3, "order": "RGB", "messages": {"ready-dcnow": {"color": "#123456"}}})
        self.assertEqual(old["groups"], d)                               # the per-message looks of an older version start from the new defaults
        self.assertEqual((old["max_brightness"], old["order"]), (0.3, "RGB"))   # calibration is kept

    def test_the_calibration_is_clamped_as_before(self):
        cfg = ledconfig.clean_led_config({"white_balance": {"r": 2, "g": -1, "b": 0.5}, "max_brightness": 7, "gamma": 99, "order": "XYZ"})
        self.assertEqual(cfg["white_balance"], {"r": 1.0, "g": 0.0, "b": 0.5})
        self.assertEqual((cfg["max_brightness"], cfg["order"]), (1.0, "GRB"))
        self.assertTrue(0.5 <= cfg["gamma"] <= 4.0)


class ConditionTests(Base):
    def keys(self, **kw):
        return ledconfig.active_keys(ctx(**kw))

    def test_what_dreampi_is_doing(self):
        self.assertLessEqual({"ready-dcnow", "sel-dcnow"}, self.keys(state="ok"))
        self.assertLessEqual({"ready-dcnet", "sel-dcnet"}, self.keys(state="ok", selected="dcnet"))
        self.assertNotIn("ready-dcnet", self.keys(state="ok"))
        self.assertIn("busy", self.keys(state="busy"))
        self.assertIn("notrunning", self.keys(state="off"))
        self.assertIn("unknown", self.keys(state="unknown"))
        self.assertIn("call-dcnow", self.keys(state="call-dcnow"))
        self.assertIn("call-dcnet", self.keys(state="call-dcnet"))
        self.assertIn("call-other", self.keys(state="call"))

    def test_the_selected_network(self):
        self.assertIn("sel-dcnet", self.keys(selected="dcnet"))
        self.assertNotIn("sel-dcnow", self.keys(selected="dcnet"))

    def test_connection_messages(self):
        k = self.keys(net=dict(GOOD, ethernet=True, wifi=True))
        self.assertLessEqual({"internet-ok", "ethernet", "wifi", "modem-ok"}, k)
        self.assertIn("no-network", self.keys(net={"network": False}))
        self.assertNotIn("no-internet", self.keys(net={"network": False, "internet": False}))   # no route is the bigger problem
        self.assertIn("no-internet", self.keys(net={"network": True, "internet": False}))
        self.assertIn("no-ip", self.keys(net={"network": False, "no_ip": True}))
        self.assertIn("wifi-weak", self.keys(net=dict(GOOD, wifi=True, wifi_weak=True)))
        self.assertIn("net-slow", self.keys(net=dict(GOOD, slow=True)))

    def test_dns_failing_is_not_the_same_as_no_internet(self):
        k = self.keys(net={"network": True, "internet": False, "dns_fail": True})
        self.assertIn("dns-fail", k)
        self.assertNotIn("no-internet", k)

    def test_nothing_from_the_web_service_means_no_connection_messages(self):
        k = self.keys(net={})                                            # its state file is missing or stale
        self.assertFalse(k & {"no-network", "no-internet", "internet-ok", "modem-ok", "modem-missing", "ethernet", "wifi", "ok", "error"})

    def test_the_modem(self):
        self.assertIn("modem-ok", self.keys(net=dict(GOOD, modem=True)))
        self.assertIn("modem-missing", self.keys(net=dict(GOOD, modem=False)))
        k = self.keys(net=dict(GOOD, modem=None))
        self.assertFalse(k & {"modem-ok", "modem-missing"})              # the port isn't known yet

    def test_pi_health(self):
        k = self.keys(net=dict(GOOD, undervoltage=True, throttled=True, hot=True, warm=True))
        self.assertLessEqual({"undervoltage", "throttled", "hot", "warm"}, k)
        self.assertEqual(self.keys(net=dict(GOOD, warm=True)) & {"hot", "warm"}, {"warm"})

    def test_wifi_setup_states(self):
        self.assertEqual(self.keys(wifi="scanning") & {"wifisetup-scan", "wifisetup-choose"}, {"wifisetup-scan"})
        self.assertEqual(self.keys(wifi="hosting") & {"wifisetup-scan", "wifisetup-choose"}, {"wifisetup-scan", "wifisetup-choose"})
        self.assertIn("wifisetup-connecting", self.keys(wifi="connecting"))
        self.assertIn("wifisetup-ok", self.keys(wifi="ok"))
        self.assertIn("wifisetup-failed", self.keys(wifi="failed"))

    def test_updates_and_reboot(self):
        self.assertIn("update-addon", self.keys(info={"addon": True}))
        self.assertNotIn("update-addon", self.keys(info={"addon": False}))
        self.assertIn("update-dreampi", self.keys(info={"dreampi": True}))
        self.assertIn("update-running", self.keys(update="running"))
        self.assertIn("update-ok", self.keys(update="ok"))
        self.assertIn("update-failed", self.keys(update="failed"))
        self.assertIn("reboot", self.keys(reboot=True))

    def test_error_is_any_critical_condition(self):
        for flag in ({"network": False}, dict(GOOD, internet=False), dict(GOOD, undervoltage=True), dict(GOOD, hot=True), dict(GOOD, modem=False)):
            self.assertIn("error", self.keys(net=flag), flag)
        self.assertIn("error", self.keys(state="off", net=GOOD))
        self.assertNotIn("error", self.keys(net=GOOD))

    def test_warning_is_any_warning_or_important_information(self):
        for flag in (dict(GOOD, slow=True), dict(GOOD, wifi_weak=True), dict(GOOD, throttled=True), dict(GOOD, warm=True), dict(GOOD, no_ip=True)):
            self.assertIn("warning", self.keys(net=flag), flag)
        self.assertIn("warning", self.keys(net=GOOD, info={"addon": True}))
        self.assertIn("warning", self.keys(net=GOOD, update="failed"))
        self.assertIn("warning", self.keys(net=GOOD, wifi="failed"))
        self.assertIn("warning", self.keys(net=GOOD, dcnet_problem=True))
        self.assertNotIn("warning", self.keys(net=GOOD))

    def test_everything_ok_means_no_error_and_no_warning(self):
        self.assertIn("ok", self.keys(net=GOOD))
        self.assertIn("ok", self.keys(state="call-dcnow", net=GOOD))
        self.assertNotIn("ok", self.keys(net=dict(GOOD, slow=True)))
        self.assertNotIn("ok", self.keys(state="busy", net=GOOD))
        self.assertNotIn("ok", self.keys(net={"network": True, "internet": None}))

    def test_off_is_never_one_of_the_true_messages(self):
        self.assertNotIn("off", self.keys(net=GOOD))


class LookTests(Base):
    def test_idle_with_the_defaults_shows_the_selected_networks_colour(self):
        looks = self.looks(ctx(net=GOOD))
        self.assertEqual([m["messages"] for m in looks], [["sel-dcnow", "ready-dcnow"]])        # both apply and share the look
        self.assertEqual(looks[-1]["color"], core.network_colour("dcnow")["led"])
        open(core.FLAG, "w").close()
        looks = self.looks(ctx(selected="dcnet", net=GOOD))
        self.assertEqual(looks[-1]["color"], core.network_colour("dcnet")["led"])

    def test_the_network_colours_follow_the_switchers_choice(self):
        core.set_module_colour("switcher", "dcnow", "bright-green")
        looks = self.looks(ctx(state="call-dcnow", net=GOOD))
        self.assertEqual(looks[-1]["color"], "#50ff70")
        self.assertEqual(ledconfig.resolve_colour("network", "dcnow"), "#50ff70")
        self.assertEqual(ledconfig.resolve_colour("dcnet"), core.network_colour("dcnet")["led"])

    def test_a_palette_colour_is_its_led_value(self):
        self.assertEqual(ledconfig.resolve_colour("orange"), "#ff8c00")
        self.assertEqual(ledconfig.resolve_colour("blue"), "#0046ff")

    def test_defaults_for_the_states(self):
        self.assertEqual(self.looks(ctx(state="busy"))[-1]["effect"], "blink")
        self.assertEqual(self.looks(ctx(state="busy"))[-1]["color"], core.colour("yellow")["led"])
        m = self.looks(ctx(state="off"))[-1]
        self.assertEqual((m["color"], m["effect"]), ("#ff0000", "blink"))
        self.assertEqual(self.looks(ctx(state="call"))[-1]["color"], core.colour("purple")["led"])
        unknown = self.looks(ctx(state="unknown"))                                                   # unknown is optional: only the selection lights
        self.assertEqual(len(unknown), 1)
        self.assertEqual(unknown[0]["messages"], ["sel-dcnow"])

    def test_messages_in_no_group_never_light(self):
        self.groups(group("g1", "blue", ["ready"]))
        self.assertEqual([m["key"] for m in self.looks(ctx(net={"network": False}))], ["g1"])
        for m in self.looks(ctx(net={"network": False})):
            self.assertNotIn("no-network", m["messages"])

    def test_priority_decides_which_group_is_on_top(self):
        self.groups(group("g1", "red", ["no-network"]), group("g2", "blue", ["ready"]), group("g3", "green", ["warning"]))
        looks = self.looks(ctx(net={"network": False, "wifi_weak": True}))
        self.assertEqual([m["key"] for m in looks], ["g2", "g3", "g1"])                # ready lowest, then the warning, the error on top

    def test_several_active_messages_of_one_group_give_one_look(self):
        self.groups(group("g1", "red", ["error", "no-network", "undervoltage"]))
        looks = self.looks(ctx(net={"network": False, "undervoltage": True}))
        self.assertEqual(len(looks), 1)
        self.assertEqual(sorted(looks[0]["messages"]), ["error", "no-network", "undervoltage"])

    def test_off_gives_its_look_only_when_nothing_else_applies(self):
        self.groups(group("g1", "red", ["notrunning"]), group("g2", "white", ["off"], brightness=0.01))
        self.assertEqual([m["key"] for m in self.looks(ctx(state="off"))], ["g1"])
        looks = self.looks(ctx(state="ok"))
        self.assertEqual([m["key"] for m in looks], ["g2"])
        self.assertEqual(looks[0]["messages"], ["off"])

    def test_nothing_in_any_group_means_dark_leds(self):
        self.groups()
        self.assertEqual(self.looks(ctx(net=GOOD)), [])

    def test_the_level_is_the_groups_or_the_global_one(self):
        cfg = ledconfig.led_config()
        cfg["max_brightness"] = 0.2
        cfg["groups"] = [group("g1", "red", ["ready"]), group("g2", "blue", ["notrunning"], brightness=0.5)]
        ledconfig.save_led_config(cfg)
        self.assertEqual(self.looks(ctx())[-1]["brightness"], 0.2)
        self.assertEqual(self.looks(ctx(state="off"))[-1]["brightness"], 0.5)
        self.assertEqual(ledconfig.led_config()["max_brightness"], 0.2)           # editing groups never touches the global level

    def test_favourites_light_their_messages_only_when_online(self):
        self.groups(group("g1", "red", ["players-game", "players-friend"]))
        self.assertEqual(self.looks(ctx(net=GOOD)), [])
        self.assertIn("players-game", ledconfig.active_keys(ctx(players={"games": ["Outtrigger"], "friends": []})))
        self.assertNotIn("players-friend", ledconfig.active_keys(ctx(players={"games": ["Outtrigger"], "friends": []})))
        self.assertIn("players-friend", ledconfig.active_keys(ctx(players={"games": [], "friends": ["Ana"]})))
        self.assertEqual([l["messages"] for l in self.looks(ctx(net=GOOD, players={"games": [], "friends": ["Ana"]}))], [["players-friend"]])

    def test_the_dot_previews_what_dreampi_is_doing(self):
        with open(core.STATE, "w") as f:
            f.write("call dcnow 123")
        look = ledconfig.dreampi_look()
        self.assertEqual(look["color"], core.network_colour("dcnow")["led"])
        os.remove(core.STATE)
        self.groups(group("g1", "red", ["no-network"]))
        self.assertIsNone(ledconfig.dreampi_look())                               # no group for any DreamPi message: no look

    def test_gather_reads_the_files_the_other_services_write(self):
        core.write_update_info(True, False)
        core.mark_reboot()
        open(core.FLAG, "w").close()
        c = ledconfig.gather()
        self.assertEqual((c["selected"], c["reboot"], c["update_info"].get("addon")), ("dcnet", True, True))
        self.assertEqual(ledconfig.gather(live=False)["update_info"], {})


class TargetingTests(Base):
    def msg(self, key, leds=None, colour="#ff0000", effect="solid", brightness=1.0, speed="slow"):
        return {"key": key, "effect": effect, "speed": speed, "color": colour, "brightness": brightness, "leds": leds}

    def lit(self, frame):
        return [i + 1 for i, px in enumerate(frame) if px != (0, 0, 0)]

    def test_one_led_of_a_strip(self):
        self.assertEqual(self.lit(led.render([self.msg("a", [3, 3])], 0.0, 6)), [3])

    def test_a_range(self):
        self.assertEqual(self.lit(led.render([self.msg("a", [2, 4])], 0.0, 6)), [2, 3, 4])

    def test_all_leds(self):
        self.assertEqual(self.lit(led.render([self.msg("a", None)], 0.0, 4)), [1, 2, 3, 4])

    def test_single_led_setup(self):
        self.assertEqual(self.lit(led.render([self.msg("a", None)], 0.0, 1)), [1])
        self.assertEqual(self.lit(led.render([self.msg("a", [1, 1])], 0.0, 1)), [1])
        self.assertEqual(self.lit(led.render([self.msg("a", [2, 2])], 0.0, 1)), [])   # beyond the strip

    def test_groups_on_different_leds_show_at_the_same_time(self):
        self.groups(group("g1", "green", ["ethernet"], leds=[1, 1]), group("g2", "cyan", ["wifi"], leds=[2, 2]),
                    group("g3", "orange", ["ready"], leds=[3, 3]))
        looks = self.looks(ctx(net=dict(GOOD, ethernet=True, wifi=True)))
        frame = led.render(looks, 0.0, 5)
        self.assertEqual(self.lit(frame), [1, 2, 3])
        self.assertGreater(frame[0][1], frame[0][0])                      # green
        self.assertEqual(frame[4], (0, 0, 0))

    def test_a_group_in_its_dark_blink_half_still_owns_its_leds(self):
        low = self.msg("low", None, "#00ff00")
        top = self.msg("top", [1, 1], "#ff0000", effect="blink")
        clocks = {}
        led.render([low, top], 0.0, 2, clocks)
        self.assertEqual(led.render([low, top], 0.7, 2, clocks), [(0, 0, 0), (0, 255, 0)])


class ReadyFollowsTheNetworkTests(Base):
    def test_each_network_has_its_own_ready_look(self):
        self.groups(group("g1", "green", ["ready-dcnow"]), group("g2", "blue", ["ready-dcnet"]))
        self.assertEqual([m["color"] for m in self.looks(ctx(net=GOOD))], [core.colour("green")["led"]])
        self.assertEqual([m["color"] for m in self.looks(ctx(selected="dcnet", net=GOOD))], [core.colour("blue")["led"]])

    def test_the_selection_decides_which_ready_look_shows_when_the_network_is_switched_later(self):
        self.groups(group("g1", "network", ["ready-dcnow", "ready-dcnet"]))
        self.assertEqual(self.looks(ctx(net=GOOD))[0]["color"], core.network_colour("dcnow")["led"])
        self.assertEqual(self.looks(ctx(selected="dcnet", net=GOOD))[0]["color"], core.network_colour("dcnet")["led"])


class PaletteCalibrationTests(Base):
    def test_a_colour_can_look_different_on_the_led(self):
        self.groups(group("g1", "red", ["ready-dcnow"]))
        self.assertEqual(self.looks(ctx(net=GOOD))[0]["color"], "#ff0000")
        self.assertTrue(core.set_palette_colour("red", led="#e01000"))
        self.assertEqual(self.looks(ctx(net=GOOD))[0]["color"], "#e01000")              # the LED follows
        self.assertEqual(core.colour("red")["ui"], core.colour("red")["ui_default"])    # the page's red is untouched

    def test_a_colour_can_be_changed_on_screen_and_gets_its_lighter_border(self):
        self.assertTrue(core.set_palette_colour("blue", ui="#0000ff"))
        c = core.colour("blue")
        self.assertEqual((c["ui"], c["ui_l"]), ("#0000ff", core.lighter("#0000ff")))
        self.assertIn("--c-blue:#0000ff", core.colours_css())

    def test_the_default_value_is_not_kept_and_a_reset_puts_it_back(self):
        core.set_palette_colour("green", led="#00aa00")
        self.assertIn("green", core.palette_overrides())
        core.set_palette_colour("green", led=core.colour("green")["led_default"])
        self.assertNotIn("green", core.palette_overrides())
        core.set_palette_colour("green", ui="#123456", led="#00aa00")
        core.set_palette_colour("white", led="#ffe0e0")
        core.reset_palette("green")
        self.assertEqual(list(core.palette_overrides()), ["white"])
        core.reset_palette()
        self.assertEqual(core.palette_overrides(), {})

    def test_bad_values_are_refused(self):
        self.assertFalse(core.set_palette_colour("nonsense", led="#ff0000"))
        self.assertFalse(core.set_palette_colour("red", led="red"))
        with open(core.PALETTE_FILE, "w") as f:
            f.write('{"red": {"led": "oops", "ui": "#112233"}, "nonsense": {"led": "#ffffff"}}')
        self.assertEqual(core.palette_overrides(), {"red": {"ui": "#112233"}})

    def test_the_colour_test_holds_a_colour_for_a_few_seconds(self):
        self.assertFalse(ledconfig.wb_test_active())
        ledconfig.touch_wb_test("#336699")
        self.assertTrue(ledconfig.wb_test_active())
        self.assertEqual(ledconfig.wb_test_colour(), "#336699")
        ledconfig.touch_wb_test("not a colour")
        self.assertEqual(ledconfig.wb_test_colour(), "#ffffff")                          # the white balance test
        ledconfig.clear_wb_test()
        self.assertFalse(ledconfig.wb_test_active())


class PriorityOrderTests(Base):
    def test_the_default_order_is_the_catalogue_order_without_off(self):
        self.assertEqual(ledconfig.clean_priority(None), ledconfig.PRIORITY_ORDER)
        self.assertEqual(ledconfig.led_config()["priority"], ledconfig.PRIORITY_ORDER)
        self.assertNotIn("off", ledconfig.PRIORITY_ORDER)

    def test_a_saved_order_is_kept_and_made_safe(self):
        order = list(reversed(ledconfig.PRIORITY_ORDER))
        self.assertEqual(ledconfig.clean_priority(order), order)
        got = ledconfig.clean_priority(["wifi", "nonsense", "wifi", 5, "error"])
        self.assertLess(got.index("wifi"), got.index("error"))                         # their order is kept, unknown and repeated entries are dropped
        self.assertEqual(sorted(got), sorted(ledconfig.PRIORITY_ORDER))                # and everything that is missing is back

    def test_a_missing_message_goes_back_after_the_one_it_follows_by_default(self):
        order = [k for k in ledconfig.PRIORITY_ORDER if k != "event-soon"]
        order.reverse()
        got = ledconfig.clean_priority(order)
        default = ledconfig.PRIORITY_ORDER
        prev = default[default.index("event-soon") - 1]
        self.assertEqual(got[got.index(prev) + 1], "event-soon")

    def test_the_order_decides_which_group_is_on_top(self):
        self.groups(group("g1", "red", ["no-network"]), group("g2", "blue", ["ready-dcnow"]))
        looks = self.looks(ctx(net={"network": False}))
        self.assertEqual([m["key"] for m in looks], ["g2", "g1"])                      # by default the problem is on top
        cfg = ledconfig.led_config()
        cfg["priority"] = ["ready-dcnow"] + [k for k in cfg["priority"] if k != "ready-dcnow"]
        ledconfig.save_led_config(cfg)
        looks = self.looks(ctx(net={"network": False}))
        self.assertEqual([m["key"] for m in looks], ["g1", "g2"])                      # and now being ready is

    def test_the_order_comes_back_from_the_endpoint_and_is_saved_through_it(self):
        import json as _json
        cfg = ledconfig.led_config()
        cfg["priority"] = cfg["priority"][1:] + cfg["priority"][:1]
        got = ledconfig.save_led_config(cfg)
        self.assertEqual(got["priority"][-1], ledconfig.PRIORITY_ORDER[0])
        with open(core.LED_CONFIG) as f:
            self.assertEqual(_json.load(f)["priority"], got["priority"])


class WebTests(Base):
    def setUp(self):
        Base.setUp(self)
        import threading
        from support import web
        self.srv = web.Server(("127.0.0.1", 0), web.Handler)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.base = "http://127.0.0.1:%d" % self.srv.server_address[1]

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()
        Base.tearDown(self)

    def get(self):
        from urllib.request import urlopen
        return json.loads(urlopen(self.base + "/ledconfig", timeout=10).read().decode())

    def post(self, cfg):
        from urllib.request import Request, urlopen
        req = Request(self.base + "/ledconfig", data=json.dumps(cfg).encode(), method="POST", headers={"X-Requested-With": "x", "Content-Type": "application/json"})
        return json.loads(urlopen(req, timeout=10).read().decode())

    def test_the_endpoint_has_everything_the_page_needs(self):
        r = self.get()
        self.assertEqual([e[0] for e in r["effects"]], [e[0] for e in ledconfig.EFFECTS])
        self.assertEqual([m["key"] for m in r["messages"]], KEYS)
        self.assertEqual([c[0] for c in r["categories"]], [c[0] for c in ledconfig.CATEGORIES])
        self.assertEqual(len(r["colours"]["palette"]), 16)
        self.assertEqual([t["id"] for t in r["colours"]["tokens"]], ["dcnow", "dcnet"])
        self.assertEqual(r["token_ui"]["dcnow"], {"ui": core.network_colour("dcnow")["ui"], "ui_l": core.network_colour("dcnow")["ui_l"]})
        self.assertEqual(r["config"]["groups"], r["defaults"]["groups"])
        self.assertEqual(r["defaults"]["priority"], ledconfig.PRIORITY_ORDER)
        self.assertEqual(r["config"]["priority"], ledconfig.PRIORITY_ORDER)
        self.assertTrue(all(set(m) == {"key", "label", "category", "description", "detected"} for m in r["messages"]))

    def test_saving_groups_round_trips(self):
        cfg = self.get()["config"]
        cfg["groups"].append(group("mine", "bright-cyan", ["error", "ready"], effect="blink", speed="fast", leds=[1, 1]))
        out = self.post(cfg)
        mine = [g for g in out["config"]["groups"] if g["id"] == "mine"][0]
        self.assertEqual((mine["colour"], mine["messages"], mine["leds"]), ("bright-cyan", ["error"], [1, 1]))    # "ready" is in another group already
        self.assertEqual(ledconfig.led_config()["groups"][-1]["id"], "mine")


if __name__ == "__main__":
    unittest.main()
