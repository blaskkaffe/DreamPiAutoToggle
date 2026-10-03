"""Independent LED messages: defaults, priority, fallback, targeting, the global network colours, migration."""
import colorsys
import json
import os
import unittest

from support import ledconfig, core, sandbox, cleanup
import netswitch_led as led

KEYS = [s[0] for s in ledconfig.LED_STATES]


def keys(msgs):
    return [m["key"] for m in msgs]


def hue_after_gamma(colour, gamma=ledconfig.GAMMA):
    """The hue (degrees) the LED really shows: gamma is applied to every channel before output."""
    r, g, b = [(int(colour[i:i + 2], 16) / 255.0) ** gamma for i in (1, 3, 5)]
    return colorsys.rgb_to_hsv(r, g, b)[0] * 360


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = sandbox()

    def tearDown(self):
        cleanup(self.tmp)

    def configure(self, **changes):
        cfg = ledconfig.led_config()
        for key, fields in changes.items():
            cfg["messages"][key.replace("_", "-")].update(fields)
        ledconfig.save_led_config(cfg)
        return cfg

    def set_dcnet(self, on):
        if on:
            open(core.FLAG, "w").close()
        elif os.path.exists(core.FLAG):
            os.remove(core.FLAG)


class MessageListTests(Base):
    def test_every_message_is_in_a_group_and_has_a_priority(self):
        groups = set(g[0] for g in ledconfig.GROUPS)
        for s in ledconfig.LED_STATES:
            self.assertIn(s[2], groups, s[0])
            self.assertIn(s[0], ledconfig.PRIORITY, s[0])
        self.assertEqual(sorted(ledconfig.PRIORITY_ORDER), sorted(KEYS))

    def test_groups_hold_the_requested_messages(self):
        by = dict((g[0], [s[0] for s in ledconfig.LED_STATES if s[2] == g[0]]) for g in ledconfig.GROUPS)
        self.assertEqual(by["system"], ["busy", "off", "pi", "unknown"])
        self.assertEqual(by["network"], ["no-network", "no-internet", "ethernet", "wifi", "net-switch"])
        for net in ("dcnow", "dcnet", "netlink"):
            self.assertEqual(by["call-" + net], ["ready-" + net, "connecting-" + net, "call-" + net, "failed-" + net])

    def test_default_enabled_set(self):
        cfg = ledconfig.default_led_config()["messages"]
        on = set(k for k, m in cfg.items() if m["enabled"])
        want = {"busy", "off", "pi", "unknown", "no-network", "no-internet", "wifi-setup", "wifi-ok", "wifi-failed"}
        for net in ("dcnow", "dcnet"):
            want |= {"ready-" + net, "connecting-" + net, "call-" + net, "failed-" + net}
        self.assertEqual(on, want)
        for k in ("ethernet", "wifi", "net-switch", "ready-netlink", "connecting-netlink", "call-netlink", "failed-netlink"):
            self.assertFalse(cfg[k]["enabled"], k)

    def test_default_looks(self):
        m = ledconfig.default_led_config()["messages"]
        look = lambda k: (m[k]["color"], m[k]["effect"], m[k]["speed"])
        R, A, P = ledconfig.RED, ledconfig.AMBER, ledconfig.PURPLE
        self.assertEqual(look("busy"), (A, "blink", "slow"))
        self.assertEqual(look("off"), (R, "blink", "slow"))
        self.assertEqual(look("pi"), (R, "blink", "fast"))
        self.assertEqual(look("unknown")[1:], ("solid", "slow"))
        self.assertEqual(look("no-network"), (R, "solid", "slow"))
        self.assertEqual(look("no-internet"), (A, "blink", "slow"))
        self.assertEqual(look("ethernet")[1:], ("solid", "slow"))
        self.assertEqual(look("wifi")[1:], ("solid", "slow"))
        for net, c in (("dcnow", "dcnow"), ("dcnet", "dcnet"), ("netlink", P)):      # the networks' colours are tokens: global
            self.assertEqual(look("ready-" + net), (c, "solid", "slow"))
            self.assertEqual(look("connecting-" + net), (c, "blink", "slow"))
            self.assertEqual(look("call-" + net), (c, "solid", "slow"))
            self.assertEqual(look("failed-" + net), (R, "blink", "fast"))

    def test_only_solid_and_blink_exist(self):
        self.assertEqual([e[0] for e in ledconfig.EFFECTS], ["solid", "blink"])
        for st, m in ledconfig.default_led_config()["messages"].items():
            self.assertIn(m["effect"], ("solid", "blink"), st)

    def test_errors_are_red_and_not_mistakable_for_network_colours(self):
        m = ledconfig.default_led_config()["messages"]
        errors = ["off", "pi", "no-network"] + ["failed-" + n for n in ("dcnow", "dcnet", "netlink")]
        for k in errors:
            self.assertEqual(m[k]["color"], ledconfig.RED, k)
        for k in errors:
            self.assertNotIn(m[k]["color"], ("dcnow", "dcnet", ledconfig.PURPLE), k)
        red = hue_after_gamma(ledconfig.RED)
        self.assertGreater(abs(hue_after_gamma(ledconfig.PURPLE) - red), 60)

    def test_identical_defaults_are_fine_and_each_message_is_independent(self):
        cfg = self.configure(call_dcnow={"color": "#123456", "leds": [3, 3]}, no_internet={"color": "#123456"})
        got = ledconfig.led_config()["messages"]
        self.assertEqual(got["call-dcnow"]["color"], "dcnow")             # a network message's colour is the network's, not its own
        self.assertEqual(got["call-dcnow"]["leds"], [3, 3])
        self.assertEqual(got["no-internet"]["color"], "#123456")          # any other message can have its own colour
        self.assertEqual(got["call-dcnet"]["color"], "dcnet")      # untouched
        self.assertIsNone(got["call-dcnet"]["leds"])


