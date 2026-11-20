"""0.11.0: stronger-model confirmation, extra frames, head position, crop, rule checks, push buttons, caching."""
import os
import sys
import unittest
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "prusa_watch", "app"))

from prusa_watch import camera, config, notify, printers, vision  # noqa: E402
from prusa_watch.prusalink import PrinterStatus, parse_status  # noqa: E402
from prusa_watch.vision import Verdict  # noqa: E402
from prusa_watch.watchdog import Watchdog  # noqa: E402
from test_agent import agent_mod, make_agent  # noqa: E402

agent_mod.EXTRA_FRAME_DELAY_S = 0
WARN = Verdict("warning", "other", 0.4, "no parts visible", part_visible="hidden")
FAIL = Verdict("failure", "detached_part", 0.9, "part moved", part_visible="partly")
OK = Verdict("ok", "none", 0.8, "all fine", part_visible="partly")


def escalating_agent(**over):
    a = make_agent(confirm_with_stronger_model=True, **over)
    a.confirm_judge = mock.Mock(model_id="claude-sonnet-5-5", last_usage={"cost_usd": 0.01})
    return a


@mock.patch.object(agent_mod.camera, "thumbnail", return_value=b"\x10" * 64)
@mock.patch.object(agent_mod.camera, "grab_jpeg", return_value=b"JPEG")
class EscalationTest(unittest.TestCase):
    def test_warning_cleared_by_stronger_model(self, _g, _t):
        a = escalating_agent()
        a.printer.status.return_value = PrinterStatus("PRINTING", job_id=3, axis_z=2.0, progress=10)
        a.judge.assess.return_value = WARN
        a.confirm_judge.assess.return_value = OK
        a.tick()
        v = a.last_verdict
        self.assertEqual((v.status, v.checked_by), ("ok", "claude-sonnet-5-5"))
        self.assertIn("cleared by claude-sonnet-5-5", v.downgraded)
        self.assertEqual(a.watchdog.warn_streak, 0)

    def test_failure_confirmed_by_stronger_model_alerts(self, _g, _t):
        a = escalating_agent()
        a.watchdog.failure_threshold = 1
        a.printer.status.return_value = PrinterStatus("PRINTING", job_id=3, axis_z=2.0, progress=10)
        a.judge.assess.return_value = FAIL
        a.confirm_judge.assess.return_value = FAIL
        a.tick()
        self.assertEqual((a.last_verdict.status, a.last_verdict.checked_by), ("failure", "claude-sonnet-5-5"))
        a.notifier.send.assert_called_once()
        self.assertIn("checked by claude-sonnet-5-5", a.notifier.send.call_args.args[1])

    def test_ok_is_not_escalated(self, _g, _t):
        a = escalating_agent()
        a.printer.status.return_value = PrinterStatus("PRINTING", job_id=3, axis_z=2.0, progress=10)
        a.judge.assess.return_value = OK
        a.tick()
        a.confirm_judge.assess.assert_not_called()

    def test_printer_model_reaches_both_judges(self, _g, _t):
        a = escalating_agent()
        a.printer_model = None
        a._set_printer("core_one_l", "test")
        self.assertEqual(a.confirm_judge.system_prompt, a.judge.system_prompt)
        self.assertIn("CORE One L", a.confirm_judge.system_prompt)

    def test_extra_frames_and_head_position(self, grab, _t):
        a = make_agent(frames_per_check=3, printer_model="core_one_l")
        a.printer.status.return_value = PrinterStatus("PRINTING", job_id=3, axis_z=2.0, progress=10,
                                                      axis_x=262, axis_y=-5)
        a.judge.assess.return_value = OK
        a.tick()
        call = a.judge.assess.call_args
        self.assertEqual(len(call.kwargs["extra"]), 2)
        self.assertIn("parked outside the print area", call.args[2])


