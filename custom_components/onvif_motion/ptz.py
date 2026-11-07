"""Pan / tilt / zoom and presets through the standard ONVIF PTZ service."""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from onvif import ONVIFCamera

_LOGGER = logging.getLogger(__name__)

DEFAULT_SPEED = 0.3
MOVE_SECONDS = 1.0


class OnvifPTZ:
    """Jog moves (move briefly, then stop) and preset recall for one profile."""

    def __init__(self, camera: ONVIFCamera, profile_token: str) -> None:
        self._camera = camera
        self._token = profile_token
        self._service: Any = None
        self._jog: asyncio.Task | None = None
        self.presets: list[dict[str, str]] = []

    async def setup(self) -> bool:
        """True if the camera answers PTZ calls for this profile."""
        try:
            self._service = await self._camera.create_ptz_service()
            await self.refresh_presets()
            return True
        except Exception as err:  # noqa: BLE001 - any failure means "no PTZ"
            _LOGGER.debug("No ONVIF PTZ: %s", err)
            return False

    async def refresh_presets(self) -> None:
        result = await self._service.GetPresets({"ProfileToken": self._token})
        self.presets = [
            {"id": str(p.token), "name": str(getattr(p, "Name", None) or p.token)}
            for p in result or []
        ]

    async def jog(self, pan: float, tilt: float, zoom: float, seconds: float = MOVE_SECONDS) -> None:
        """Move for a moment and stop, replacing any move still running."""
        if self._jog and not self._jog.done():
            self._jog.cancel()
        velocity: dict[str, Any] = {}
        if pan or tilt:
            velocity["PanTilt"] = {"x": pan, "y": tilt}
        if zoom:
            velocity["Zoom"] = {"x": zoom}
        await self._service.ContinuousMove({"ProfileToken": self._token, "Velocity": velocity})
        self._jog = asyncio.ensure_future(self._stop_after(seconds))

    async def _stop_after(self, seconds: float) -> None:
        await asyncio.sleep(seconds)
        await self.stop()

    async def stop(self) -> None:
        await self._service.Stop({"ProfileToken": self._token, "PanTilt": True, "Zoom": True})

    async def goto_preset(self, preset_id: str) -> None:
        await self._service.GotoPreset({"ProfileToken": self._token, "PresetToken": preset_id})
