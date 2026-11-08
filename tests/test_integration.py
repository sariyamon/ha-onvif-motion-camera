"""End-to-end tests with a faked camera."""
from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_NAME, CONF_PASSWORD, CONF_PORT, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry, async_capture_events

from custom_components.onvif_motion.const import (
    BUS_EVENT,
    CONF_PROFILE_TOKEN,
    CONF_PROTOCOL,
    CONF_RTSP_TRANSPORT,
    CONF_TELEGRAM_CHAT_IDS,
    CONF_TELEGRAM_TOKEN,
    DOMAIN,
)
from custom_components.onvif_motion.parsers import parse_message

from .conftest import JPEG

USER_INPUT = {
    CONF_NAME: "Gate",
    CONF_HOST: "192.168.31.101",
    CONF_PORT: 2020,
    CONF_PROTOCOL: "http",
    CONF_USERNAME: "admin",
    CONF_PASSWORD: "secret",
}


def _msg(topic, data, operation="Changed", source=None):
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


async def test_config_flow(hass: HomeAssistant, fake_camera) -> None:
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.MENU
    assert result["menu_options"] == ["onvif", "rtsp"]
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"next_step_id": "onvif"})
    assert result["type"] is FlowResultType.FORM
    result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "stream"
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_PROFILE_TOKEN: "profile_2", CONF_RTSP_TRANSPORT: "tcp"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Gate"
    assert result["result"].unique_id == "74:fe:ce:89:7d:d5"
    assert result["data"][CONF_PROFILE_TOKEN] == "profile_2"
    await hass.async_block_till_done()
    entry = result["result"]
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_config_flow_bad_auth(hass: HomeAssistant, fake_camera) -> None:
    from zeep.exceptions import Fault

    fake_camera.update_xaddrs.side_effect = Fault("Sender not Authorized")
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"next_step_id": "onvif"})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], USER_INPUT)
    assert result["errors"] == {"base": "invalid_auth"}


