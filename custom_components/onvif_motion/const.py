"""Constants for the ONVIF Motion & Snapshot integration."""
from __future__ import annotations

from datetime import timedelta
from typing import Final

DOMAIN: Final = "onvif_motion"
MANUFACTURER_FALLBACK: Final = "ONVIF"

# Config entry data
CONF_PROTOCOL: Final = "protocol"
CONF_PROFILE_TOKEN: Final = "profile_token"
CONF_RTSP_TRANSPORT: Final = "rtsp_transport"

PROTOCOL_HTTP: Final = "http"
PROTOCOL_HTTPS: Final = "https"
PROTOCOLS: Final = [PROTOCOL_HTTP, PROTOCOL_HTTPS]
RTSP_TRANSPORTS: Final = ["tcp", "udp", "udp_multicast", "http"]
CONF_STREAM_URL: Final = "stream_url"  # optional custom RTSP address

DEFAULT_PORT: Final = 80
DEFAULT_USERNAME: Final = "admin"

# Options – snapshots
CONF_SNAPSHOT_EVENTS: Final = "snapshot_events"
CONF_SNAPSHOT_COOLDOWN: Final = "snapshot_cooldown"
CONF_SNAPSHOT_KEEP: Final = "snapshot_keep"
CONF_EVENT_OFF_DELAY: Final = "event_off_delay"

DEFAULT_SNAPSHOT_COOLDOWN: Final = 10
DEFAULT_SNAPSHOT_KEEP: Final = 50
DEFAULT_EVENT_OFF_DELAY: Final = 0

# Options – alerts
CONF_ALERT_EVENTS: Final = "alert_events"
CONF_ALERT_COOLDOWN: Final = "alert_cooldown"
CONF_ALERT_MESSAGE: Final = "alert_message"
DEFAULT_ALERT_COOLDOWN: Final = 60
DEFAULT_ALERT_MESSAGE: Final = "{event} detected at {camera} – {time}"

CONF_TELEGRAM_TOKEN: Final = "telegram_bot_token"
CONF_TELEGRAM_CHAT_IDS: Final = "telegram_chat_ids"
# Alternative: send through a Telegram bot already set up in Home Assistant
CONF_TELEGRAM_NOTIFY: Final = "telegram_notify_entities"

CONF_WHATSAPP_PROVIDER: Final = "whatsapp_provider"
CONF_WHATSAPP_TOKEN: Final = "whatsapp_access_token"
CONF_WHATSAPP_PHONE_ID: Final = "whatsapp_phone_number_id"
CONF_WHATSAPP_RECIPIENTS: Final = "whatsapp_recipients"
CONF_WHATSAPP_APIKEY: Final = "whatsapp_callmebot_apikey"
CONF_WHATSAPP_NOTIFY_ACTION: Final = "whatsapp_notify_action"

WA_NONE: Final = "none"
WA_CLOUD_API: Final = "cloud_api"
WA_CALLMEBOT: Final = "callmebot"
WA_HA_NOTIFY: Final = "ha_notify"
WHATSAPP_PROVIDERS: Final = [WA_NONE, WA_CLOUD_API, WA_CALLMEBOT, WA_HA_NOTIFY]

# Event kinds (the logical type of an ONVIF event)
EV_MOTION: Final = "motion"
EV_PERSON: Final = "person"
EV_VEHICLE: Final = "vehicle"
EV_PET: Final = "pet"
EV_FACE: Final = "face"
EV_LINE: Final = "line_crossing"
EV_INTRUSION: Final = "intrusion"
EV_REGION_ENTER: Final = "region_entrance"
EV_REGION_EXIT: Final = "region_exit"
EV_LOITERING: Final = "loitering"
EV_TAMPER: Final = "tamper"
EV_TOO_DARK: Final = "image_too_dark"
EV_TOO_BRIGHT: Final = "image_too_bright"
EV_TOO_BLURRY: Final = "image_too_blurry"
EV_SCENE_CHANGE: Final = "scene_change"
EV_AUDIO: Final = "audio"
EV_DIGITAL_INPUT: Final = "digital_input"
EV_RELAY: Final = "relay"
EV_STORAGE: Final = "storage_failure"
EV_OTHER: Final = "other"

EVENT_KINDS: Final = [
    EV_MOTION,
    EV_PERSON,
    EV_VEHICLE,
    EV_PET,
    EV_FACE,
    EV_LINE,
    EV_INTRUSION,
    EV_REGION_ENTER,
    EV_REGION_EXIT,
    EV_LOITERING,
    EV_TAMPER,
    EV_TOO_DARK,
    EV_TOO_BRIGHT,
    EV_TOO_BLURRY,
    EV_SCENE_CHANGE,
    EV_AUDIO,
    EV_DIGITAL_INPUT,
    EV_RELAY,
    EV_STORAGE,
    EV_OTHER,
]

EVENT_LABELS: Final = {
    EV_MOTION: "Motion",
    EV_PERSON: "Person",
    EV_VEHICLE: "Vehicle",
    EV_PET: "Pet",
    EV_FACE: "Face",
    EV_LINE: "Line crossing",
    EV_INTRUSION: "Intrusion",
    EV_REGION_ENTER: "Region entrance",
    EV_REGION_EXIT: "Region exit",
    EV_LOITERING: "Loitering",
    EV_TAMPER: "Tamper",
    EV_TOO_DARK: "Image too dark",
    EV_TOO_BRIGHT: "Image too bright",
    EV_TOO_BLURRY: "Image too blurry",
    EV_SCENE_CHANGE: "Scene change",
    EV_AUDIO: "Audio",
    EV_DIGITAL_INPUT: "Digital input",
    EV_RELAY: "Relay",
    EV_STORAGE: "Storage failure",
    EV_OTHER: "Other event",
}

# Detection-style events that make sense for snapshots and alerts.
DETECTION_KINDS: Final = [
    EV_MOTION,
    EV_PERSON,
    EV_VEHICLE,
    EV_PET,
    EV_FACE,
    EV_LINE,
    EV_INTRUSION,
    EV_REGION_ENTER,
    EV_REGION_EXIT,
    EV_LOITERING,
    EV_TAMPER,
    EV_AUDIO,
    EV_DIGITAL_INPUT,
]
DEFAULT_SNAPSHOT_EVENTS: Final = [EV_MOTION, EV_PERSON, EV_VEHICLE, EV_LINE, EV_INTRUSION]
DEFAULT_ALERT_EVENTS: Final = [EV_PERSON, EV_VEHICLE, EV_LINE, EV_INTRUSION]

# Bus event fired for every state change, for automations.
BUS_EVENT: Final = f"{DOMAIN}_event"
BUS_EVENT_SNAPSHOT: Final = f"{DOMAIN}_snapshot"

# Dispatcher signals (formatted with entry_id)
SIGNAL_NEW_EVENT: Final = f"{DOMAIN}_new_event_{{}}"
SIGNAL_UPDATE: Final = f"{DOMAIN}_update_{{}}"

PULLPOINT_TIMEOUT: Final = timedelta(seconds=30)
SUBSCRIPTION_INTERVAL: Final = timedelta(minutes=10)
RETRY_DELAY: Final = 60
SNAPSHOT_DIR: Final = DOMAIN
STORAGE_VERSION: Final = 1

SERVICE_SNAPSHOT: Final = "take_snapshot"
SERVICE_SEND_ALERT: Final = "send_alert"
ATTR_MESSAGE: Final = "message"
ATTR_ATTACH_SNAPSHOT: Final = "attach_snapshot"
ATTR_CHANNELS: Final = "channels"