class RuntimeTests(Base):
    def test_state_maps_to_messages(self):
        net = {"network": True}
        self.assertEqual(keys(ledconfig.active_messages("ok", net, wifi=False)), ["ready-dcnow"])
        self.set_dcnet(True)
        self.assertEqual(keys(ledconfig.active_messages("ok", net, wifi=False)), ["ready-dcnet"])
        self.assertEqual(keys(ledconfig.active_messages("call-dcnet", net, wifi=False)), ["call-dcnet"])
        self.set_dcnet(False)
        self.assertEqual(keys(ledconfig.active_messages("call-dcnow", net, wifi=False)), ["call-dcnow"])
        self.configure(call_netlink={"enabled": True})
        self.assertEqual(keys(ledconfig.active_messages("call", net, wifi=False)), ["call-netlink"])
        self.assertEqual(keys(ledconfig.active_messages("busy", net, wifi=False)), ["busy"])
        self.assertEqual(keys(ledconfig.active_messages("off", net, wifi=False)), ["off"])

    def test_priority_errors_over_information_and_wifi_setup_over_all(self):
        self.configure(ethernet={"enabled": True}, wifi={"enabled": True})
        net = {"network": False, "internet": False, "pi_problem": True, "ethernet": True, "wifi": True}
        got = keys(ledconfig.active_messages("ok", net, wifi=False))
        self.assertEqual(got, ["wifi", "ethernet", "ready-dcnow", "pi", "no-network"])   # drawn lowest first
        saved, core.wifi_state = core.wifi_state, lambda: {"state": "hosting"}
        try:
            self.assertEqual(keys(ledconfig.active_messages("ok", net))[-1], "wifi-setup")
        finally:
            core.wifi_state = saved

    def test_disabled_messages_make_no_output(self):
        self.configure(ready_dcnow={"enabled": False}, unknown={"enabled": False})
        self.assertEqual(ledconfig.active_messages("ok", {"network": True}, wifi=False), [])
        self.assertEqual(ledconfig.active_messages("unknown", {"network": True}, wifi=False), [])
        frame = led.render([], 0.0, 3)
        self.assertEqual(frame, [(0, 0, 0)] * 3)

    def test_state_unknown_is_only_a_fallback(self):
        net_ok = {"network": True}
        self.assertEqual(keys(ledconfig.active_messages("unknown", net_ok, wifi=False)), ["unknown"])
        # any other applicable message hides it - an error ...
        self.assertEqual(keys(ledconfig.active_messages("unknown", {"network": False}, wifi=False)), ["no-network"])
        # ... or information
        self.configure(ethernet={"enabled": True})
        self.assertEqual(keys(ledconfig.active_messages("unknown", {"network": True, "ethernet": True}, wifi=False)), ["ethernet"])
        # a disabled one does not
        self.configure(ethernet={"enabled": False})
        self.assertEqual(keys(ledconfig.active_messages("unknown", {"network": True, "ethernet": True}, wifi=False)), ["unknown"])
        # lowest priority of all
        self.assertEqual(ledconfig.PRIORITY_ORDER[-1], "unknown")
        self.assertEqual(min(ledconfig.PRIORITY, key=ledconfig.PRIORITY.get), "unknown")

    def test_unknown_never_overrides_startup_call_or_error(self):
        for state in ("busy", "call-dcnow", "call-dcnet", "off"):
            got = keys(ledconfig.active_messages(state, {"network": True}, wifi=False))
            self.assertNotIn("unknown", got, state)
            self.assertEqual(len(got), 1, state)

    def test_only_detectable_messages_ever_show(self):
        """Connecting, Call failed, Ready - Netlink and Network switching aren't detected, so they never light."""
        undetected = set(s[0] for s in ledconfig.LED_STATES if not s[7])
        self.assertEqual(undetected, {"net-switch"} | set(p + n for p in ("connecting-", "failed-") for n in ("dcnow", "dcnet", "netlink")) | {"ready-netlink"})
        every = set()
        for dcnet in (False, True):
            self.set_dcnet(dcnet)
            for state in ("off", "busy", "ok", "call-dcnow", "call-dcnet", "call", "unknown"):
                for net in (None, {"network": True}, {"network": False}, {"network": True, "internet": False},
                            {"network": True, "pi_problem": True, "ethernet": True, "wifi": True}):
                    for k in ledconfig.led_config()["messages"]:
                        cfg = ledconfig.led_config()
                        cfg["messages"][k]["enabled"] = True
                        ledconfig.save_led_config(cfg)
                    every |= set(keys(ledconfig.active_messages(state, net, wifi=False)))
        self.assertFalse(every & undetected, every & undetected)

    def test_dcnow_and_dcnet_can_differ_completely(self):
        self.configure(ready_dcnow={"effect": "blink", "leds": [1, 1]},
                       ready_dcnet={"effect": "solid", "leds": [4, 4], "speed": "fast"})
        a = ledconfig.active_messages("ok", {"network": True}, wifi=False)[0]
        self.set_dcnet(True)
        b = ledconfig.active_messages("ok", {"network": True}, wifi=False)[0]
        self.assertEqual((a["key"], a["color"], a["effect"], a["leds"]), ("ready-dcnow", "#ff8c00", "blink", [1, 1]))      # orange
        self.assertEqual((b["key"], b["color"], b["effect"], b["leds"], b["speed"]), ("ready-dcnet", "#0046ff", "solid", [4, 4], "fast"))   # blue

    def test_global_brightness_is_separate(self):
        cfg = self.configure(ready_dcnow={"brightness": 0.5})
        self.assertNotIn("max_brightness", cfg["messages"]["ready-dcnow"])
        ledconfig.save_led_config(dict(ledconfig.led_config(), max_brightness=0.2))
        m = ledconfig.active_messages("ok", {"network": True}, wifi=False)[0]
        self.assertEqual(m["brightness"], 0.5)                           # its own level wins
        self.configure(ready_dcnow={"brightness": None})
        m = ledconfig.active_messages("ok", {"network": True}, wifi=False)[0]
        self.assertEqual(m["brightness"], 0.2)                           # no own level: the global one
        self.assertEqual(ledconfig.led_config()["max_brightness"], 0.2)  # editing messages never touches it


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

    def test_several_messages_on_different_leds_at_the_same_time(self):
        frame = led.render([self.msg("eth", [1, 1], "#00ff00"), self.msg("wifi", [2, 2], "#00c8ff"),
                            self.msg("dcnow", [3, 3], "#ff8c00"), self.msg("dcnet", [4, 4], "#0046ff")], 0.0, 5)
        self.assertEqual(self.lit(frame), [1, 2, 3, 4])
        self.assertGreater(frame[0][1], frame[0][0])                      # green
        self.assertGreater(frame[3][2], frame[3][0])                      # blue
        self.assertEqual(frame[4], (0, 0, 0))

    def test_active_messages_carry_their_leds_to_render(self):
        self.configure(ethernet={"enabled": True, "leds": [1, 1]}, wifi={"enabled": True, "leds": [2, 2]},
                       ready_dcnow={"leds": [3, 3]})
        msgs = ledconfig.active_messages("ok", {"network": True, "ethernet": True, "wifi": True}, wifi=False)
        self.assertEqual(self.lit(led.render(msgs, 0.0, 5)), [1, 2, 3])
        by = dict((m["key"], m["leds"]) for m in msgs)
        self.assertEqual(by, {"ready-dcnow": [3, 3], "ethernet": [1, 1], "wifi": [2, 2]})

    def test_bad_ranges_are_dropped(self):
        got = ledconfig.clean_led_config({"messages": {"wifi": {"leds": [0, 5]}, "ethernet": {"leds": [3]},
                                                       "busy": {"leds": [5, 2]}, "off": {"leds": "all"}}})["messages"]
        self.assertIsNone(got["wifi"]["leds"])
        self.assertIsNone(got["ethernet"]["leds"])
        self.assertEqual(got["busy"]["leds"], [2, 5])
        self.assertIsNone(got["off"]["leds"])


