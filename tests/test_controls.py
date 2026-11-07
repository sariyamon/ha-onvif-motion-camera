"""Camera controls: ONVIF PTZ and TP-Link VIGI settings."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant.core import HomeAssistant

from custom_components.onvif_motion.vigi import VigiCoordinator

from .test_integration import _setup

VIGI_DATA = {
    "device_info": {"model": "C540V"},
    "motion": {"enabled": "on", "digital_sensitivity": "50", "people_enabled": "off"},
    "image_switch": {"pre_night_vision_mode": "auto_ir", "night_vision_mode": "inf_night_vision",
                     "wtl_intensity_level": "2"},
    "alarm": {"enabled": "on", "light_alarm_enabled": "on", "sound_alarm_enabled": "off",
              "sound_alarm_times": "3"},
    "led": {"enabled": "on"},
    "speaker": {"volume": "60", "mute": "off"},
    "target_track": {"enabled": "off"},
    "presets": [{"id": "1", "name": "Gate view"}, {"id": "2", "name": "Road"}],
}


def _vigi(hass, entry_holder):
    api = MagicMock()
    api.set = AsyncMock()
    api.goto_preset = AsyncMock()
    api.alarm = AsyncMock()
    api.close = AsyncMock()
    api.get_many = AsyncMock(return_value=VIGI_DATA)

    async def probe(hass_, entry):
        coordinator = VigiCoordinator(hass_, entry, api)
        coordinator.data = VIGI_DATA
        return coordinator

    return api, probe


async def test_vigi_controls(hass: HomeAssistant, fake_camera) -> None:
    api, probe = _vigi(hass, None)
    with patch("custom_components.onvif_motion.async_probe_vigi", probe):
        entry = await _setup(hass)

    # Only settings the camera reports become entities.
    assert hass.states.get("switch.gate_motion_detection").state == "on"
    assert hass.states.get("switch.gate_person_detection").state == "off"
    assert hass.states.get("switch.gate_vehicle_detection") is None
    assert hass.states.get("switch.gate_status_led").state == "on"
    assert hass.states.get("light.gate_spotlight").state == "off"
    assert hass.states.get("select.gate_night_vision").state == "Auto IR"
    assert hass.states.get("number.gate_speaker_volume").state == "60.0"
    assert hass.states.get("select.gate_preset_position").attributes["options"] == ["Gate view", "Road"]

    await hass.services.async_call("switch", "turn_on", {"entity_id": "switch.gate_person_detection"}, blocking=True)
    api.set.assert_awaited_with("motion_detection", "motion_det", {"people_enabled": "on"})

    await hass.services.async_call("light", "turn_on", {"entity_id": "light.gate_spotlight", "brightness": 255}, blocking=True)
    api.set.assert_any_await("image", "switch", {"pre_night_vision_mode": "white_led_always_on"})
    api.set.assert_any_await("image", "switch", {"wtl_intensity_level": 4})

    await hass.services.async_call("select", "select_option", {"entity_id": "select.gate_night_vision", "option": "IR always on"}, blocking=True)
    api.set.assert_awaited_with("image", "switch", {"pre_night_vision_mode": "ir_always_on"})

    await hass.services.async_call("number", "set_value", {"entity_id": "number.gate_alarm_sound_repeats", "value": 5}, blocking=True)
    api.set.assert_awaited_with("msg_alarm", "chn1_msg_alarm_info", {"sound_alarm_times": "5"})

    await hass.services.async_call("select", "select_option", {"entity_id": "select.gate_preset_position", "option": "Road"}, blocking=True)
    api.goto_preset.assert_awaited_with("2")

    await hass.services.async_call("button", "press", {"entity_id": "button.gate_sound_alarm"}, blocking=True)
    api.alarm.assert_awaited_with(True)

    assert await hass.config_entries.async_unload(entry.entry_id)
    api.close.assert_awaited()


async def test_onvif_ptz_buttons(hass: HomeAssistant, fake_camera) -> None:
    media = await fake_camera.create_media_service()
    media.GetProfiles.return_value[0].PTZConfiguration = SimpleNamespace(token="ptz")
    ptz = MagicMock()
    ptz.GetPresets = AsyncMock(return_value=[SimpleNamespace(token="p1", Name="Home")])
    ptz.ContinuousMove = AsyncMock()
    ptz.Stop = AsyncMock()
    ptz.GotoPreset = AsyncMock()
    fake_camera.create_ptz_service = AsyncMock(return_value=ptz)

    entry = await _setup(hass)
    with patch("custom_components.onvif_motion.ptz.MOVE_SECONDS", 0):
        await hass.services.async_call("button", "press", {"entity_id": "button.gate_pan_left"}, blocking=True)
    call = ptz.ContinuousMove.await_args.args[0]
    assert call["ProfileToken"] == "profile_1"
    assert call["Velocity"] == {"PanTilt": {"x": -0.3, "y": 0.0}}

    await hass.services.async_call("select", "select_option", {"entity_id": "select.gate_preset_position", "option": "Home"}, blocking=True)
    ptz.GotoPreset.assert_awaited_with({"ProfileToken": "profile_1", "PresetToken": "p1"})
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_telegram_via_home_assistant_bot(hass: HomeAssistant, fake_camera) -> None:
    calls = []

    async def send_photo(call):
        calls.append(dict(call.data))

    hass.services.async_register("telegram_bot", "send_photo", send_photo)
    entry = await _setup(hass, {"telegram_notify_entities": ["notify.telegram_bot_1"]})
    hub = entry.runtime_data
    image = await hub.async_take_snapshot("person")
    await hub.async_send_alert("Person at Gate", image, ["telegram"])
    assert calls[0]["entity_id"] == ["notify.telegram_bot_1"]
    assert calls[0]["file"] == hub.snapshot.path
    assert hub.snapshot.path.startswith(hass.config.media_dirs.get("local") or hass.config.path("media"))
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_vigi_push_events(hass: HomeAssistant, fake_camera) -> None:
    """Detections from the VIGI push stream behave like ONVIF ones."""
    from custom_components.onvif_motion.vigi_events import push_event

    entry = await _setup(hass)
    hub = entry.runtime_data
    hub.push_connected(True)
    hub.process_push_event(push_event("PeopleDetection", "Gate area"))
    await hass.async_block_till_done()

    state = hass.states.get("binary_sensor.gate_person")
    assert state is not None and state.state == "on"
    assert state.attributes["source"] == "Gate area"
    assert hass.states.get("sensor.gate_last_detection_type").state == "person"
    assert hub.trigger_count == 1 and hub.snapshot.path is not None
    assert hass.states.get("binary_sensor.gate_event_subscription").state == "on"

    assert push_event("CrossLineDetection", None).kind == "line_crossing"
    assert push_event("DropAndTakeDetection", None).name == "Object left / taken"
    assert await hass.config_entries.async_unload(entry.entry_id)
