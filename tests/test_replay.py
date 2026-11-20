"""eval/replay.py: variant v4 uses the printer model of each sample (or the forced/configured one)."""
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from types import SimpleNamespace
from unittest import mock

ROOT = os.path.join(os.path.dirname(__file__), "..")
sys.path.insert(0, os.path.join(ROOT, "prusa_watch", "app"))
sys.path.insert(0, os.path.join(ROOT, "eval"))

import replay  # noqa: E402
from prusa_watch import printers, vision  # noqa: E402
from prusa_watch.dataset import Dataset  # noqa: E402


class SamplePrinterTest(unittest.TestCase):
    def test_order_forced_meta_context_default(self):
        ctx = "state=PRINTING\nPrint file: knob_0.4n_0.2mm_PLA_COREONEL_47m.bgcode"
        self.assertEqual(replay.sample_printer({"context": ctx}, "mk4s"), "mk4s")
        self.assertEqual(replay.sample_printer({"context": ctx, "printer_model": "xl"}), "xl")
        self.assertEqual(replay.sample_printer({"context": ctx}), "core_one_l")
        self.assertEqual(replay.sample_printer({"context": "state=PRINTING"}), printers.DEFAULT)
        self.assertEqual(replay.sample_printer({"printer_model": "unknown", "context": ""}), printers.DEFAULT)

    def test_config_printer(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "c.json")
            self.assertEqual(replay.config_printer(p), "auto")                  # file missing
            with open(p, "w") as f:
                json.dump({"printer_model": "CORE_ONE"}, f)
            self.assertEqual(replay.config_printer(p), "core_one")

    def test_v4_sets_prompt_v3_keeps_it(self):
        judge = mock.Mock(system_prompt="old")
        replay.assess("v4", judge, b"C", None, "ctx", printer_model="core_one_l")
        self.assertEqual(judge.system_prompt, vision.build_system_prompt("core_one_l"))
        judge3 = mock.Mock(system_prompt="v3 prompt")
        replay.assess("v3", judge3, b"C", None, "ctx", printer_model="core_one_l")
        self.assertEqual(judge3.system_prompt, "v3 prompt")


class DatasetRunTest(unittest.TestCase):
    def test_run_uses_each_samples_printer(self):
        with tempfile.TemporaryDirectory() as d:
            ds = Dataset(d, ok_every=1)
            for i, (ctx, model) in enumerate((("Print file: a_PLA_COREONEL_1h.bgcode", None),
                                              ("Print file: b_PLA_MK4S_1h.bgcode", None),
                                              ("no file", "core_one"))):
                sid = ds.save(1_700_000_000 + i * 60, i, b"JPEG", None, ctx,
                              {"status": "ok", "issue": "none", "confidence": 0.9}, "m", force=True,
                              printer_model=model)
                ds.label(sid, "ok")
            seen = []

            def fake_assess(current, reference, context, expected, layout=None):
                seen.append(judge.system_prompt)
                return vision.Verdict("ok", "none", 0.9, "fine")

            judge = mock.Mock(last_usage={})
            judge.assess.side_effect = fake_assess
            args = SimpleNamespace(dataset=d, variants="recorded,v4", config=os.path.join(d, "none.json"),
                                   model=None, positive="failure", printer_model=None)
            with mock.patch.object(replay, "make_judges", return_value={"v4": judge}), redirect_stdout(io.StringIO()) as out:
                replay.run_dataset(args)
            self.assertEqual(sorted(seen), sorted(vision.build_system_prompt(k) for k in ("core_one_l", "mk4s", "core_one")))
            self.assertIn("printer model for v4 (per sample)", out.getvalue())
            report = [f for f in os.listdir(d) if f.startswith("eval-")]
            with open(os.path.join(d, report[0]), encoding="utf-8") as f:
                self.assertEqual(sorted(json.load(f)["printer_models"].values()), ["core_one", "core_one_l", "mk4s"])

    def test_dataset_meta_has_printer_model(self):
        with tempfile.TemporaryDirectory() as d:
            ds = Dataset(d)
            sid = ds.save(1_700_000_000, 1, b"J", None, "", {"status": "warning"}, "m", printer_model="core_one_l")
            self.assertEqual(ds.get(sid)["printer_model"], "core_one_l")


if __name__ == "__main__":
    unittest.main()
