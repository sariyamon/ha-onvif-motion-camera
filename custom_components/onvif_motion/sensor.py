"""Sensors: last event, last snapshot time, events today."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.event import async_track_time_change
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.util import dt as dt_util

from . import OnvifMotionConfigEntry
from .const import EVENT_KINDS, EVENT_LABELS
from .entity import OnvifMotionEntity
from .hub import OnvifHub


async def async_setup_entry(
    hass: HomeAssistant,
    entry: OnvifMotionConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    hub = entry.runtime_data
    async_add_entities(
        [
            LastEventTimeSensor(hub),
            LastEventTypeSensor(hub),
            LastSnapshotTimeSensor(hub),
            EventsTodaySensor(hub),
        ]
    )


class LastEventTimeSensor(OnvifMotionEntity, SensorEntity):
    """When the camera last detected something."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_translation_key = "last_event_time"
    _attr_icon = "mdi:motion-sensor"

    def __init__(self, hub: OnvifHub) -> None:
        super().__init__(hub, "last_event_time")

    @property
    def native_value(self) -> datetime | None:
        if self.hub.last_event and self.hub.last_event.last_triggered:
            return self.hub.last_event.last_triggered
        restored = self.hub.restored_last_event.get("time")
        return dt_util.parse_datetime(restored) if restored else None


class LastEventTypeSensor(OnvifMotionEntity, SensorEntity):
    """What the camera last detected (motion, person, vehicle…)."""

    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = EVENT_KINDS
    _attr_translation_key = "last_event_type"
    _attr_icon = "mdi:cctv"

    def __init__(self, hub: OnvifHub) -> None:
        super().__init__(hub, "last_event_type")

    @property
    def native_value(self) -> str | None:
        if self.hub.last_event:
            return self.hub.last_event.event.kind
        kind = self.hub.restored_last_event.get("kind")
        return kind if kind in EVENT_KINDS else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        last = self.hub.last_event
        if not last:
            return {}
        return {
            "label": EVENT_LABELS.get(last.event.kind, last.event.name),
            "name": last.event.name,
            "topic": last.event.topic,
            "source": last.event.source,
        }


class LastSnapshotTimeSensor(OnvifMotionEntity, SensorEntity):
    """When the latest snapshot was saved (for dashboard captions)."""

    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_translation_key = "last_snapshot_time"
    _attr_icon = "mdi:camera-burst"

    def __init__(self, hub: OnvifHub) -> None:
        super().__init__(hub, "last_snapshot_time")

    @property
    def native_value(self) -> datetime | None:
        return self.hub.snapshot.time

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "path": self.hub.snapshot.path,
            "event_type": self.hub.snapshot.kind,
            "saved_snapshots": len(self.hub.snapshot.history),
        }


class EventsTodaySensor(OnvifMotionEntity, SensorEntity, RestoreEntity):
    """Detections since midnight."""

    _attr_state_class = SensorStateClass.TOTAL
    _attr_translation_key = "events_today"
    _attr_icon = "mdi:counter"
    _attr_native_unit_of_measurement = "events"

    def __init__(self, hub: OnvifHub) -> None:
        super().__init__(hub, "events_today")
        self._count = 0
        self._seen_total = hub.trigger_count
        self._attr_last_reset = dt_util.start_of_local_day()

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        last = await self.async_get_last_state()
        if (
            last
            and last.state.isdigit()
            and dt_util.as_local(last.last_changed).date() == dt_util.now().date()
        ):
            self._count = int(last.state)
        self.async_on_remove(
            async_track_time_change(self.hass, self._midnight, hour=0, minute=0, second=0)
        )

    @callback
    def _midnight(self, _now: datetime) -> None:
        self._count = 0
        self._attr_last_reset = dt_util.start_of_local_day()
        self.async_write_ha_state()

    @callback
    def _handle_hub_update(self) -> None:
        total = self.hub.trigger_count
        if total > self._seen_total:
            self._count += total - self._seen_total
            self._seen_total = total
        self.async_write_ha_state()

    @property
    def native_value(self) -> int:
        return self._count
