"""Live camera entity (RTSP stream + ONVIF still image)."""
from __future__ import annotations

from homeassistant.components.camera import Camera, CameraEntityFeature
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback

from . import OnvifMotionConfigEntry
from .const import CONF_RTSP_TRANSPORT
from .entity import OnvifMotionEntity
from .hub import OnvifHub


async def async_setup_entry(
    hass: HomeAssistant,
    entry: OnvifMotionConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    async_add_entities([OnvifLiveCamera(entry.runtime_data)])


class OnvifLiveCamera(OnvifMotionEntity, Camera):
    """The camera's live view."""

    _attr_translation_key = "live"
    _attr_name = None  # use the device name, e.g. "Gate"

    def __init__(self, hub: OnvifHub) -> None:
        OnvifMotionEntity.__init__(self, hub, "camera")
        Camera.__init__(self)
        if hub.stream_uri:
            self._attr_supported_features = CameraEntityFeature.STREAM
            transport = hub.entry.data.get(CONF_RTSP_TRANSPORT, "tcp")
            self.stream_options["rtsp_transport"] = transport

    async def stream_source(self) -> str | None:
        return self.hub.stream_uri

    async def async_camera_image(
        self, width: int | None = None, height: int | None = None
    ) -> bytes | None:
        try:
            return await self.hub.async_get_image()
        except HomeAssistantError:
            return None
