"""Buttons: take a snapshot, send a test alert, reboot the camera."""
from __future__ import annotations

from homeassistant.components.button import ButtonDeviceClass, ButtonEntity
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import OnvifMotionConfigEntry
from .entity import OnvifMotionEntity
from .hub import OnvifHub


async def async_setup_entry(
    hass: HomeAssistant,
    entry: OnvifMotionConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    hub = entry.runtime_data
    async_add_entities([SnapshotButton(hub), TestAlertButton(hub), RebootButton(hub)])


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