class MigrationTests(Base):
    def write_legacy(self, colours):
        with open(core.LED_CONFIG, "w") as f:
            json.dump({"max_brightness": 0.25, "order": "RGB", "colours": colours}, f)

    def test_untouched_old_entries_get_the_new_defaults(self):
        old = dict((net, {"ok": {"color": "#00ff00", "effect": "solid", "speed": "slow", "enabled": True},
                          "no-internet": {"color": "#ff7a00", "effect": "blink", "speed": "slow", "enabled": True}})
                   for net in ("dcnow", "dcnet"))
        self.write_legacy(old)
        cfg = ledconfig.led_config()
        self.assertEqual(cfg["max_brightness"], 0.25)
        self.assertEqual(cfg["order"], "RGB")
        self.assertEqual(cfg["messages"]["ready-dcnow"]["color"], "dcnow")
        self.assertEqual(cfg["messages"]["ready-dcnet"]["color"], "dcnet")
        self.assertEqual(cfg["messages"]["no-internet"]["color"], ledconfig.AMBER)

    def test_customised_old_entries_are_kept(self):
        self.write_legacy({"dcnow": {"ok": {"color": "#112233", "effect": "blink", "speed": "fast", "enabled": False,
                                            "leds": [2, 3], "brightness": 0.4},
                                     "ethernet": {"color": "#ffffff", "effect": "solid", "speed": "slow", "enabled": True}},
                           "dcnet": {"ok": {"color": "#445566", "effect": "solid", "speed": "slow", "enabled": True},
                                     "call-dcnet": {"color": "#0046ff", "effect": "breathe", "speed": "slow", "enabled": True},
                                     "call": {"color": "#aa00ff", "effect": "solid", "speed": "slow", "enabled": False}}})
        m = ledconfig.led_config()["messages"]
        self.assertEqual((m["ready-dcnow"]["color"], m["ready-dcnow"]["effect"], m["ready-dcnow"]["enabled"],
                          m["ready-dcnow"]["leds"], m["ready-dcnow"]["brightness"]), ("dcnow", "blink", False, [2, 3], 0.4))   # the colour is the network's now
        self.assertEqual(m["ready-dcnet"]["color"], "dcnet")
        self.assertEqual(m["call-dcnet"]["effect"], "solid")                   # "breathe" no longer exists: the message's default
        self.assertFalse(m["call-netlink"]["enabled"])                         # old "call" = Netlink
        self.assertTrue(m["ethernet"]["enabled"])                              # switched on by the user
        self.assertEqual(m["ethernet"]["color"], "#ffffff")

    def test_saving_writes_only_messages(self):
        self.write_legacy({"dcnow": {"no-internet": {"color": "#112233"}}})
        ledconfig.save_led_config(ledconfig.led_config())
        with open(core.LED_CONFIG) as f:
            saved = json.load(f)
        self.assertNotIn("colours", saved)
        self.assertEqual(saved["messages"]["no-internet"]["color"], "#112233")
        self.assertEqual(ledconfig.led_config()["messages"]["no-internet"]["color"], "#112233")

    def test_old_blink_flag_and_garbage_do_not_break(self):
        self.write_legacy({"dcnow": {"off": {"color": "#ff0000", "blink": False}, "pi": "nonsense"}, "dcnet": 5})
        m = ledconfig.led_config()["messages"]
        self.assertEqual(m["off"]["effect"], "solid")
        self.assertEqual(m["pi"]["effect"], "blink")                           # default


