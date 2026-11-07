"""Tests for ONVIF event parsing (no Home Assistant needed)."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import types

ROOT = Path(__file__).resolve().parents[1] / "custom_components" / "onvif_motion"


def _load(name: str):
    spec = importlib.util.spec_from_file_location(f"onvif_motion.{name}", ROOT / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[f"onvif_motion.{name}"] = module
    spec.loader.exec_module(module)
    return module


# Load const + parsers standalone, without importing the HA package __init__.
sys.modules.setdefault("onvif_motion", types.ModuleType("onvif_motion"))
sys.modules["onvif_motion"].__path__ = [str(ROOT)]
const = _load("const")
parsers = _load("parsers")


def msg(topic, data, source=None, operation="Changed"):
    """Build a message shaped like onvif-zeep-async's NotificationMessage."""
    return {
        "Topic": {"_value_1": topic},
        "Message": {
            "_value_1": {
                "PropertyOperation": operation,
                "Source": {"SimpleItem": [{"Name": k, "Value": v} for k, v in (source or {}).items()]},
                "Data": {"SimpleItem": [{"Name": k, "Value": v} for k, v in data.items()]},
            }
        },
    }


def test_cell_motion():
    ev = parsers.parse_message(
        msg(
            "tns1:RuleEngine/CellMotionDetector/Motion",
            {"IsMotion": "true"},
            {"VideoSourceConfigurationToken": "vsconf", "Rule": "MyMotionDetectorRule"},
        )
    )
    assert ev.kind == const.EV_MOTION
    assert ev.active is True
    assert ev.name == "Motion"
    assert not ev.momentary


def test_motion_alarm_off():
    ev = parsers.parse_message(msg("tns1:VideoSource/MotionAlarm", {"State": "false"}))
    assert ev.kind == const.EV_MOTION
    assert ev.active is False


def test_tplink_people_and_vehicle():
    people = parsers.parse_message(
        msg("tns1:RuleEngine/PeopleDetector/People", {"IsPeople": "true"})
    )
    vehicle = parsers.parse_message(
        msg("tns1:RuleEngine/TPSmartEventDetector/TPSmartEvent", {"IsVehicle": "1"})
    )
    assert people.kind == const.EV_PERSON
    assert vehicle.kind == const.EV_VEHICLE
    assert vehicle.active


def test_line_crossing_is_momentary():
    ev = parsers.parse_message(
        msg(
            "tns1:RuleEngine/LineDetector/Crossed",
            {"ObjectId": "15"},
            {"Rule": "Line1"},
        )
    )
    assert ev.kind == const.EV_LINE
    assert ev.momentary and ev.active
    assert ev.name == "Line crossing Line1"


def test_initialized_momentary_ignored():
    assert (
        parsers.parse_message(
            msg("tns1:RuleEngine/LineDetector/Crossed", {"ObjectId": "1"}, operation="Initialized")
        )
        is None
    )


def test_field_detector_intrusion():
    ev = parsers.parse_message(
        msg("tns1:RuleEngine/FieldDetector/ObjectsInside", {"IsInside": "true"}, {"Rule": "Zone1"})
    )
    assert ev.kind == const.EV_INTRUSION


def test_tamper_and_too_dark():
    tamper = parsers.parse_message(msg("tns1:RuleEngine/TamperDetector/Tamper", {"IsTamper": "true"}))
    dark = parsers.parse_message(msg("tns1:VideoSource/ImageTooDark/AnalyticsService", {"State": "true"}))
    assert tamper.kind == const.EV_TAMPER
    assert dark.kind == const.EV_TOO_DARK


def test_initialized_flag():
    ev = parsers.parse_message(
        msg("tns1:RuleEngine/CellMotionDetector/Motion", {"IsMotion": "false"}, operation="Initialized")
    )
    assert ev.is_initial


def test_unknown_topic_becomes_other():
    ev = parsers.parse_message(msg("tns1:Vendor/SomethingNew/WeirdThing", {"State": "true"}))
    assert ev.kind == const.EV_OTHER
    assert ev.name == "Weird thing"


def test_ignored_and_bad_messages():
    assert parsers.parse_message(msg("tns1:Monitoring/ProcessorUsage", {"Value": "12"})) is None
    assert parsers.parse_messages([None, {"Topic": None}]) == []


def test_unique_ids_differ_per_rule():
    a = parsers.parse_message(msg("tns1:RuleEngine/LineDetector/Crossed", {"ObjectId": "1"}, {"Rule": "A"}))
    b = parsers.parse_message(msg("tns1:RuleEngine/LineDetector/Crossed", {"ObjectId": "1"}, {"Rule": "B"}))
    assert a.uid != b.uid
