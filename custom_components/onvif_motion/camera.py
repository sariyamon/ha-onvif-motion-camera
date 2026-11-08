"""Live camera entity (RTSP stream + ONVIF still image)."""
from __future__ import annotations

from aiohttp import web
from haffmpeg.camera import CameraMjpeg

from homeassistant.components.camera import Camera, CameraEntityFeature
from homeassistant.components.ffmpeg import get_ffmpeg_manager
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_aiohttp_proxy_stream
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

    async def handle_async_mjpeg_stream(
        self, request: web.Request
    ) -> web.StreamResponse | None:
        """MJPEG live view (works in every browser and the mobile app, no HLS needed)."""
        if not self.hub.stream_uri:
            return await super().handle_async_mjpeg_stream(request)
        manager = get_ffmpeg_manager(self.hass)
        stream = CameraMjpeg(manager.binary)
        await stream.open_camera(self.hub.stream_uri, extra_cmd="-q:v 5 -r 10")
        try:
            reader = await stream.get_reader()
            return await async_aiohttp_proxy_stream(
                self.hass, request, reader, manager.ffmpeg_stream_content_type
            )
        finally:
            await stream.close()