class WebTests(Base):
    def test_ledconfig_endpoint_lists_groups_and_effects(self):
        import threading
        from urllib.request import Request, urlopen
        from support import web
        srv = web.Server(("127.0.0.1", 0), web.Handler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        base = "http://127.0.0.1:%d" % srv.server_address[1]
        try:
            r = json.loads(urlopen(base + "/ledconfig", timeout=10).read().decode())
            self.assertEqual([g[0] for g in r["groups"]], [g[0] for g in ledconfig.GROUPS])
            self.assertEqual([e[0] for e in r["effects"]], ["solid", "blink"])
            self.assertEqual(r["net_led"], {"dcnow": "#ff8c00", "dcnet": "#0046ff"})
            self.assertEqual(set(r["net_bound"]), {"ready-dcnow", "connecting-dcnow", "call-dcnow", "ready-dcnet", "connecting-dcnet", "call-dcnet"})
            self.assertEqual(len(r["states"]), len(ledconfig.LED_STATES))
            self.assertEqual(set(r["config"]["messages"]), set(KEYS))
            cfg = r["config"]
            cfg["messages"]["ethernet"].update(enabled=True, effect="blink", leds=[1, 1])
            req = Request(base + "/ledconfig", data=json.dumps(cfg).encode(), method="POST",
                          headers={"X-Requested-With": "x", "Content-Type": "application/json"})
            out = json.loads(urlopen(req, timeout=10).read().decode())
            self.assertEqual(out["config"]["messages"]["ethernet"]["leds"], [1, 1])
            self.assertEqual(ledconfig.led_config()["messages"]["ethernet"]["effect"], "blink")
        finally:
            srv.shutdown()
            srv.server_close()


if __name__ == "__main__":
    unittest.main()
