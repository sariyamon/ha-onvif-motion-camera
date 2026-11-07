"""Image entity showing the latest saved event snapshot."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from homeassistant.components.image import ImageEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import OnvifMotionConfigEntry
from .entity import OnvifMotionEntity
from .hub import OnvifHub


async def async_setup_entry(
    hass: HomeAssistant,
    entry: OnvifMotionConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([LastSnapshotImage(hass, entry.runtime_data)])


class LastSnapshotImage(OnvifMotionEntity, ImageEntity):
    """The most recent snapshot, kept across restarts."""

    _attr_translation_key = "last_snapshot"
    _attr_content_type = "image/jpeg"

    def __init__(self, hass: HomeAssistant, hub: OnvifHub) -> None:
        OnvifMotionEntity.__init__(self, hub, "last_snapshot")
        ImageEntity.__init__(self, hass)
        self._shown_path: str | None = None
        self._attr_image_last_updated = hub.snapshot.time

    @property
    def image_last_updated(self) -> datetime | None:
        return self.hub.snapshot.time

    @property
    def available(self) -> bool:
        return self.hub.snapshot.path is not None

    @callback
    def _handle_hub_update(self) -> None:
        if self.hub.snapshot.path != self._shown_path:
            self._shown_path = self.hub.snapshot.path
            self._cached_image = None
        self.async_write_ha_state()

    async def async_image(self) -> bytes | None:
        return await self.hub.async_read_snapshot()

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "path": self.hub.snapshot.path,
            "event_type": self.hub.snapshot.kind,
        }
