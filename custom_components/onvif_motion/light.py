"""Spotlight (white light) of TP-Link VIGI cameras."""
from __future__ import annotations

import math
from typing import Any

from homeassistant.components.light import ATTR_BRIGHTNESS, ColorMode, LightEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import OnvifMotionConfigEntry
from .entity import VigiEntity
from .hub import OnvifHub
from .vigi_api import SPOTLIGHT_OFF, SPOTLIGHT_ON


async def async_setup_entry(
    hass: HomeAssistant,
    entry: OnvifMotionConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    hub = entry.runtime_data
    if hub.vigi and "wtl_intensity_level" in (hub.vigi.data or {}).get("image_switch", {}):
        async_add_entities([VigiSpotlight(hub)])


class VigiSpotlight(VigiEntity, LightEntity):
    """On = white light, off = back to infrared. Brightness maps to levels 1–4."""

    _attr_translation_key = "spotlight"
    _attr_icon = "mdi:spotlight-beam"
    _attr_color_mode = ColorMode.BRIGHTNESS
    _attr_supported_color_modes = {ColorMode.BRIGHTNESS}

    def __init__(self, hub: OnvifHub) -> None:
        super().__init__(hub, "vigi_spotlight")

    @property
    def _switch(self) -> dict:
        return self.data.get("image_switch", {})

    @property
    def is_on(self) -> bool:
        return self._switch.get("night_vision_mode") == SPOTLIGHT_ON[0]

    @property
    def brightness(self) -> int:
        try:
            level = int(self._switch.get("wtl_intensity_level", 4))
        except (TypeError, ValueError):
            return 255
        return round((level - 1) / 3 * 254) + 1

    async def _mode(self, modes: tuple[str, str]) -> None:
        field = "pre_night_vision_mode" if "pre_night_vision_mode" in self._switch else "night_vision_mode"
        value = modes[1] if field == "pre_night_vision_mode" else modes[0]
        await self.coordinator.api.set("image", "switch", {field: value})

    async def async_turn_on(self, **kwargs: Any) -> None:
        async def _on() -> None:
            await self._mode(SPOTLIGHT_ON)
            if (brightness := kwargs.get(ATTR_BRIGHTNESS)) is not None:
                level = max(1, min(4, math.ceil(brightness / 255 * 4)))
                await self.coordinator.api.set("image", "switch", {"wtl_intensity_level": level})

        await self.coordinator.async_write(_on())

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self.coordinator.async_write(self._mode(SPOTLIGHT_OFF))
