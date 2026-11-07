"""Selects: night vision mode (VIGI) and PTZ preset (VIGI or ONVIF)."""
from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import OnvifMotionConfigEntry
from .entity import OnvifMotionEntity, VigiEntity
from .hub import OnvifHub
from .vigi_api import NIGHT_VISION_MODES, PRE_NIGHT_VISION_MODES, WHITE_LED_MODES


async def async_setup_entry(
    hass: HomeAssistant,
    entry: OnvifMotionConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    hub = entry.runtime_data
    entities: list[SelectEntity] = []
    data = (hub.vigi.data or {}) if hub.vigi else {}
    switch = data.get("image_switch", {})
    if "pre_night_vision_mode" in switch or "night_vision_mode" in switch:
        entities.append(NightVisionSelect(hub))
    if hub.vigi and data.get("presets"):
        entities.append(VigiPresetSelect(hub))
    elif hub.ptz and hub.ptz.presets:
        entities.append(OnvifPresetSelect(hub))
    async_add_entities(entities)


class NightVisionSelect(VigiEntity, SelectEntity):
    """IR / colour / spotlight behaviour at night."""

    _attr_translation_key = "night_vision"
    _attr_icon = "mdi:weather-night"

    def __init__(self, hub: OnvifHub) -> None:
        super().__init__(hub, "vigi_night_vision")

    @property
    def _switch(self) -> dict:
        return self.data.get("image_switch", {})

    @property
    def _field(self) -> str:
        return "pre_night_vision_mode" if "pre_night_vision_mode" in self._switch else "night_vision_mode"

    @property
    def _modes(self) -> dict[str, str]:
        if self._field == "night_vision_mode":
            return dict(NIGHT_VISION_MODES)
        modes = dict(PRE_NIGHT_VISION_MODES)
        if "wtl_intensity_level" not in self._switch:  # no white LED on this model
            for key in WHITE_LED_MODES:
                modes.pop(key, None)
        current = self._switch.get(self._field)
        if current in PRE_NIGHT_VISION_MODES:
            modes.setdefault(current, PRE_NIGHT_VISION_MODES[current])
        return modes

    @property
    def options(self) -> list[str]:
        return list(self._modes.values())

    @property
    def current_option(self) -> str | None:
        return self._modes.get(self._switch.get(self._field))

    async def async_select_option(self, option: str) -> None:
        mode = next((k for k, v in self._modes.items() if v == option), None)
        if mode is None:
            raise HomeAssistantError(f"Unknown night vision mode {option}")
        await self.coordinator.async_write(
            self.coordinator.api.set("image", "switch", {self._field: mode})
        )


class _PresetSelect(SelectEntity):
    _attr_translation_key = "ptz_preset"
    _attr_icon = "mdi:camera-marker"
    _last: str | None = None

    def _presets(self) -> list[dict[str, str]]:
        raise NotImplementedError

    @property
    def options(self) -> list[str]:
        return [p["name"] for p in self._presets()]

    @property
    def current_option(self) -> str | None:
        return self._last

    def _preset_id(self, option: str) -> str:
        for preset in self._presets():
            if preset["name"] == option:
                return preset["id"]
        raise HomeAssistantError(f"Unknown preset {option}")


class VigiPresetSelect(VigiEntity, _PresetSelect):
    """Go to a saved camera position (presets saved in the VIGI app)."""

    def __init__(self, hub: OnvifHub) -> None:
        super().__init__(hub, "ptz_preset")

    def _presets(self) -> list[dict[str, str]]:
        return self.data.get("presets", [])

    async def async_select_option(self, option: str) -> None:
        await self.coordinator.async_write(self.coordinator.api.goto_preset(self._preset_id(option)))
        self._last = option
        self.async_write_ha_state()


class OnvifPresetSelect(OnvifMotionEntity, _PresetSelect):
    """Go to a saved camera position (ONVIF presets)."""

    def __init__(self, hub: OnvifHub) -> None:
        super().__init__(hub, "ptz_preset")

    def _presets(self) -> list[dict[str, str]]:
        return self.hub.ptz.presets if self.hub.ptz else []

    async def async_select_option(self, option: str) -> None:
        assert self.hub.ptz
        await self.hub.ptz.goto_preset(self._preset_id(option))
        self._last = option
        self.async_write_ha_state()
