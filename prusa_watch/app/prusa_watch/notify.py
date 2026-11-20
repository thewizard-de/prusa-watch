"""Outbound notifications: Home Assistant (push or persistent notification) and the HA sensor."""
import glob
import json
import logging
import os
import time
from typing import Optional

import requests

log = logging.getLogger(__name__)

ALERT_DIR = "/media/prusa_watch"   # snapshots that came with an alert (HA media browser: My media -> prusa_watch)
MEDIA_ROOT = "/media"              # the add-on's view of HA's media folder, served as /media/local/...


def prune_images(directory: str, pattern: str = "*.jpg", keep: int = 300) -> int:
    """Delete all but the newest `keep` files matching pattern in directory; returns how many were removed."""
    if keep <= 0:
        return 0
    try:
        files = sorted(glob.glob(os.path.join(directory, pattern)), key=os.path.getmtime)
    except OSError:
        return 0
    removed = 0
    for path in files[:-keep]:
        try:
            os.remove(path)
            removed += 1
        except OSError:
            pass
    return removed


def media_url(path: str) -> Optional[str]:
    """/media/prusa_watch/x.jpg -> /media/local/prusa_watch/x.jpg (what the HA companion app can attach)."""
    norm = path.replace("\\", "/")
    if not norm.startswith(MEDIA_ROOT + "/"):
        return None
    return "/media/local/" + norm[len(MEDIA_ROOT) + 1:]


class HANotifier:
    """Sends alerts through Home Assistant. With `service` set (e.g. "mobile_app_handy") the
    notify service is used (phone push); otherwise a persistent notification appears in the
    HA sidebar. Only works inside the add-on (needs the Supervisor token)."""

    def __init__(self, service: str = "", alert_dir: str = ALERT_DIR, keep: int = 300):
        self.token = os.environ.get("SUPERVISOR_TOKEN")
        service = (service or "").strip()
        self.service = service[len("notify."):] if service.startswith("notify.") else service
        self.alert_dir = alert_dir
        self.keep = keep

    def send(self, subject: str, body: str, jpeg: Optional[bytes] = None,
             filename: str = "snapshot.jpg", actions: Optional[list] = None) -> None:
        """actions: [(action_id, title), ...] - buttons in the phone push (companion app), ignored for the
        sidebar notification. HA fires mobile_app_notification_action with the action id when one is tapped."""
        if not self.token:
            raise RuntimeError("Home Assistant notifications need the add-on environment (no SUPERVISOR_TOKEN)")
        message = body
        image = None
        if jpeg:
            path = self._save_snapshot(jpeg, filename)
            if path:
                message += f"\n\nSnapshot: {path}"
                image = media_url(path)
        headers = {"Authorization": f"Bearer {self.token}"}
        if self.service:
            url = f"http://supervisor/core/api/services/notify/{self.service}"
            payload = {"title": subject, "message": message}
            data = {}
            if image:
                data["image"] = image                     # the companion app shows the snapshot in the push
            if actions:
                data["actions"] = [{"action": a, "title": t} for a, t in actions]
            if data:
                payload["data"] = data
        else:
            url = "http://supervisor/core/api/services/persistent_notification/create"
            payload = {"title": subject, "message": message,
                       "notification_id": f"prusa_watch_{int(time.time() * 1000)}"}
        r = requests.post(url, headers=headers, json=payload, timeout=10)
        r.raise_for_status()
        log.info("Notification sent: %s", subject)

    def _save_snapshot(self, jpeg: bytes, filename: str) -> Optional[str]:
        try:
            os.makedirs(self.alert_dir, exist_ok=True)
            path = os.path.join(self.alert_dir, filename)
            with open(path, "wb") as f:
                f.write(jpeg)
            prune_images(self.alert_dir, keep=self.keep)
            return path
        except OSError as e:
            log.warning("Could not save alert snapshot: %s", e)
            return None


