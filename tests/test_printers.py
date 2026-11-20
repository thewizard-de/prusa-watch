"""0.10.0: printer model selection, layout guard, alert pictures in pushes, snapshot pruning."""
import os
import sys
import tempfile
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "prusa_watch", "app"))

from prusa_watch import config, notify, printers, vision  # noqa: E402
from test_agent import agent_mod, make_agent  # noqa: E402
from prusa_watch.prusalink import PrinterStatus  # noqa: E402
from prusa_watch.vision import Verdict  # noqa: E402


class DetectTest(unittest.TestCase):
    def test_hostnames_and_file_names(self):
        cases = {
            "prusa-core-one-l": "core_one_l",
            "bracket_0.4n_0.2mm_PLA_COREONEL_25m.bgcode": "core_one_l",
            "box_0.4n_0.2mm_PETG_COREONE_1h3m.bgcode": "core_one",
            "prusa-core-one": "core_one",
            "prusa-xl": "xl",
            "part_0.4n_0.2mm_PLA_MK4S_47m.bgcode": "mk4s",
            "prusa-mk4": "mk4",
            "part_PLA_MK3.5S_1h.bgcode": "mk3.5s",
            "prusa-mk3-5": "mk3.5",
            "prusa-mini": "mini",
        }
        for hint, key in cases.items():
            self.assertEqual(printers.detect(hint), key, hint)

    def test_no_match_and_first_hint_wins(self):
        self.assertIsNone(printers.detect("my-printer", "", None))
        self.assertEqual(printers.detect("werkstatt", "x_PLA_COREONEL_2h.bgcode"), "core_one_l")


class PromptTest(unittest.TestCase):
    def test_corexy_prompt_describes_vertical_bed(self):
        p = vision.build_system_prompt("core_one_l")
        self.assertIn("Prusa CORE One L", p)
        self.assertIn("CoreXY", p)
        self.assertNotIn("bed-slinger", p)
        self.assertIn("report_assessment", p)

    def test_bedslinger_prompt_and_default(self):
        p = vision.build_system_prompt("mk4s")
        self.assertIn("Prusa MK4S is a bed-slinger", p)
        self.assertEqual(vision.build_system_prompt("nonsense"), vision.SYSTEM_PROMPT)
        self.assertIn("Prusa MK3.5S", vision.SYSTEM_PROMPT)


class ConfigTest(unittest.TestCase):
    BASE = {"printer_host": "10.0.0.5", "camera_url": "rtsp://10.0.0.6/live", "anthropic_api_key": "k"}

    def test_printer_model_validated(self):
        cfg = config.Config(**self.BASE, printer_model=" CORE_ONE_L ")
        cfg.validate()
        self.assertEqual(cfg.printer_model, "core_one_l")
        with self.assertRaises(ValueError):
            config.Config(**self.BASE, printer_model="ender3").validate()

    def test_power_entity_without_domain_is_ignored(self):
        cfg = config.Config(**self.BASE, power_entity="printendo")
        cfg.validate()
        self.assertEqual(cfg.power_entity, "")
        cfg = config.Config(**self.BASE, power_entity="sensor.plug_power")
        cfg.validate()
        self.assertEqual(cfg.power_entity, "sensor.plug_power")


class AgentPrinterTest(unittest.TestCase):
    def test_configured_model_sets_prompt(self):
        a = make_agent(printer_model="core_one_l")
        self.assertEqual(a.printer_model, "core_one_l")
        self.assertIn("CORE One L", a.judge.system_prompt)

    def test_auto_from_hostname(self):
        a = make_agent()
        a.printer.version.return_value = {"hostname": "prusa-core-one-l"}
        a._detect_printer()
        self.assertEqual(a.printer_model, "core_one_l")
        a._detect_printer("part_MK4S_1h.bgcode")                     # hostname wins
        self.assertEqual(a.printer_model, "core_one_l")

    def test_auto_falls_back_to_file_name(self):
        a = make_agent()
        a.printer.version.side_effect = OSError("printer off")
        a._detect_printer()
        self.assertEqual(a.printer_model, printers.DEFAULT)
        a._detect_printer("lid_0.4n_0.2mm_PLA_COREONEL_1h3m.bgcode")
        self.assertEqual(a.printer_model, "core_one_l")
        self.assertIn("CORE One L", a.judge.system_prompt)


@mock.patch.object(agent_mod.camera, "thumbnail", return_value=b"\x10" * 64)
@mock.patch.object(agent_mod.camera, "grab_jpeg", return_value=b"JPEG")
class LayoutGuardTest(unittest.TestCase):
    def run_ticks(self, a, statuses, verdicts):
        a.judge.assess.side_effect = verdicts
        for st in statuses:
            a.printer.status.return_value = st
            a.tick()

    def test_not_set_while_bed_is_parked_or_part_hidden(self, _grab, _thumb):
        a = make_agent()
        ok_hidden = Verdict("ok", "none", 0.8, "head covers it", part_visible="hidden")
        ok = Verdict("ok", "none", 0.8, "fine", part_visible="partly")
        self.run_ticks(a, [PrinterStatus("PRINTING", job_id=5, axis_z=288.1),
                           PrinterStatus("PRINTING", job_id=5, axis_z=20.0),
                           PrinterStatus("PRINTING", job_id=5, axis_z=0.6)],
                       [ok, ok, ok_hidden])
        self.assertIsNone(a.layout)
        self.run_ticks(a, [PrinterStatus("PRINTING", job_id=5, axis_z=0.8)], [ok])
        self.assertEqual(a.layout.z, 0.8)


class NotifyImageTest(unittest.TestCase):
    def test_media_url(self):
        self.assertEqual(notify.media_url("/media/prusa_watch/a.jpg"), "/media/local/prusa_watch/a.jpg")
        self.assertIsNone(notify.media_url("/share/prusa_watch/a.jpg"))

    def test_push_carries_image_for_media_snapshots(self):
        with mock.patch.dict(os.environ, {"SUPERVISOR_TOKEN": "tok"}), \
                mock.patch.object(notify.requests, "post") as post, \
                mock.patch.object(notify.HANotifier, "_save_snapshot", return_value="/media/prusa_watch/a.jpg"):
            post.return_value.raise_for_status = mock.Mock()
            notify.HANotifier("mobile_app_handy").send("Failure", "body", jpeg=b"J", filename="a.jpg")
        self.assertEqual(post.call_args.kwargs["json"]["data"], {"image": "/media/local/prusa_watch/a.jpg"})

    def test_prune_keeps_newest(self):
        with tempfile.TemporaryDirectory() as d:
            now = time.time()
            for i in range(5):
                path = os.path.join(d, f"flagged-{i}.jpg")
                with open(path, "wb") as f:
                    f.write(b"x")
                os.utime(path, (now + i, now + i))
            with open(os.path.join(d, "latest.jpg"), "wb") as f:
                f.write(b"x")
            self.assertEqual(notify.prune_images(d, "flagged-*.jpg", keep=2), 3)
            self.assertEqual(sorted(os.listdir(d)), ["flagged-3.jpg", "flagged-4.jpg", "latest.jpg"])


if __name__ == "__main__":
    unittest.main()
