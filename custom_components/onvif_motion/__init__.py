"""ONVIF Motion & Snapshot – camera, events, latest snapshot and alerts."""
from __future__ import annotations

import logging

import voluptuous as vol

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_DEVICE_ID, Platform
from homeassistant.core import HomeAssistant, ServiceCall, ServiceResponse, SupportsResponse
from homeassistant.exceptions import (
    ConfigEntryAuthFailed,
    ConfigEntryNotReady,
    ServiceValidationError,
)
from homeassistant.helpers import config_validation as cv, device_registry as dr

from .const import (
    ATTR_ATTACH_SNAPSHOT,
    ATTR_CHANNELS,
    ATTR_MESSAGE,
    DOMAIN,
    SERVICE_SEND_ALERT,
    SERVICE_SNAPSHOT,
)
from .hub import CannotConnect, InvalidAuth, OnvifHub

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [
    Platform.BINARY_SENSOR,
    Platform.BUTTON,
    Platform.CAMERA,
    Platform.IMAGE,
    Platform.SENSOR,
    Platform.SWITCH,
]

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)

type OnvifMotionConfigEntry = ConfigEntry[OnvifHub]

SNAPSHOT_SCHEMA = vol.Schema({vol.Required(ATTR_DEVICE_ID): vol.All(cv.ensure_list, [cv.string])})
ALERT_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_DEVICE_ID): vol.All(cv.ensure_list, [cv.string]),
        vol.Optional(ATTR_MESSAGE): cv.string,
        vol.Optional(ATTR_ATTACH_SNAPSHOT, default=True): cv.boolean,
        vol.Optional(ATTR_CHANNELS, default=["telegram", "whatsapp"]): vol.All(
            cv.ensure_list, [vol.In(["telegram", "whatsapp"])]
        ),
    }
)


async def async_setup(hass: HomeAssistant, config: dict) -> bool:
    """Register services once."""

    def _hubs(call: ServiceCall) -> list[OnvifHub]:
        registry = dr.async_get(hass)
        hubs: list[OnvifHub] = []
        for device_id in call.data[ATTR_DEVICE_ID]:
            device = registry.async_get(device_id)
            if device is None:
                raise ServiceValidationError(f"Unknown device {device_id}")
            for entry_id in device.config_entries:
                entry = hass.config_entries.async_get_entry(entry_id)
                if entry and entry.domain == DOMAIN and hasattr(entry, "runtime_data"):
                    hubs.append(entry.runtime_data)
        if not hubs:
            raise ServiceValidationError("No ONVIF Motion camera found for that device")
        return hubs

    async def take_snapshot(call: ServiceCall) -> ServiceResponse:
        results = {}
        for hub in _hubs(call):
            await hub.async_take_snapshot("manual")
            results[hub.name] = {"path": hub.snapshot.path}
        return results

    async def send_alert(call: ServiceCall) -> None:
        for hub in _hubs(call):
            message = call.data.get(ATTR_MESSAGE) or hub.format_message(
                hub.last_event.event.kind if hub.last_event else "motion"
            )
            image = None
            if call.data[ATTR_ATTACH_SNAPSHOT]:
                image = await hub.async_take_snapshot("alert")
            await hub.async_send_alert(message, image, call.data[ATTR_CHANNELS])

    hass.services.async_register(
        DOMAIN,
        SERVICE_SNAPSHOT,
        take_snapshot,
        schema=SNAPSHOT_SCHEMA,
        supports_response=SupportsResponse.OPTIONAL,
    )
    hass.services.async_register(DOMAIN, SERVICE_SEND_ALERT, send_alert, schema=ALERT_SCHEMA)
    return True


async def async_setup_entry(hass: HomeAssistant, entry: OnvifMotionConfigEntry) -> bool:
    """Connect to the camera and set up entities."""
    hub = OnvifHub(hass, entry)
    try:
        await hub.async_setup()
    except InvalidAuth as err:
        raise ConfigEntryAuthFailed(str(err)) from err
    except CannotConnect as err:
        raise ConfigEntryNotReady(f"Cannot reach {hub.name}: {err}") from err

    entry.runtime_data = hub
    # Options (snapshot rules, Telegram, WhatsApp) are read live by the hub,
    # so changing them needs no reload.
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: OnvifMotionConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        await entry.runtime_data.async_shutdown()
    return unloaded
