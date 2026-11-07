"""Turn raw ONVIF notification messages into simple, typed events.

Kept free of Home Assistant imports so it can be unit tested on its own.
Works with zeep objects as returned by onvif-zeep-async and with plain
dicts / SimpleNamespace objects shaped the same way.
"""
from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

from .const import (
    EV_AUDIO,
    EV_DIGITAL_INPUT,
    EV_FACE,
    EV_INTRUSION,
    EV_LINE,
    EV_LOITERING,
    EV_MOTION,
    EV_OTHER,
    EV_PERSON,
    EV_PET,
    EV_REGION_ENTER,
    EV_REGION_EXIT,
    EV_RELAY,
    EV_SCENE_CHANGE,
    EV_STORAGE,
    EV_TAMPER,
    EV_TOO_BLURRY,
    EV_TOO_BRIGHT,
    EV_TOO_DARK,
    EV_VEHICLE,
    EVENT_LABELS,
)

TRUE_VALUES = {"true", "1", "on", "active", "yes", "open", "detected", "alarm"}
FALSE_VALUES = {"false", "0", "off", "inactive", "no", "closed", "normal", "idle"}

# Ordered: the first matching rule wins, so specific detectors go before
# the generic "motion" catch-all. Matched against the lower-cased topic plus
# the names of the message's data items (e.g. "IsPeople", "IsVehicle").
_KIND_RULES: list[tuple[str, tuple[str, ...]]] = [
    (EV_TAMPER, ("tamper", "videoloss", "signalloss", "cameraocclu", "shelter")),
    (EV_TOO_DARK, ("imagetoodark", "toodark")),
    (EV_TOO_BRIGHT, ("imagetoobright", "toobright")),
    (EV_TOO_BLURRY, ("imagetooblurry", "tooblurry", "defocus")),
    (EV_SCENE_CHANGE, ("globalscenechange", "scenechange")),
    (EV_LINE, ("linedetector", "linecross", "linecrossing", "tripwire", "iscrossed", "crossed")),
    (EV_REGION_ENTER, ("regionentrance", "fieldenter", "enterregion")),
    (EV_REGION_EXIT, ("regionexit", "regionexiting", "leaveregion", "fieldexit")),
    (EV_LOITERING, ("loiter",)),
    (EV_FACE, ("face",)),
    (EV_PERSON, ("people", "person", "human", "body", "pedestrian")),
    (EV_VEHICLE, ("vehicle", "iscar", "/car", "motorvehicle", "nonmotor")),
    (EV_PET, ("pet", "animal", "isdog", "iscat")),
    (EV_INTRUSION, ("fielddetector", "intrusion", "isinside", "objectsinside", "regiondetect", "perimeter")),
    (EV_AUDIO, ("audio", "sound", "decibel", "babycry")),
    (EV_DIGITAL_INPUT, ("digitalinput", "logicalstate", "alarmin")),
    (EV_RELAY, ("relay",)),
    (EV_STORAGE, ("storagefailure", "hardwarefailure", "hddfull", "sdcard", "diskfull")),
    (EV_MOTION, ("motion", "ismotion", "cellmotion", "movement")),
]

# Topics that are plain device information, not events worth a sensor.
_IGNORED_TOPIC_PARTS = (
    "monitoring/processorusage",
    "monitoring/operatingtime",
    "monitoring/backup",
    "device/hardwarefailure/temperature/",
    "videosourceconfiguration",
    "profile",
    "recordingconfig",
    "mediaconfiguration",
)


@dataclass(slots=True)
class ParsedEvent:
    """One logical ONVIF event state."""

    uid: str
    kind: str
    name: str
    topic: str
    source: str | None
    active: bool
    momentary: bool
    operation: str | None
    data: dict[str, str]

    @property
    def is_initial(self) -> bool:
        """True for the state the camera reports when we subscribe."""
        return (self.operation or "").lower() == "initialized"


def _get(obj: Any, name: str, default: Any = None) -> Any:
    if obj is None:
        return default
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _as_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, (list, tuple)):
        return list(value)
    return [value]


