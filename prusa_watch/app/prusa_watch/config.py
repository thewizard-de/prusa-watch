import json
import logging
from dataclasses import dataclass, fields

from . import printers

log = logging.getLogger(__name__)

AUTO_ACTIONS = ("none", "pause", "stop")


@dataclass
class Config:
    printer_host: str
    printer_model: str = "auto"         # auto | core_one_l | core_one | xl | mk4s | mk4 | mk3.5s | mk3.5 | mini
    prusalink_api_key: str = ""
    prusalink_username: str = "maker"
    prusalink_password: str = ""
    camera_url: str = ""
    camera_rotate: int = 0
    anthropic_api_key: str = ""
    anthropic_model: str = "claude-haiku-5-5"
    ha_notify_service: str = ""       # e.g. mobile_app_handy (phone push); empty = HA sidebar notification
    check_interval_s: int = 60
    compare_minutes: int = 5
    failure_threshold: int = 3
    min_confidence: float = 0.6
    confirm_failures: bool = True
    warning_threshold: int = 3        # this many suspicious verdicts in a row also email (0 = off)
    layout_reference: bool = True     # keep a first-layer frame as the layout ground truth for the job
    use_gcode_thumbnail: bool = True  # show the model the slicer preview of the object being printed
    skip_preheat: bool = True         # no AI checks while heating up at 0% progress
    alert_cooldown_min: int = 30
    notify_finished: bool = True
    auto_action: str = "none"
    auto_action_threshold: int = 5
    ha_sensor: bool = True
    power_entity: str = ""            # HA sensor with the printer plug's power in W
    energy_price: float = 0.0         # price per kWh, for the cost per print
    currency: str = "€"
    dataset_enabled: bool = True      # keep labelled samples for evaluation (/share/prusa_watch/dataset)
    dataset_ok_every: int = 10        # keep 1 in N 'ok' checks (all warnings/failures are kept)
    dataset_max: int = 2000
    label_button_correct: str = "input_button.prusa_watch_correct"
    label_button_false_alarm: str = "input_button.prusa_watch_false_alarm"
    label_button_missed: str = "input_button.prusa_watch_missed_failure"
    heartbeat_min: int = 5
    blind_alert_min: int = 10
    hec_url: str = ""
    hec_token: str = ""
    hec_index: str = "prusa_watch"
    hec_verify_tls: bool = True
    snapshot_dir: str = "/share/prusa_watch"
    alert_dir: str = "/media/prusa_watch"   # alert snapshots, attached to phone pushes as /media/local/...
    keep_images: int = 300               # newest alert/flagged snapshots kept in each folder
    log_level: str = "info"

    @property
    def ai_provider(self) -> str:
        return "anthropic"          # the only provider since 0.9.2-ha (AWS/Bedrock removed)

    @property
    def model_id(self) -> str:
        return self.anthropic_model

    def validate(self) -> None:
        # Pasted secrets often carry stray spaces/newlines.
        self.printer_model = str(self.printer_model or "auto").strip().lower()
        for name in ("printer_host", "camera_url", "prusalink_api_key", "prusalink_password",
                     "ha_notify_service", "hec_url", "hec_token", "hec_index", "power_entity",
                     "anthropic_api_key", "anthropic_model"):
            setattr(self, name, str(getattr(self, name) or "").strip())
        problems = []
        if not self.anthropic_api_key:
            problems.append("anthropic_api_key is required")
        if not self.printer_host or "X" in self.printer_host:
            problems.append("printer_host is not set")
        if not self.camera_url or "Y" in self.camera_url:
            problems.append("camera_url is not set")
        try:
            self.camera_rotate = int(self.camera_rotate)   # HA list() options arrive as strings
        except (TypeError, ValueError):
            self.camera_rotate = -1
        if self.camera_rotate not in (0, 90, 180, 270):
            problems.append("camera_rotate must be 0, 90, 180 or 270")
        if self.printer_model not in printers.CHOICES:
            problems.append(f"printer_model must be one of {printers.CHOICES}")
        if self.power_entity and "." not in self.power_entity:
            log.warning("power_entity %r is not an entity id (e.g. sensor.plug_power) - energy tracking is off",
                        self.power_entity)
            self.power_entity = ""
        if self.auto_action not in AUTO_ACTIONS:
            problems.append(f"auto_action must be one of {AUTO_ACTIONS}")
        if problems:
            raise ValueError("; ".join(problems))
        # Never act before the user has had at least one warning email.
        if self.auto_action != "none" and self.auto_action_threshold <= self.failure_threshold:
            log.warning(
                "auto_action_threshold (%d) <= failure_threshold (%d); raising it to %d",
                self.auto_action_threshold, self.failure_threshold, self.failure_threshold + 1,
            )
            self.auto_action_threshold = self.failure_threshold + 1


def load(path: str) -> Config:
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    known = {f.name for f in fields(Config)}
    for key in set(raw) - known:
        log.warning("Ignoring unknown option %r", key)
    cfg = Config(**{k: v for k, v in raw.items() if k in known})
    cfg.validate()
    return cfg