@mock.patch.object(agent_mod.camera, "thumbnail", return_value=b"\x10" * 64)
@mock.patch.object(agent_mod.camera, "grab_jpeg", return_value=b"JPEG")
class RuleTest(unittest.TestCase):
    def test_progress_stall_alerts_once(self, _g, _t):
        a = make_agent(stall_minutes=10)
        a.judge.assess.return_value = OK
        a.printer.status.return_value = PrinterStatus("PRINTING", job_id=4, axis_z=3.0, progress=40)
        with mock.patch.object(agent_mod.time, "time") as clock:
            for minute in (0, 5, 11, 20):
                clock.return_value = 1000.0 + minute * 60
                a.tick()
        subjects = [c.args[0] for c in a.notifier.send.call_args_list]
        self.assertEqual(subjects.count("[Prusa Watch] Print progress stalled"), 1)

    def test_hotend_fan_stopped(self, _g, _t):
        a = make_agent()
        a.judge.assess.return_value = OK
        st = PrinterStatus("PRINTING", job_id=4, axis_z=3.0, progress=40, temp_nozzle=215, fan_hotend=0)
        a.printer.status.return_value = st
        a.tick()
        self.assertFalse(a.notifier.send.called)
        a.tick()
        a.tick()
        subjects = [c.args[0] for c in a.notifier.send.call_args_list]
        self.assertEqual(subjects, ["[Prusa Watch] Hotend fan stopped"])

    def test_rules_off(self, _g, _t):
        a = make_agent(rule_checks=False)
        a.judge.assess.return_value = OK
        a.printer.status.return_value = PrinterStatus("PRINTING", job_id=4, axis_z=3.0, temp_nozzle=215, fan_hotend=0)
        for _ in range(3):
            a.tick()
        self.assertFalse(a.notifier.send.called)


class PushActionTest(unittest.TestCase):
    def test_actions_in_push_payload(self):
        with mock.patch.dict(os.environ, {"SUPERVISOR_TOKEN": "tok"}), \
                mock.patch.object(notify.requests, "post") as post:
            post.return_value.raise_for_status = mock.Mock()
            notify.HANotifier("mobile_app_x").send("s", "b", actions=[("PRUSA_WATCH_CORRECT", "Richtig erkannt")])
        self.assertEqual(post.call_args.kwargs["json"]["data"]["actions"],
                         [{"action": "PRUSA_WATCH_CORRECT", "title": "Richtig erkannt"}])

    def test_agent_titles_and_switch(self):
        a = make_agent(notify_language="de")
        a.dataset = mock.Mock()
        self.assertEqual(a._push_actions("PRUSA_WATCH_FALSE_ALARM"), [("PRUSA_WATCH_FALSE_ALARM", "Fehlalarm")])
        a.cfg.push_actions = False
        self.assertIsNone(a._push_actions("PRUSA_WATCH_FALSE_ALARM"))


class SmallPartsTest(unittest.TestCase):
    def test_head_text(self):
        m = printers.MODELS["core_one_l"]
        self.assertEqual(printers.head_text(m, None, 5), "")
        self.assertIn("back-left", printers.head_text(m, 20, 280))
        self.assertIn("parked outside", printers.head_text(m, 262, -5))

    def test_parse_status_has_head(self):
        st = parse_status({"printer": {"state": "PRINTING", "axis_x": 12.5, "axis_y": 40}})
        self.assertEqual((st.axis_x, st.axis_y), (12.5, 40))

    def test_crop(self):
        self.assertIsNone(camera.parse_crop(""))
        self.assertEqual(camera.parse_crop("0.1, 0, 0.85, 1"), (0.1, 0.0, 0.85, 1.0))
        for bad in ("0.1,0.2", "0.5,0,0.8,1", "-1,0,1,1"):
            with self.assertRaises(ValueError):
                camera.parse_crop(bad)
        with mock.patch.object(camera, "_ffmpeg", return_value=b"J") as ff:
            camera.grab_jpeg("rtsp://x/live", width=1280, crop=(0.1, 0, 0.85, 1))
        vf = ff.call_args.args[0][ff.call_args.args[0].index("-vf") + 1]
        self.assertTrue(vf.startswith("crop=iw*0.85:ih*1:iw*0.1:ih*0,scale='min(1280,iw)'"))

    def test_config_validation(self):
        base = {"printer_host": "10.0.0.5", "camera_url": "rtsp://10.0.0.6/live", "anthropic_api_key": "k"}
        for bad in ({"frames_per_check": 4}, {"camera_crop": "1,2"},
                    {"confirm_with_stronger_model": True, "confirm_model": " "}):
            with self.assertRaises(ValueError):
                config.Config(**base, **bad).validate()
        cfg = config.Config(**base, auto_action_issues=" spaghetti, detached_part ")
        self.assertEqual(cfg.action_issues, {"spaghetti", "detached_part"})

    def test_watchdog_action_only_for_listed_issues(self):
        w = Watchdog(1, 0.6, 0, auto_action="pause", auto_action_threshold=2, action_issues={"spaghetti"})
        layer = Verdict("failure", "layer_shift", 0.9, "x")
        self.assertIsNone(w.observe(layer, 0).action)
        self.assertIsNone(w.observe(layer, 1).action)
        self.assertEqual(w.observe(Verdict("failure", "spaghetti", 0.9, "x"), 2).action, "pause")


