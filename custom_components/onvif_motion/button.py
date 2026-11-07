"""Buttons: take a snapshot, send a test alert, reboot the camera."""
from __future__ import annotations

from homeassistant.components.button import ButtonDeviceClass, ButtonEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import OnvifMotionConfigEntry
from .entity import OnvifMotionEntity, VigiEntity
from .hub import OnvifHub
from .ptz import DEFAULT_SPEED


async def async_setup_entry(
    hass: HomeAssistant,
    entry: OnvifMotionConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    hub = entry.runtime_data
    entities: list[ButtonEntity] = [SnapshotButton(hub), TestAlertButton(hub)]
    if hub.is_onvif:
        entities.append(RebootButton(hub))
    if hub.ptz:
        entities.extend(PTZButton(hub, *spec) for spec in PTZ_BUTTONS)
    if hub.vigi and (hub.vigi.data or {}).get("alarm"):
        entities.extend([AlarmButton(hub, True), AlarmButton(hub, False)])
    async_add_entities(entities)


class SnapshotButton(OnvifMotionEntity, ButtonEntity):
    _attr_translation_key = "take_snapshot"
    _attr_icon = "mdi:camera"

    def __init__(self, hub: OnvifHub) -> None:
        super().__init__(hub, "take_snapshot")

    async def async_press(self) -> None:
        await self.hub.async_take_snapshot("manual")


class TestAlertButton(OnvifMotionEntity, ButtonEntity):
    _attr_translation_key = "test_alert"
    _attr_icon = "mdi:bell-ring"
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, hub: OnvifHub) -> None:
        super().__init__(hub, "test_alert")

    async def async_press(self) -> None:
        image = await self.hub.async_take_snapshot("test")
        await self.hub.async_send_alert(
            f"Test alert from {self.hub.name} (ONVIF Motion & Snapshot)", image
        )


class RebootButton(OnvifMotionEntity, ButtonEntity):
    _attr_device_class = ButtonDeviceClass.RESTART
    _attr_entity_category = EntityCategory.CONFIG

    def __init__(self, hub: OnvifHub) -> None:
        super().__init__(hub, "reboot")

    async def async_press(self) -> None:
        await self.hub.async_reboot()


# key, icon, pan, tilt, zoom
PTZ_BUTTONS = (
    ("ptz_pan_left", "mdi:pan-left", -DEFAULT_SPEED, 0.0, 0.0),
    ("ptz_pan_right", "mdi:pan-right", DEFAULT_SPEED, 0.0, 0.0),
    ("ptz_tilt_up", "mdi:pan-up", 0.0, DEFAULT_SPEED, 0.0),
    ("ptz_tilt_down", "mdi:pan-down", 0.0, -DEFAULT_SPEED, 0.0),
    ("ptz_zoom_in", "mdi:magnify-plus", 0.0, 0.0, DEFAULT_SPEED),
    ("ptz_zoom_out", "mdi:magnify-minus", 0.0, 0.0, -DEFAULT_SPEED),
)


class PTZButton(OnvifMotionEntity, ButtonEntity):
    """Move the camera a little in one direction (standard ONVIF PTZ)."""

    def __init__(self, hub: OnvifHub, key: str, icon: str, pan: float, tilt: float, zoom: float) -> None:
        super().__init__(hub, key)
        self._attr_translation_key = key
        self._attr_icon = icon
        self._move = (pan, tilt, zoom)

    async def async_press(self) -> None:
        assert self.hub.ptz
        await self.hub.ptz.jog(*self._move)


class AlarmButton(VigiEntity, ButtonEntity):
    """Sound / stop the camera's siren and warning light."""

    def __init__(self, hub: OnvifHub, start: bool) -> None:
        key = "alarm_trigger" if start else "alarm_stop"
        super().__init__(hub, f"vigi_{key}")
        self._attr_translation_key = key
        self._attr_icon = "mdi:alarm-light" if start else "mdi:alarm-light-off"
        self._start = start

    async def async_press(self) -> None:
        await self.coordinator.async_write(self.coordinator.api.alarm(self._start))
