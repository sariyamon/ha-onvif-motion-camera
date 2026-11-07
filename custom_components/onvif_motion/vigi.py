"""Polls TP-Link VIGI camera settings so they can be shown and changed."""
from __future__ import annotations

from datetime import timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .vigi_api import VigiCamera, VigiError

_LOGGER = logging.getLogger(__name__)
_KEYS = ["device_info", "motion", "image_switch", "alarm", "led", "speaker",
         "microphone", "tamper", "target_track", "presets"]


class VigiCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Settings of one VIGI camera, refreshed every 30 s."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, api: VigiCamera) -> None:
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=f"VIGI controls {entry.title}",
            update_interval=timedelta(seconds=30),
        )
        self.api = api

    async def _async_update_data(self) -> dict[str, Any]:
        try:
            return await self.api.get_many(_KEYS)
        except VigiError as err:
            raise UpdateFailed(str(err)) from err

    async def async_write(self, coro) -> None:
        """Run a setter, then refresh so the entity shows the camera's real state."""
        try:
            await coro
        except VigiError as err:
            raise HomeAssistantError(f"Camera refused the change: {err}") from err
        finally:
            await self.async_request_refresh()


async def async_probe_vigi(hass: HomeAssistant, entry: ConfigEntry) -> VigiCoordinator | None:
    """Return a coordinator if the camera speaks the VIGI API, else None."""
    host = entry.data[CONF_HOST].removeprefix("https://").removeprefix("http://").split("/")[0]
    api = VigiCamera(host, entry.data[CONF_USERNAME], entry.data[CONF_PASSWORD])
    coordinator = VigiCoordinator(hass, entry, api)
    try:
        coordinator.data = await api.get_many(_KEYS)
    except VigiError as err:
        _LOGGER.debug("%s: no VIGI controls (%s)", host, err)
        await api.close()
        return None
    coordinator.last_update_success = True
    return coordinator