async def _setup(hass: HomeAssistant, options=None) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Gate",
        unique_id="74:fe:ce:89:7d:d5",
        data={**USER_INPUT, CONF_PROFILE_TOKEN: "profile_1", CONF_RTSP_TRANSPORT: "tcp"},
        options=options or {},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_entities_events_and_snapshot(hass: HomeAssistant, fake_camera) -> None:
    entry = await _setup(hass)
    hub = entry.runtime_data
    bus_events = async_capture_events(hass, BUS_EVENT)

    assert hass.states.get("camera.gate") is not None
    assert hass.states.get("switch.gate_telegram_alerts").state == "on"
    assert hass.states.get("sensor.gate_detections_today").state == "0"
    assert hub.stream_uri == "rtsp://admin:secret@192.168.31.101:554/stream1"

    # Camera reports a person -> new binary sensor, snapshot, bus event.
    hub.process_event(parse_message(_msg("tns1:RuleEngine/PeopleDetector/People", {"IsPeople": "true"})))
    hub._signal_update()
    await hass.async_block_till_done()

    person = hass.states.get("binary_sensor.gate_person")
    assert person is not None and person.state == "on"
    assert person.attributes["device_class"] == "occupancy"
    assert hass.states.get("sensor.gate_last_detection_type").state == "person"
    assert hass.states.get("sensor.gate_detections_today").state == "1"
    assert bus_events[-1].data["event"] == "person" and bus_events[-1].data["active"]

    assert hub.snapshot.path is not None
    assert hass.states.get("sensor.gate_last_snapshot_time").state not in ("unknown", "unavailable")
    assert await hub.async_read_snapshot() == JPEG
    assert hass.states.get("image.gate_last_snapshot").state != "unavailable"

    # Person leaves.
    hub.process_event(parse_message(_msg("tns1:RuleEngine/PeopleDetector/People", {"IsPeople": "false"})))
    hub._signal_update()
    await hass.async_block_till_done()
    assert hass.states.get("binary_sensor.gate_person").state == "off"
    assert bus_events[-1].data["active"] is False

    # Sensor survives a reload even though the camera has not re-sent it.
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    registry = er.async_get(hass)
    assert registry.async_get("binary_sensor.gate_person") is not None
    assert hass.states.get("binary_sensor.gate_person") is not None

    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_snapshots_switch_off(hass: HomeAssistant, fake_camera) -> None:
    entry = await _setup(hass)
    await hass.services.async_call(
        "switch", "turn_off", {"entity_id": "switch.gate_snapshots"}, blocking=True
    )
    hub = entry.runtime_data
    hub.process_event(parse_message(_msg("tns1:RuleEngine/CellMotionDetector/Motion", {"IsMotion": "true"})))
    await hass.async_block_till_done()
    assert hub.snapshot.path is None
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_initial_state_does_not_trigger(hass: HomeAssistant, fake_camera) -> None:
    entry = await _setup(hass)
    hub = entry.runtime_data
    hub._initial_until = hass.loop.time() + 10  # just subscribed
    hub.process_event(
        parse_message(
            _msg("tns1:RuleEngine/CellMotionDetector/Motion", {"IsMotion": "true"}, operation="Initialized")
        )
    )
    await hass.async_block_till_done()
    assert hub.snapshot.path is None
    assert hub.trigger_count == 0

    # TP-Link VIGI tags live events "Initialized" too: after the startup
    # window they must count as real detections.
    hub._initial_until = 0
    hub.process_event(
        parse_message(
            _msg("tns1:RuleEngine/CellMotionDetector/Motion", {"IsMotion": "false"}, operation="Initialized")
        )
    )
    hub.process_event(
        parse_message(
            _msg("tns1:RuleEngine/CellMotionDetector/Motion", {"IsMotion": "true"}, operation="Initialized")
        )
    )
    await hass.async_block_till_done()
    assert hub.trigger_count == 1
    assert hub.snapshot.path is not None
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_telegram_alert(hass: HomeAssistant, fake_camera, aioclient_mock) -> None:
    aioclient_mock.post(
        "https://api.telegram.org/bot123:ABC/sendPhoto", json={"ok": True}
    )
    entry = await _setup(
        hass, {CONF_TELEGRAM_TOKEN: "123:ABC", CONF_TELEGRAM_CHAT_IDS: "111, 222"}
    )
    hub = entry.runtime_data
    hub.process_event(parse_message(_msg("tns1:RuleEngine/TPSmartEventDetector/TPSmartEvent", {"IsVehicle": "true"})))
    await hass.async_block_till_done()
    assert aioclient_mock.call_count == 2  # one photo per chat

    # Cooldown: a second vehicle right away does not alert again.
    hub.process_event(parse_message(_msg("tns1:RuleEngine/TPSmartEventDetector/TPSmartEvent", {"IsVehicle": "false"})))
    hub.process_event(parse_message(_msg("tns1:RuleEngine/TPSmartEventDetector/TPSmartEvent", {"IsVehicle": "true"})))
    await hass.async_block_till_done()
    assert aioclient_mock.call_count == 2
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_take_snapshot_service(hass: HomeAssistant, fake_camera) -> None:
    entry = await _setup(hass)
    from homeassistant.helpers import device_registry as dr

    device = next(iter(dr.async_get(hass).devices.values()))
    result = await hass.services.async_call(
        DOMAIN, "take_snapshot", {"device_id": device.id}, blocking=True, return_response=True
    )
    assert result["Gate"]["path"].endswith("_manual.jpg")
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_options_flow(hass: HomeAssistant, fake_camera) -> None:
    entry = await _setup(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.MENU
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "telegram"}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_TELEGRAM_TOKEN: " 1:A ", CONF_TELEGRAM_CHAT_IDS: "42"}
    )
    assert result["type"] is FlowResultType.MENU
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "whatsapp"}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {"whatsapp_provider": "callmebot", "whatsapp_recipients": "+919876543210", "whatsapp_callmebot_apikey": "k"},
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "alerts"}
    )
    assert result["description_placeholders"]["camera"] == "{camera}"
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"alert_events": ["person"], "alert_cooldown": 30, "alert_message": "{event} at {camera}"}
    )
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"next_step_id": "save"}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert entry.options[CONF_TELEGRAM_TOKEN] == "1:A"
    assert entry.options["whatsapp_provider"] == "callmebot"
    assert entry.runtime_data.format_message("person") == "Person at Gate"
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_reconfigure(hass: HomeAssistant, fake_camera) -> None:
    entry = await _setup(hass)
    result = await entry.start_reconfigure_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**{k: v for k, v in USER_INPUT.items() if k != CONF_NAME}, CONF_HOST: "192.168.31.150"}
    )
    assert result["reason"] == "reconfigure_successful"
    assert entry.data[CONF_HOST] == "192.168.31.150"


