# Changelog

## 0.10.1-ha (fork)
- **`eval/replay.py` respects the printer model.** New variant `v4` = current prompt with the printer of each
  sample: `--printer-model` forces one, otherwise `printer_model` from the config, and with `auto` the model
  saved in the sample (`meta.json` "printer_model"), else detected from its "Print file:" line, else mk3.5s.
  `v3` stays the 0.9.0 prompt (MK3.5S description) for comparison; the default dataset run is `recorded,v4`.
  The report JSON lists the printer model used per sample.
- Dataset samples now store `printer_model` in `meta.json`.

## 0.10.0-ha (fork)
- **Printer selection.** New option `printer_model` (`auto`, `core_one_l`, `core_one`, `xl`, `mk4s`, `mk4`,
  `mk3.5s`, `mk3.5`, `mini`). The prompt (v4) now describes how the chosen printer moves: CoreXY printers
  (CORE One, CORE One L, XL) have a bed that only lowers, bed-slingers (MK4/MK3.5/MINI) slide the bed. Until now
  every printer was described as an MK3.5S bed-slinger. `auto` reads the PrusaLink hostname, else the printer
  suffix in the G-code file name (`..._COREONEL_25m.bgcode`).
- **Layout frame only from the first layers.** It is now taken from the first `ok` check with the parts in view
  and 0 < Z ≤ 5 mm. On the CORE One L it was set at Z=288 mm (bed parked, sheet empty) and later checks
  then reported "parts missing".
- **Picture in the phone push.** Alert snapshots are saved to `/media/prusa_watch/` (add-on maps `media`) and
  attached to `ha_notify_service` pushes as `/media/local/prusa_watch/...`.
- **Snapshots are pruned**: new option `keep_images` (300) for alert snapshots and `flagged-*.jpg`.
- `power_entity` without a domain (e.g. `printendo`) is ignored with a warning instead of silently reading nothing.
- `sensor.prusa_watch` has a `printer_model` attribute; `requirements.txt` pins major versions; repository URLs
  point to this fork; `__version__` matches the add-on version.

## 0.9.2-ha (fork)
- **AWS removed.** Bedrock is gone, Claude API is the only AI provider. The options `ai_provider`,
  `bedrock_model_id`, `aws_region`, `aws_access_key_id`, `aws_secret_access_key` and `cloudwatch_heartbeat` were
  removed from the add-on configuration and the code. `boto3` is no longer a dependency. Old values in a saved
  configuration are ignored.
- `anthropic_api_key` is now required.

## 0.9.1-ha (fork)
- **Notifications go through Home Assistant instead of Amazon SES.** Alerts become a persistent notification
  in the HA sidebar, or a phone push when `ha_notify_service` is set (e.g. `mobile_app_handy`). Alert snapshots
  are saved to `/share/prusa_watch/alerts/` and the path is included in the message.
  `email_from` / `email_to` were removed. `cloudwatch_heartbeat` now defaults to off.
- **Fixed: auto pause/stop never worked.** `pause()` and `stop()` were defined after a `return` inside
  `thumbnail_ref()` and so were not methods of `PrusaLink`. Calling them raised `AttributeError`, which was
  only logged as "FAILED". They are now real methods, covered by `tests/test_fork.py`.
- The event type for notifications is now `notify` (was `email`) in Splunk/HEC output.

## 0.9.0
- **Catches parts that come loose.** A real failure (flat PETG parts torn off and dragged by the nozzle) was
  judged `ok` because the v2 prompt told the model to ignore where the part is. Prompt **v3** checks the
  layout of the parts on the bed sheet (relative to the sheet and to each other, not the image), tells
  hidden-behind-the-head from missing, and treats a part that moved, tipped or vanished as `detached_part`.
- **Layout frame:** the first good frame of each print (first layers) is kept and sent with every check as
  ground truth for where the parts are. Stored with samples (`layout.jpg`) and shown in the panel.
  Option `layout_reference` (on).
- Guard relaxed: `detached_part` now counts with the part partly visible; still downgraded when hidden.
- **Warning streak:** `warning_threshold` (3) suspicious verdicts in a row send a "Suspicious print, please
  look" email. They never pause/stop the printer. Check events carry `warn_streak` and `alert_reason`.
- `eval/replay.py`: variant `v3` (current), `v2` reproduces the 0.3-0.8 prompt and guard.
- Replay (Haiku 5.5): good print 0/33 false alarms with v2 and v3; the failed frame v2 `ok`, v3 `failure`.

## 0.8.4
- Fix: the `energy` event at the end of a print now carries the `job_id` of the print (PrusaLink reports no
  job id once the job is FINISHED), so energy and cost can be matched to their print.

