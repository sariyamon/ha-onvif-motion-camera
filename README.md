# ONVIF Motion & Snapshot for Home Assistant

A custom integration for any ONVIF camera that gives you, in one place:

- **Live camera** (RTSP stream + still image)
- **A sensor for every detection the camera reports** — motion, person, vehicle, pet, face, line crossing, intrusion, region enter/exit, loitering, tamper, audio, digital input and more, created automatically as the camera reports them
- **Latest snapshot** taken on detection (from the camera's ONVIF snapshot URL, or straight from the video stream for cameras without one, such as TP-Link VIGI), kept across restarts, with its time — ready for a "Last Motion" dashboard
- **Telegram and WhatsApp alerts built in** — snapshot attached, no Node-RED, no extra automations
- **Camera controls**: pan / tilt / zoom buttons and preset positions for any ONVIF PTZ camera
- **TP-Link VIGI extras** (found automatically): spotlight, night-vision mode, siren & alarm light, motion / person / vehicle / tamper detection on-off, motion sensitivity, auto tracking, status LED, speaker and microphone
- Switches, buttons, services and bus events for your own automations

Set-up is just: **IP, port, protocol, username, password.** Install the same integration on any other Home Assistant and add cameras the same way.

Tested against TP-Link VIGI cameras (C340, C340S, C340-W, C350, C540V); works with any camera that supports ONVIF Profile S events (Hikvision, Dahua, Reolink, Imou, Tapo, Uniview, Axis…).

---

## Install

### HACS (recommended)
1. HACS → ⋮ → **Custom repositories** → add `https://github.com/sariyamon/ha-onvif-motion-camera`, type **Integration**.
   (On Home Assistant 2026.11+ use **Settings → Marketplace → Add from link**.)
2. Install **ONVIF Motion & Snapshot**, then restart Home Assistant.

### Manual
Copy `custom_components/onvif_motion` into your `/config/custom_components/` folder and restart.

## Add a camera
**Settings → Devices & services → Add integration → ONVIF Motion & Snapshot**, then choose how to connect:

| | **ONVIF** (recommended) | **RTSP only** |
|---|---|---|
| You enter | IP, ONVIF port, HTTP/HTTPS, login | RTSP address, login, transport |
| Live view & snapshots | ✅ | ✅ |
| Motion / person / vehicle sensors and alerts | ✅ | TP-Link VIGI only (push channel) |
| PTZ, presets, restart button | ✅ | – |
| TP-Link VIGI extras (spotlight, siren…) | ✅ | ✅ |

**ONVIF**

| Field | Example | Notes |
|---|---|---|
| Camera name | Gate | Used for the device and entity names |
| IP address | 192.168.31.101 | |
| ONVIF port | 2020 | TP-Link VIGI/Tapo: **2020**. Most others: **80** |
| Protocol | HTTP | HTTPS only if the camera's ONVIF service uses it |
| Username / password | admin / •••• | The camera's ONVIF (or admin) login |

Next you pick the **stream profile** (main or sub stream) and **RTSP transport**.

**RTSP only** – for cameras without ONVIF. Enter the RTSP address (e.g. `rtsp://192.168.31.120:554/stream1`), login and transport; a frame is grabbed from the stream to check it before the camera is added.

**Change it later** – open the camera's **Configure → Connection**. You can switch between ONVIF and RTSP only, change the IP, port, protocol, login, RTSP transport (TCP, UDP, UDP multicast, HTTP tunnel) or set a custom RTSP address. The camera is checked before saving and keeps its entities and history.

## What you get (camera named "Gate")

| Entity | What it is |
|---|---|
| `camera.gate` | Live stream and still image |
| `image.gate_last_snapshot` | The most recent detection snapshot (survives restarts) |
| `sensor.gate_last_snapshot_time` | When it was taken — use it for dashboard captions |
| `sensor.gate_last_detection` | Time of the last detection |
| `sensor.gate_last_detection_type` | motion / person / vehicle / line_crossing / … |
| `sensor.gate_detections_today` | Counter, resets at midnight |
| `binary_sensor.gate_motion`, `_person`, `_vehicle`, `_line_crossing_…`, `_intrusion_…`, `_tamper`, … | One per event the camera reports. Attributes: `topic`, `source`, `last_triggered`, `trigger_count`, raw `data` |
| `binary_sensor.gate_event_subscription` | Whether the ONVIF event feed is connected |
| `switch.gate_snapshots` | Take snapshots on detection |
| `switch.gate_telegram_alerts` / `switch.gate_whatsapp_alerts` | Per-camera alert on/off |
| `button.gate_take_snapshot`, `button.gate_send_test_alert`, `button.gate_restart` | |
| `button.<name>_pan_left` / `_pan_right` / `_tilt_up` / `_tilt_down` / `_zoom_in` / `_zoom_out`, `select.<name>_preset_position` | PTZ cameras only |
| `light.<name>_spotlight`, `select.<name>_night_vision`, `switch.<name>_motion_detection`, `_person_detection`, `_vehicle_detection`, `_tamper_detection`, `_siren_light_alarm`, `_alarm_light`, `_alarm_sound`, `_auto_tracking`, `_status_led`, `_speaker_mute`, `_microphone_mute`, `number.<name>_motion_sensitivity`, `_speaker_volume`, `_alarm_sound_repeats`, `button.<name>_sound_alarm` / `_stop_alarm` | TP-Link VIGI only, and only the settings your model has |

Event sensors appear the first time the camera reports that event. Walk in front of the camera once after adding it to see them all.

## Snapshots and alerts — no Node-RED

Open the integration → **Configure**:

- **Snapshots** – which events take a snapshot, minimum gap between snapshots, how many files to keep (stored in your media folder under `onvif_motion/`, so they also show in **Media**), and an optional minimum "on" time for event sensors.
- **Alert rules** – which events send an alert, minimum gap between alerts, and the message (`{camera}`, `{event}`, `{time}`, `{date}`).
- **Telegram** – pick chats from the Telegram bot you already have in Home Assistant (no token needed), or enter a bot token from @BotFather and chat IDs. Alerts arrive as a photo with caption.
- **WhatsApp** – choose a provider:
  - **WhatsApp Cloud API (Meta)** – sends the snapshot as a photo. Needs an access token, phone number ID and recipient numbers. Meta only delivers free-form messages to people who messaged your business number in the last 24 h; otherwise use an approved template or one of the options below.
  - **CallMeBot** – free and quick to set up, text only. Each recipient gets an API key from CallMeBot.
  - **Home Assistant notify action** – hands the message to any `notify.*` action you already have (for example a WhatsApp integration from HACS).

Press **Send test alert** on the device to check everything.

## Automations

Every detection is also a bus event:

```yaml
trigger: event
event_type: onvif_motion_event
event_data:
  camera: Gate
  event: person      # motion, vehicle, line_crossing, intrusion, tamper, …
  active: true
```

`onvif_motion_snapshot` fires whenever a snapshot is saved (`camera`, `event`, `path`).

Services:

- `onvif_motion.take_snapshot` – save a snapshot now (returns its path)
- `onvif_motion.send_alert` – send a Telegram/WhatsApp alert, optionally with a fresh snapshot, custom message and chosen channels

More in [`examples/automations.yaml`](examples/automations.yaml).

## Dashboard

[`examples/dashboard.yaml`](examples/dashboard.yaml) has a "Last Motion" grid: latest snapshot full-bleed with the camera name and time as plain white text over the picture, tap to open the live view.

## Replacing a Node-RED + local_file setup

If you used Node-RED for motion → snapshot → Telegram, plus `local_file` cameras and `input_text` / `input_datetime` helpers to remember the last snapshot, this integration does all of that by itself:

| Before | Now |
|---|---|
| Node-RED flow per camera | Built in (Configure → Snapshots / Alerts) |
| `camera.snapshot_gate` (local_file) | `image.gate_last_snapshot` |
| `input_datetime.last_snapshot_time_gate` | `sensor.gate_last_snapshot_time` |
| `input_text.last_snapshot_gate` + restore automations | Kept automatically across restarts |
| `input_boolean.telegram_notification_gate` | `switch.gate_telegram_alerts` |

Add the camera here, check the new entities work, then turn off the old flows.

## Troubleshooting

- **A VIGI camera shows no detections** – some models (e.g. the C540V PTZ) never send events over ONVIF. The integration notices this after about 90 seconds and switches that camera to TP-Link's own push channel (port 20443). Make sure **Push Notifications** is on for each detection type in the VIGI app.
- **Cannot connect** – check the ONVIF port (2020 on TP-Link), that ONVIF is enabled in the camera's web UI, and that the camera's clock is roughly right.
- **No event sensors** – `binary_sensor.<name>_event_subscription` should be on. Make sure motion/smart detection is enabled in the camera itself.
- **Debug log**:
  ```yaml
  logger:
    logs:
      custom_components.onvif_motion: debug
  ```

## Credits
The TP-Link VIGI controls are adapted from [VIGICam](https://github.com/steveAbratt/VIGICam) by Steve Bratt (MIT), whose login flow builds on [pytapo](https://github.com/JurajNyiri/pytapo) (MIT).

## License
MIT
