"""Tests for the fork changes: Home Assistant notifications and the PrusaLink pause/stop methods."""
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "prusa_watch", "app"))

from prusa_watch import notify  # noqa: E402
from prusa_watch.prusalink import PrusaLink  # noqa: E402


class HANotifierTest(unittest.TestCase):
    def test_disabled_without_supervisor_token(self):
        with mock.patch.dict(os.environ, {}, clear=True):
            n = notify.HANotifier()
        with self.assertRaises(RuntimeError):
            n.send("subject", "body")

    def test_persistent_notification_by_default(self):
        with mock.patch.dict(os.environ, {"SUPERVISOR_TOKEN": "tok"}), \
                mock.patch.object(notify.requests, "post") as post:
            post.return_value.raise_for_status = mock.Mock()
            notify.HANotifier().send("Suspicious print", "body text")
        url = post.call_args.args[0]
        payload = post.call_args.kwargs["json"]
        self.assertTrue(url.endswith("/services/persistent_notification/create"))
        self.assertEqual(payload["title"], "Suspicious print")
        self.assertEqual(payload["message"], "body text")
        self.assertTrue(payload["notification_id"].startswith("prusa_watch_"))
        self.assertEqual(post.call_args.kwargs["headers"]["Authorization"], "Bearer tok")

    def test_push_service_with_notify_prefix(self):
        with mock.patch.dict(os.environ, {"SUPERVISOR_TOKEN": "tok"}), \
                mock.patch.object(notify.requests, "post") as post:
            post.return_value.raise_for_status = mock.Mock()
            notify.HANotifier("notify.mobile_app_handy").send("Print finished", "done")
        self.assertTrue(post.call_args.args[0].endswith("/services/notify/mobile_app_handy"))
        self.assertEqual(post.call_args.kwargs["json"], {"title": "Print finished", "message": "done"})

    def test_snapshot_saved_and_linked_in_message(self):
        import tempfile
        with tempfile.TemporaryDirectory() as d, \
                mock.patch.dict(os.environ, {"SUPERVISOR_TOKEN": "tok"}), \
                mock.patch.object(notify.requests, "post") as post:
            post.return_value.raise_for_status = mock.Mock()
            notify.HANotifier(alert_dir=d).send("Suspicious", "body", jpeg=b"JPEG", filename="a.jpg")
            with open(os.path.join(d, "a.jpg"), "rb") as f:
                self.assertEqual(f.read(), b"JPEG")
            self.assertIn(os.path.join(d, "a.jpg"), post.call_args.kwargs["json"]["message"])


class PrusaLinkActionsTest(unittest.TestCase):
    """Regression: pause/stop used to sit after a return in thumbnail_ref() and were never class methods."""

    def test_pause_and_stop_are_methods(self):
        self.assertTrue(callable(getattr(PrusaLink, "pause", None)))
        self.assertTrue(callable(getattr(PrusaLink, "stop", None)))

    def test_pause_sends_put_and_stop_sends_delete(self):
        p = PrusaLink("10.0.0.5", api_key="k")
        with mock.patch.object(p.session, "request") as req:
            req.return_value.raise_for_status = mock.Mock()
            p.pause(9)
            p.stop(9)
        self.assertEqual(req.call_args_list[0].args, ("PUT", "http://10.0.0.5/api/v1/job/9/pause"))
        self.assertEqual(req.call_args_list[1].args, ("DELETE", "http://10.0.0.5/api/v1/job/9"))


if __name__ == "__main__":
    unittest.main()
