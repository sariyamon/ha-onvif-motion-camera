"""Switches to turn snapshots and Telegram / WhatsApp alerts on and off."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from homeassistant.components.switch import SwitchEntity, SwitchEntityDescription
from homeassistant.const import STATE_OFF, EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from . import OnvifMotionConfigEntry
from .entity import OnvifMotionEntity, VigiEntity
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
    entities: list[SwitchEntity] = [HubSwitch(hub, desc) for desc in SWITCHES]
    if hub.vigi:
        data = hub.vigi.data or {}
        entities.extend(
            VigiSwitch(hub, desc)
            for desc in VIGI_SWITCHES
            if desc.field in data.get(desc.data_key, {})
        )
    async_add_entities(entities)


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


@dataclass(frozen=True, kw_only=True)
class VigiSwitchDescription(SwitchEntityDescription):
    """A VIGI on/off setting: data key, field, and where to write it."""

    data_key: str
    field: str
    module: str
    section: str


VIGI_SWITCHES = (
    VigiSwitchDescription(key="motion_detection", translation_key="motion_detection", icon="mdi:motion-sensor",
                          data_key="motion", field="enabled", module="motion_detection", section="motion_det"),
    VigiSwitchDescription(key="person_detection", translation_key="person_detection", icon="mdi:human",
                          data_key="motion", field="people_enabled", module="motion_detection", section="motion_det"),
    VigiSwitchDescription(key="vehicle_detection", translation_key="vehicle_detection", icon="mdi:car",
                          data_key="motion", field="vehicle_enabled", module="motion_detection", section="motion_det"),
    VigiSwitchDescription(key="tamper_detection", translation_key="tamper_detection", icon="mdi:shield-alert",
                          data_key="tamper", field="enabled", module="tamper_detection", section="tamper_det"),
    VigiSwitchDescription(key="alarm", translation_key="alarm", icon="mdi:alarm-light",
                          data_key="alarm", field="enabled", module="msg_alarm", section="chn1_msg_alarm_info"),
    VigiSwitchDescription(key="alarm_light", translation_key="alarm_light", icon="mdi:alarm-light-outline",
                          data_key="alarm", field="light_alarm_enabled", module="msg_alarm", section="chn1_msg_alarm_info"),
    VigiSwitchDescription(key="alarm_sound", translation_key="alarm_sound", icon="mdi:bullhorn",
                          data_key="alarm", field="sound_alarm_enabled", module="msg_alarm", section="chn1_msg_alarm_info"),
    VigiSwitchDescription(key="status_led", translation_key="status_led", icon="mdi:led-on",
                          entity_category=EntityCategory.CONFIG,
                          data_key="led", field="enabled", module="led", section="config"),
    VigiSwitchDescription(key="target_tracking", translation_key="target_tracking", icon="mdi:target-account",
                          data_key="target_track", field="enabled", module="target_track", section="target_track_info"),
    VigiSwitchDescription(key="speaker_mute", translation_key="speaker_mute", icon="mdi:volume-off",
                          entity_category=EntityCategory.CONFIG,
                          data_key="speaker", field="mute", module="audio_config", section="speaker"),
    VigiSwitchDescription(key="microphone_mute", translation_key="microphone_mute", icon="mdi:microphone-off",
                          entity_category=EntityCategory.CONFIG,
                          data_key="microphone", field="mute", module="audio_config", section="microphone"),
)


class VigiSwitch(VigiEntity, SwitchEntity):
    """On/off camera setting (only created when the camera reports it)."""

    entity_description: VigiSwitchDescription

    def __init__(self, hub: OnvifHub, description: VigiSwitchDescription) -> None:
        super().__init__(hub, f"vigi_{description.key}")
        self.entity_description = description

    @property
    def is_on(self) -> bool:
        d = self.entity_description
        return self.data.get(d.data_key, {}).get(d.field) == "on"

    async def _set(self, on: bool) -> None:
        d = self.entity_description
        await self.coordinator.async_write(
            self.coordinator.api.set(d.module, d.section, {d.field: "on" if on else "off"})
        )

    async def async_turn_on(self, **kwargs: Any) -> None:
        await self._set(True)

    async def async_turn_off(self, **kwargs: Any) -> None:
        await self._set(False)
