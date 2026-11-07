"""Base entity for ONVIF Motion & Snapshot."""
from __future__ import annotations

from homeassistant.core import callback
from homeassistant.helpers.device_registry import CONNECTION_NETWORK_MAC, DeviceInfo
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, SIGNAL_UPDATE
from .hub import OnvifHub


class OnvifMotionEntity(Entity):
    """Common device info and update wiring."""

    _attr_has_entity_name = True
    _attr_should_poll = False

    def __init__(self, hub: OnvifHub, key: str) -> None:
        self.hub = hub
        self._attr_unique_id = f"{hub.unique_id}_{key}"
        info = hub.info
        connections = set()
        if info.mac:
            connections.add((CONNECTION_NETWORK_MAC, info.mac.lower()))
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, hub.unique_id)},
            connections=connections,
            name=hub.name,
            manufacturer=info.manufacturer,
            model=info.model,
            sw_version=info.firmware,
            serial_number=info.serial,
        )

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_UPDATE.format(self.hub.entry.entry_id),
                self._handle_hub_update,
            )
        )

    @callback
    def _handle_hub_update(self) -> None:
        self.async_write_ha_state()


class VigiEntity(CoordinatorEntity, OnvifMotionEntity):
    """A camera setting read and written through the VIGI API."""

    def __init__(self, hub: OnvifHub, key: str) -> None:
        OnvifMotionEntity.__init__(self, hub, key)
        CoordinatorEntity.__init__(self, hub.vigi)

    @property
    def data(self) -> dict:
        return self.coordinator.data or {}