class HECSender:
    """Sends events to a Splunk HTTP Event Collector. Never raises; failed events are
    kept (bounded) and retried with the next send."""

    def __init__(self, url: str, token: str, index: str = "", sourcetype: str = "prusa:watch",
                 host: str = "prusa-watch", verify_tls: bool = True, max_backlog: int = 500):
        self.enabled = bool(url and token)
        self.url = url.rstrip("/")
        if self.enabled and not self.url.endswith("/services/collector/event"):
            self.url += "/services/collector/event"
        self.index = index
        self.sourcetype = sourcetype
        self.host = host
        self.verify_tls = verify_tls
        self.session = requests.Session()
        self.session.headers["Authorization"] = f"Splunk {token}"
        self.backlog: list[dict] = []
        self.max_backlog = max_backlog
        self._warned = False

    def send(self, event: dict, t: float) -> None:
        if not self.enabled:
            return
        payload = {"time": round(t, 3), "host": self.host, "source": "prusa_watch",
                   "sourcetype": self.sourcetype, "event": event}
        if self.index:
            payload["index"] = self.index
        self.backlog.append(payload)
        del self.backlog[:-self.max_backlog]
        body = "\n".join(json.dumps(p, separators=(",", ":")) for p in self.backlog)
        try:
            r = self.session.post(self.url, data=body, timeout=5, verify=self.verify_tls)
            r.raise_for_status()
            self.backlog.clear()
            self._warned = False
        except requests.RequestException as e:
            if not self._warned:
                log.warning("Splunk HEC send failed (%d queued): %s", len(self.backlog), e)
                self._warned = True


class HASensor:
    """Publishes sensor.prusa_watch via the Supervisor proxy (only inside the add-on)."""

    URL = "http://supervisor/core/api/states/sensor.prusa_watch"

    def __init__(self, enabled: bool):
        self.token = os.environ.get("SUPERVISOR_TOKEN")
        self.enabled = enabled and bool(self.token)

    def publish(self, state: str, **attributes) -> None:
        if not self.enabled:
            return
        attributes.setdefault("friendly_name", "Prusa Watch")
        attributes.setdefault("icon", "mdi:printer-3d-nozzle-alert")
        try:
            requests.post(
                self.URL, timeout=5,
                headers={"Authorization": f"Bearer {self.token}"},
                json={"state": state, "attributes": attributes},
            ).raise_for_status()
        except requests.RequestException as e:
            log.warning("Could not update Home Assistant sensor: %s", e)

    def read_state(self, entity_id: str) -> Optional[str]:
        """Raw state string of another HA entity, None if it doesn't exist or HA is unreachable."""
        if not (self.token and entity_id):
            return None
        try:
            r = requests.get(f"http://supervisor/core/api/states/{entity_id}", timeout=5,
                             headers={"Authorization": f"Bearer {self.token}"})
            r.raise_for_status()
            return str(r.json()["state"])
        except (requests.RequestException, KeyError, TypeError, ValueError):
            return None

    def read_number(self, entity_id: str) -> Optional[float]:
        """Numeric state of another HA entity (e.g. a smart plug's power sensor), None if unavailable."""
        try:
            return float(self.read_state(entity_id))
        except (TypeError, ValueError):
            return None      # unknown / unavailable / not numeric


class EnergyMeter:
    """Integrates a power reading (W) into energy (Wh) for the current print job."""

    MAX_GAP_S = 600     # ignore gaps longer than this (add-on restart, plug offline)

    def __init__(self):
        self.reset()

    def reset(self) -> None:
        self.wh = 0.0
        self.last: Optional[tuple[float, float]] = None   # (time, watts)
        self.samples = 0

    def add(self, t: float, watts: Optional[float]) -> None:
        if watts is None or watts < 0:
            self.last = None
            return
        if self.last is not None:
            t0, w0 = self.last
            dt = t - t0
            if 0 < dt <= self.MAX_GAP_S:
                self.wh += (w0 + watts) / 2 * dt / 3600
        self.last = (t, watts)
        self.samples += 1

    @property
    def kwh(self) -> float:
        return self.wh / 1000
