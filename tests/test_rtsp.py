"""RTSP-only connection type."""
from __future__ import annotations

from unittest.mock import AsyncMock, patch

from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_PORT, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.onvif_motion.const import DOMAIN

from .test_integration import _setup

RTSP = {
    "name": "Garage",
    "stream_url": "rtsp://192.168.31.120:554/live/ch0",
    CONF_USERNAME: "admin",
    CONF_PASSWORD: "p@ss",
    "rtsp_transport": "tcp",
}
GRAB = "homeassistant.components.ffmpeg.async_get_image"


async def test_add_rtsp_camera(hass: HomeAssistant, fake_camera) -> None:
    with patch(GRAB, AsyncMock(return_value=b"jpeg")) as grab:
        result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {"next_step_id": "rtsp"})
        assert result["step_id"] == "rtsp"
        result = await hass.config_entries.flow.async_configure(result["flow_id"], RTSP)
        assert result["type"] is FlowResultType.CREATE_ENTRY
        # Login is put into the address, URL-encoded.
        assert grab.call_args.args[1] == "rtsp://admin:p%40ss@192.168.31.120:554/live/ch0"
        await hass.async_block_till_done()

    entry = result["result"]
    assert entry.data["connection_type"] == "rtsp"
    assert entry.data[CONF_HOST] == "192.168.31.120"
    hub = entry.runtime_data
    assert not hub.is_onvif and hub.camera is None
    fake_camera.update_xaddrs.assert_not_called()  # no ONVIF at all
    assert hass.states.get("camera.garage") is not None
    assert hass.states.get("button.garage_restart") is None
    assert hass.states.get("binary_sensor.garage_event_subscription") is None

    with patch(GRAB, AsyncMock(return_value=b"frame")):
        assert await hub.async_take_snapshot("manual") == b"frame"
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_rtsp_bad_address(hass: HomeAssistant, fake_camera) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": config_entries.SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"next_step_id": "rtsp"})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {**RTSP, "stream_url": "http://x"})
    assert result["errors"] == {"stream_url": "not_rtsp"}
    with patch(GRAB, AsyncMock(return_value=None)):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], RTSP)
    assert result["errors"] == {"base": "cannot_connect_rtsp"}


async def test_switch_onvif_camera_to_rtsp_and_back(hass: HomeAssistant, fake_camera) -> None:
    entry = await _setup(hass)
    with patch(GRAB, AsyncMock(return_value=b"jpeg")):
        result = await hass.config_entries.options.async_init(entry.entry_id)
        result = await hass.config_entries.options.async_configure(result["flow_id"], {"next_step_id": "connection"})
        result = await hass.config_entries.options.async_configure(
            result["flow_id"],
            {"connection_type": "rtsp", CONF_USERNAME: "admin", "rtsp_transport": "tcp", "stream_url": ""},
        )
        assert result["errors"] == {"stream_url": "needs_stream_url"}
        result = await hass.config_entries.options.async_configure(
            result["flow_id"],
            {"connection_type": "rtsp", CONF_USERNAME: "admin", "rtsp_transport": "tcp",
             "stream_url": "rtsp://192.168.31.101:554/stream1"},
        )
        result = await hass.config_entries.options.async_configure(result["flow_id"], {"next_step_id": "save"})
        await hass.async_block_till_done()
    assert entry.data["connection_type"] == "rtsp"
    assert not entry.runtime_data.is_onvif

    # And back to ONVIF.
    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"next_step_id": "connection"})
    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {"connection_type": "onvif", CONF_HOST: "192.168.31.101", CONF_PORT: 2020, "protocol": "http",
         CONF_USERNAME: "admin", "rtsp_transport": "tcp", "stream_url": ""},
    )
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"next_step_id": "save"})
    await hass.async_block_till_done()
    assert entry.data["connection_type"] == "onvif"
    assert entry.runtime_data.is_onvif and entry.runtime_data.camera is not None
    assert await hass.config_entries.async_unload(entry.entry_id)


async def test_existing_entries_default_to_onvif(hass: HomeAssistant, fake_camera) -> None:
    """Cameras added before this option keep working as ONVIF."""
    entry = await _setup(hass)
    assert "connection_type" not in entry.data
    assert entry.runtime_data.is_onvif
    assert isinstance(entry, MockConfigEntry)
    assert await hass.config_entries.async_unload(entry.entry_id)
