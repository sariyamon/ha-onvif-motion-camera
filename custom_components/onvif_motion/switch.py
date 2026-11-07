"""Switches to turn snapshots and Telegram / WhatsApp alerts on and off."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.const import STATE_OFF
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from . import OnvifMotionConfigEntry
from .entity import OnvifMotionEntity
from .hub import OnvifHub


@dataclass(frozen=True, kw_only=True)
class HubSwitchDescription(SwitchEntityDescription):
    attr: str


SWITCHES = (
    HubSwitchDescription(
        key="snapshots", translation_key="snapshots", icon="mdi:camera-burst", attr="snapshots_enabled"
    ),
    HubSwitchDescription(
        key="telegram_alerts", translation_key="telegram_alerts", icon="mdi:send", attr="telegram_enabled"
    ),
    HubSwitchDescription(
        key="whatsapp_alerts", translation_key="whatsapp_alerts", icon="mdi:whatsapp", attr="whatsapp_enabled"
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: OnvifMotionConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    hub = entry.runtime_data
    async_add_entities(HubSwitch(hub, desc) for desc in SWITCHES)


class HubSwitch(OnvifMotionEntity, SwitchEntity, RestoreEntity):
    """A per-camera on/off setting that survives restarts."""

    entity_description: HubSwitchDescription

    def __init__(self, hub: OnvifHub, description: HubSwitchDescription) -> None:
        super().__init__(hub, description.key)
        self.entity_description = description

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if (last := await self.async_get_last_state()) is not None:
            setattr(self.hub, self.entity_description.attr, last.state != STATE_OFF)

    @property
    def is_on(self) -> bool:
        return bool(getattr(self.hub, self.entity_description.attr))

    async def async_turn_on(self, **kwargs: Any) -> None:
        setattr(self.hub, self.entity_description.attr, True)
        self.async_write_ha_state()

    async def async_turn_off(self, **kwargs: Any) -> None:
        setattr(self.hub, self.entity_description.attr, False)
        self.async_write_ha_state()