def fake_response(blocks, stop="tool_use", cache_write=0, cache_read=0):
    usage = SimpleNamespace(input_tokens=1000, output_tokens=100, cache_creation_input_tokens=cache_write,
                            cache_read_input_tokens=cache_read)
    return SimpleNamespace(content=blocks, stop_reason=stop, usage=usage)


TOOL_BLOCK = SimpleNamespace(type="tool_use", name="report_assessment",
                             input={"part_visible": "partly", "evidence": "e", "status": "ok", "issue": "none",
                                    "confidence": 0.8, "description": "fine"})


class VisionJudgeTest(unittest.TestCase):
    def judge(self, model, **kw):
        j = vision.VisionJudge(model, api_key="test", **kw)
        j.client = mock.Mock()
        return j

    def test_haiku_forced_tool_and_cache_breakpoints(self):
        j = self.judge("claude-haiku-5-5", caching=True)
        j.client.messages.create.return_value = fake_response([TOOL_BLOCK], cache_read=3000)
        v = j.assess(b"C", b"R", "ctx", expected=b"E", layout=b"L", extra=[b"C2"])
        kw = j.client.messages.create.call_args.kwargs
        self.assertEqual(kw["tool_choice"], {"type": "tool", "name": "report_assessment"})
        self.assertEqual(kw["system"][0]["cache_control"], {"type": "ephemeral"})
        content = kw["messages"][0]["content"]
        cached = [i for i, b in enumerate(content) if "cache_control" in b]
        self.assertEqual(len(cached), 1)
        self.assertEqual(content[cached[0]]["type"], "image")             # the LAYOUT image
        self.assertIn("CURRENT frame 2 of 2", [b.get("text", "") for b in content][-3])
        self.assertEqual(v.status, "ok")
        self.assertAlmostEqual(j.last_usage["cost_usd"], (1000 * 0.10 + 3000 * 0.01 + 100 * 0.50) / 1e6)

    def test_sonnet_auto_strict_fallbacks_and_retry(self):
        j = self.judge("claude-sonnet-5-5", effort="medium")
        text_only = fake_response([SimpleNamespace(type="text", text="I think it is fine.")], stop="end_turn")
        j.client.beta.messages.create.side_effect = [text_only, fake_response([TOOL_BLOCK])]
        v = j.assess(b"C", None, "ctx")
        self.assertEqual(j.client.beta.messages.create.call_count, 2)          # retried without a tool call
        kw = j.client.beta.messages.create.call_args.kwargs
        self.assertEqual(kw["tool_choice"], {"type": "auto"})
        self.assertTrue(kw["tools"][0]["strict"])
        self.assertEqual((kw["fallbacks"], kw["betas"]), ("default", [vision.FALLBACK_BETA]))
        self.assertEqual(kw["output_config"], {"effort": "medium"})
        self.assertEqual(v.status, "ok")
        self.assertEqual(j.last_usage["input_tokens"], 2000)


if __name__ == "__main__":
    unittest.main()