async def test_snapshot_falls_back_to_stream(hass: HomeAssistant, fake_camera) -> None:
    """VIGI cameras have no ONVIF snapshot URL: grab a frame from RTSP."""
    from unittest.mock import AsyncMock, patch

    fake_camera.get_snapshot_uri = AsyncMock(return_value=None)
    entry = await _setup(hass)
    hub = entry.runtime_data
    with patch(
        "custom_components.onvif_motion.hub.ffmpeg.async_get_image",
        AsyncMock(return_value=b"frame"),
    ) as grab:
        assert await hub.async_take_snapshot("manual") == b"frame"
        assert grab.call_args.args[1] == "rtsp://admin:secret@192.168.31.101:554/stream1"
        await hub.async_take_snapshot("manual")
    fake_camera.get_snapshot.assert_not_called()
    assert fake_camera.get_snapshot_uri.call_count == 1  # remembered, not retried
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_options_connection(hass: HomeAssistant, fake_camera) -> None:
    """IP, login and RTSP can be changed from Configure."""
    entry = await _setup(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert "connection" in result["menu_options"]
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"next_step_id": "connection"})
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {
            CONF_HOST: "192.168.31.150",
            CONF_PORT: 2020,
            CONF_PROTOCOL: "http",
            CONF_USERNAME: "admin",
            CONF_RTSP_TRANSPORT: "udp",
            "stream_url": "rtsp://192.168.31.150:554/stream2",
        },
    )
    assert result["type"] is FlowResultType.MENU
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"next_step_id": "save"})
    await hass.async_block_till_done()
    assert entry.data[CONF_HOST] == "192.168.31.150"
    assert entry.data[CONF_PASSWORD] == "secret"  # blank kept the old one
    assert entry.data[CONF_RTSP_TRANSPORT] == "udp"
    assert entry.runtime_data.stream_uri == "rtsp://admin:secret@192.168.31.150:554/stream2"

    # A different camera at the new address is refused.
    devicemgmt = await fake_camera.create_devicemgmt_service()
    devicemgmt.GetNetworkInterfaces.return_value[0].Info.HwAddress = "11:22:33:44:55:66"
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"next_step_id": "connection"})
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {CONF_HOST: "192.168.31.99", CONF_PORT: 2020, CONF_PROTOCOL: "http", CONF_USERNAME: "admin", CONF_RTSP_TRANSPORT: "tcp"},
    )
    assert result["errors"] == {"base": "different_camera"}
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_mjpeg_live_view(hass: HomeAssistant, fake_camera) -> None:
    """The live view is served as MJPEG from the RTSP stream through ffmpeg."""
    await _setup(hass)
    camera = hass.data["entity_components"]["camera"].get_entity("camera.gate")
    stream = MagicMock()
    stream.open_camera = AsyncMock()
    stream.get_reader = AsyncMock(return_value="reader")
    stream.close = AsyncMock()
    with patch("custom_components.onvif_motion.camera.CameraMjpeg", return_value=stream), patch(
        "custom_components.onvif_motion.camera.async_aiohttp_proxy_stream",
        AsyncMock(return_value="response"),
    ) as proxy:
        assert await camera.handle_async_mjpeg_stream(MagicMock()) == "response"
    stream.open_camera.assert_awaited_once()
    assert stream.open_camera.call_args.args[0] == "rtsp://admin:secret@192.168.31.101:554/stream1"
    assert proxy.call_args.args[2] == "reader"
    stream.close.assert_awaited_once()