## 0.8.3
- No AI checks while the printer heats up: PrusaLink reports PRINTING during preheat and bed levelling, so
  checks now start once nozzle and bed are within 5 °C of target (or progress > 0). Saves calls and avoids
  confused warnings; the BLIND timer starts after preheat. HA shows `printing` with `phase: preheat`.
  Option `skip_preheat` (on).
- Confirmed on a real print: Buddy firmware serves the G-code thumbnail as PNG at `/thumb/l/<storage>/<file>`.

## 0.8.2
- **AI provider self-check at startup**: a free Models API lookup (Claude API) or a 1-token request (Bedrock)
  logs `AI provider check OK` or the exact problem (401 key, 403 access, 404 model), sends a `type=ai_check`
  event, and emails you on configuration errors - so a bad key is found before a print, not during one.

## 0.8.1
- Heartbeat events carry `provider` and `model`, so Splunk shows which model is active even between prints.
- AI errors are logged as `AI call failed (<provider>:<model>)` with `component=ai` (previously always "Bedrock").

## 0.8.0
- **Claude API as an alternative to Bedrock**: `ai_provider: anthropic` + `anthropic_api_key`, default model
  **Claude Haiku 5.5** (`claude-haiku-5-5`). Bedrock remains the default; AWS is still used for SES email and
  the CloudWatch heartbeat.
- Cost per check is computed in the add-on per model and sent as `cost_usd`; the Splunk app uses it.
- `eval/replay.py --provider/--model` to compare models on the same frames.
- Same 33 frames from a good print: Haiku 4.5 (Bedrock) 2 false alarms and the part judged "hidden" in 24;
  **Haiku 5.5 0 false alarms, part seen in 29**, at ~$0.00045 per check (~8× cheaper).

## 0.7.0
- The model now also sees **what the part should look like**: the slicer thumbnail embedded in the G-code,
  fetched once per job from PrusaLink (`/api/v1/job` → `file.refs.thumbnail`), converted with ffmpeg
  (PNG or QOI from `.bgcode`, transparent background flattened onto grey) and sent as an "EXPECTED" image
  with the file name. About 150 extra input tokens per check. Option `use_gcode_thumbnail` (on).
- Samples store the expected image too; the labelling panel shows it.
- `eval/replay.py`: variant `v2-noexp` re-runs without the thumbnail, to measure its effect.

## 0.6.0
- Labelled test set: every warning/failure check (and 1 in `dataset_ok_every` normal checks) is saved to
  `/share/prusa_watch/dataset/<id>/` with both frames, the exact context the model saw and its verdict.
- **"Prusa Watch" panel in the Home Assistant sidebar** (ingress) to label samples: ✅ OK print / ❌ Real failure + issue.
- Quick labels from `input_button` helpers: *Correct* / *False alarm* (latest alert) and *Missed failure*
  (saves and labels the latest frame as a real failure).
- `eval/replay.py --dataset` reports a confusion matrix, recall (failures caught), precision and false-alarm
  rate; variant `recorded` scores the live verdicts without any API calls.

## 0.5.0
- Smart-plug energy per print: set `power_entity` to the plug's power sensor (W) and `energy_price`
  (per kWh). The add-on integrates power over the job and reports kWh and cost in the "Print finished"
  email, `sensor.prusa_watch` (`power_w`, `print_energy_kwh`, `print_energy_cost`) and Splunk (`type=energy`).
- Plug power is included in the telemetry the model sees.
- Example automation `ha/prusa-power-off-after-print.yaml`: plug off after the print once the nozzle is < 50 °C.

## 0.4.1
- "Printer unreachable" is reported once per outage instead of every minute (a switched-off printer is normal).

## 0.4.0
- Heartbeat every `heartbeat_min` minutes to CloudWatch (`PrusaWatch/Heartbeat`) and Splunk, for a
  dead man's switch alarm outside your home network (`aws/heartbeat-alarm.ps1`).
- "Watchdog blind" email when a print runs but no AI check has succeeded for `blind_alert_min` minutes.

## 0.3.1
- `sensor.prusa_watch` carries printer telemetry as attributes (progress, time remaining, nozzle/bed
  temperatures and targets, Z) for dashboards and the SenseCAP Indicator page.

## 0.3.0
- New prompt that understands bed-slinger motion and requires positive visual evidence for a failure.
- Model also reports `part_visible` and `evidence`; guard rule: `detached_part` only counts when the part
  is fully visible.
- A failure verdict is re-checked on a second frame a few seconds later (`confirm_failures`).
- Reference frame is reset after a pause / attention.
- Replay of 33 previously flagged frames from a good print: false alarms 14 → 2.

## 0.2.0
- Optional Splunk HTTP Event Collector output (checks, state changes, emails, errors, token usage).

## 0.1.1
- PrusaLink API-key login, camera rotation option, trimmed secrets.

## 0.1.0
- First release: PrusaLink telemetry + RTSP frame → Claude Haiku 4.5 on Amazon Bedrock → SES email.
