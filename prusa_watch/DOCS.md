# Prusa Watch

AI watchdog for a Prusa printer with a Buddy3D camera. While a print runs it grabs a camera frame every
minute, sends it with PrusaLink telemetry and the G-code thumbnail to Claude (Haiku 5.5 via the Claude API), and notifies you through Home Assistant when the print fails.
Repository: https://github.com/thewizard-de/prusa-watch (fork of https://github.com/scostic/prusa-watch; the
changes are described in CHANGELOG.md)

## Before you start
- PrusaLink enabled on the printer (API key from *Settings → Network → PrusaLink*).
- Camera RTSP enabled: Prusa Connect → printer → *Camera* → *Streaming* = **RTSP**
  (stream at `rtsp://<camera-ip>/live`).
- A Claude API key from console.anthropic.com. No AWS account is needed; notifications go through Home Assistant.

At every start the add-on checks the AI provider and logs `AI provider check OK` - or the exact problem and
sends a Home Assistant notification, so a wrong key is found before a print.

## Options

| Option | Meaning |
|---|---|
| `printer_host` | PrusaLink IP or hostname |
| `printer_model` | `auto` (default) or the printer: `core_one_l`, `core_one`, `xl`, `mk4s`, `mk4`, `mk3.5s`, `mk3.5`, `mini`. Sets how the AI is told the printer moves (CoreXY with a bed that only lowers vs. a bed-slinger). `auto` reads the PrusaLink hostname (e.g. `prusa-core-one-l`), else the printer suffix in the G-code file name; the log shows `Printer model: ...` |
| `prusalink_api_key` | PrusaLink API key (or use `prusalink_username` / `prusalink_password` digest login) |
| `camera_url` / `camera_rotate` | RTSP URL; rotate frames 0/90/180/270° if the stream is upside down |
| `anthropic_api_key`, `anthropic_model` | Claude API key from console.anthropic.com and model, default `claude-haiku-5-5` |
| `ha_notify_service` | optional notify service for phone push, e.g. `mobile_app_handy` (the snapshot is attached as picture); empty = sidebar notification in Home Assistant |
| `check_interval_s` | seconds between checks while printing (60) |
| `compare_minutes` | age of the reference frame used to judge growth (5) |
| `failure_threshold`, `min_confidence` | consecutive confident failure verdicts before an email (3, 0.6) |
| `confirm_failures` | re-check every failure on a second frame before it counts (on) |
| `warning_threshold` | this many suspicious verdicts in a row (warnings or unconfirmed failures) send a "suspicious print" email, never a pause/stop; 0 = off (3) |
| `layout_reference` | keep the first good frame of each print with the parts in view and Z ≤ 5 mm (first layers) as the layout the model checks every frame against (on) |
| `use_gcode_thumbnail` | also show the model the slicer preview of the object from the G-code (on) |
| `skip_preheat` | no AI checks while heating up at 0% progress (on) |
| `alert_cooldown_min` | minimum minutes between repeated failure emails (30) |
| `notify_finished` | notify when a print finishes (on) |
| `keep_images` | newest alert and `flagged-*` snapshots kept, older ones are deleted (300) |
| `auto_action`, `auto_action_threshold` | `none` / `pause` / `stop` after N consecutive failures (off by default) |
| `power_entity`, `energy_price`, `currency` | optional smart plug power sensor in W as full entity id (`sensor.…`) → energy and cost per print; a value without domain is ignored |
| `heartbeat_min`, `blind_alert_min` | proof-of-life and "watchdog blind" alert |
| `hec_url`, `hec_token`, `hec_index`, `hec_verify_tls` | optional Splunk HEC output |

## Outputs
- `sensor.prusa_watch`: state = latest verdict while printing (`ok` / `warning` / `failure` /
  `camera_problem`), otherwise the printer state (`idle`, `paused`, `attention`, `finished`, `offline`...);
  `printing` with `phase: preheat` while heating up (no AI checks yet).
  Attributes: `issue`, `confidence`, `description`, `part_visible`, `streak`, `last_check`, `printer_state`,
  `printer_model`, `job_id`, `progress`, `time_remaining`, `axis_z`, `temp_nozzle`, `target_nozzle`, `temp_bed`, `target_bed`,
  and with a smart plug `power_w`, `print_energy_kwh`, `print_energy_cost`.
- `/share/prusa_watch/latest.jpg` and `flagged-*.jpg` for warnings/failures; alert snapshots in
  `/media/prusa_watch/` (Home Assistant *Media → My media → prusa_watch*).
- Emails: possible failure, printer attention, camera unreachable, watchdog blind, AI provider not working,
  print finished (with energy and cost when `power_entity` is set).
- Optional Splunk events (`type` = `check`, `state`, `email`, `error`, `heartbeat`, `energy`, `ai_check`,
  `label`). Checks carry `provider`, `model`, tokens, latency and `cost_usd`.

## Labelling (test set)
Open **Prusa Watch** in the Home Assistant sidebar to label saved checks as ✅ OK print or ❌ Real failure.
For quick labels, create three *Button* helpers (Settings → Devices & services → Helpers → Create helper →
Button) named **Prusa Watch Correct**, **Prusa Watch False alarm** and **Prusa Watch Missed failure**
(entity IDs `input_button.prusa_watch_correct`, `..._false_alarm`, `..._missed_failure`), and put them on a
dashboard. Options: `dataset_enabled`, `dataset_ok_every`, `dataset_max`, `label_button_*`.

## Smart plug
Set `power_entity` to the plug's power sensor in W (e.g. `sensor.<plug>_current_consumption`) and
`energy_price` to your price per kWh. An example automation that switches the plug off after the print, once
the nozzle is below 50 °C, is in the repository under `ha/`.

Keep `auto_action: none` until you have watched a few prints and tested a deliberate failure.
This is a convenience monitor, not a safety device - never leave a printer unattended if that is unsafe.