def _simple_items(container: Any) -> dict[str, str]:
    items: dict[str, str] = {}
    for item in _as_list(_get(container, "SimpleItem")):
        name = _get(item, "Name")
        if name is None:
            continue
        value = _get(item, "Value")
        items[str(name)] = "" if value is None else str(value)
    return items


def topic_of(message: Any) -> str:
    """Return the clean topic string of a notification message."""
    topic = _get(message, "Topic")
    raw = _get(topic, "_value_1", topic)
    if raw is None:
        return ""
    text = str(raw).strip().rstrip("/.")
    # Drop namespace prefixes such as "tns1:" / "tt:" on every segment.
    return "/".join(part.split(":", 1)[-1] for part in text.split("/"))


def classify(topic: str, data_names: list[str] | None = None) -> str:
    """Return the event kind for a topic (and its data item names)."""
    haystack = topic.lower() + " " + " ".join(n.lower() for n in data_names or [])
    compact = haystack.replace("_", "").replace("-", "")
    for kind, needles in _KIND_RULES:
        if any(needle in compact for needle in needles):
            return kind
    return EV_OTHER


def _to_bool(value: str) -> bool | None:
    low = value.strip().lower()
    if low in TRUE_VALUES:
        return True
    if low in FALSE_VALUES:
        return False
    return None


def _humanise(segment: str) -> str:
    segment = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", segment)
    return segment.replace("_", " ").strip().capitalize()


def parse_message(message: Any) -> ParsedEvent | None:
    """Parse one NotificationMessage. Returns None for messages to ignore."""
    topic = topic_of(message)
    if not topic:
        return None
    low_topic = topic.lower()
    if any(part in low_topic for part in _IGNORED_TOPIC_PARTS):
        return None

    payload = _get(_get(message, "Message"), "_value_1", _get(message, "Message"))
    if payload is None:
        return None

    source_items = _simple_items(_get(payload, "Source"))
    data_items = _simple_items(_get(payload, "Data"))
    operation = _get(payload, "PropertyOperation")
    if operation is not None:
        operation = str(operation)

    kind = classify(topic, list(data_items))

    # Pick the data item that carries the state: prefer a boolean one.
    active: bool | None = None
    state_key: str | None = None
    for key, value in data_items.items():
        low_key = key.lower()
        if low_key.endswith("id") or "count" in low_key or "token" in low_key:
            continue  # e.g. ObjectId "1" is not an on/off state
        parsed = _to_bool(value)
        if parsed is not None:
            active, state_key = parsed, key
            # A per-kind flag (IsPeople, IsVehicle…) wins over a generic one.
            if classify("", [key]) == kind:
                break
    momentary = active is None
    if momentary:
        # e.g. LineDetector/Crossed carries an ObjectId, not a state.
        if (operation or "").lower() == "initialized":
            return None
        active = True

    # TP-Link and other "smart event" topics carry several Is* flags in one
    # message; split them so each kind gets its own sensor.
    rule = (
        source_items.get("Rule")
        or source_items.get("RuleName")
        or source_items.get("InputToken")
        or source_items.get("RelayToken")
    )
    source = (
        source_items.get("VideoSourceConfigurationToken")
        or source_items.get("VideoSourceToken")
        or source_items.get("Source")
    )
    uid_parts = [topic, state_key or "", rule or "", source or ""]
    uid = "|".join(uid_parts)

    if kind == EV_OTHER:
        name = _humanise(topic.split("/")[-1]) or "Event"
    else:
        name = EVENT_LABELS[kind]
    if rule and kind in (EV_DIGITAL_INPUT, EV_RELAY, EV_LINE, EV_INTRUSION, EV_OTHER):
        name = f"{name} {rule}"

    return ParsedEvent(
        uid=uid,
        kind=kind,
        name=name,
        topic=topic,
        source=rule or source,
        active=bool(active),
        momentary=momentary,
        operation=operation,
        data=data_items,
    )


def parse_messages(messages: Any) -> list[ParsedEvent]:
    """Parse a list of NotificationMessages, skipping unknown ones."""
    events: list[ParsedEvent] = []
    for message in _as_list(messages):
        try:
            event = parse_message(message)
        except (AttributeError, KeyError, TypeError, ValueError):
            event = None
        if event is not None:
            events.append(event)
    return events
