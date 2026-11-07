"""Numbers: motion sensitivity, speaker volume, siren repetitions (VIGI)."""
from __future__ import annotations

from dataclasses import dataclass

from homeassistant.components.number import NumberEntity, NumberEntityDescription, NumberMode
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import OnvifMotionConfigEntry
from .entity import VigiEntity
from .hub import OnvifHub


@dataclass(frozen=True, kw_only=True)
class VigiNumberDescription(NumberEntityDescription):
    data_key: str
    field: str
    module: str
    section: str
    as_text: bool = False


NUMBERS = (
    VigiNumberDescription(
        key="motion_sensitivity", translation_key="motion_sensitivity", icon="mdi:tune-vertical",
        native_min_value=0, native_max_value=100, native_step=1, mode=NumberMode.SLIDER,
        entity_category=EntityCategory.CONFIG,
        data_key="motion", field="digital_sensitivity", module="motion_detection", section="motion_det",
    ),
    VigiNumberDescription(
        key="speaker_volume", translation_key="speaker_volume", icon="mdi:volume-high",
        native_min_value=0, native_max_value=100, native_step=1, mode=NumberMode.SLIDER,
        entity_category=EntityCategory.CONFIG,
        data_key="speaker", field="volume", module="audio_config", section="speaker",
    ),
    VigiNumberDescription(
        key="alarm_repetitions", translation_key="alarm_repetitions", icon="mdi:repeat",
        native_min_value=1, native_max_value=50, native_step=1, mode=NumberMode.BOX,
        entity_category=EntityCategory.CONFIG, as_text=True,
        data_key="alarm", field="sound_alarm_times", module="msg_alarm", section="chn1_msg_alarm_info",
    ),
)


async def async_setup_entry(
    hass: HomeAssistant,
    entry: OnvifMotionConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    hub = entry.runtime_data
    if not hub.vigi:
        return
    data = hub.vigi.data or {}
    async_add_entities(
        VigiNumber(hub, desc) for desc in NUMBERS if desc.field in data.get(desc.data_key, {})
    )


class VigiNumber(VigiEntity, NumberEntity):
    entity_description: VigiNumberDescription

    def __init__(self, hub: OnvifHub, description: VigiNumberDescription) -> None:
        super().__init__(hub, f"vigi_{description.key}")
        self.entity_description = description

    @property
    def native_value(self) -> float | None:
        d = self.entity_description
        try:
            return float(self.data.get(d.data_key, {}).get(d.field))
        except (TypeError, ValueError):
            return None

    async def async_set_native_value(self, value: float) -> None:
        d = self.entity_description
        payload = str(int(value)) if d.as_text else int(value)
        await self.coordinator.async_write(
            self.coordinator.api.set(d.module, d.section, {d.field: payload})
        )
