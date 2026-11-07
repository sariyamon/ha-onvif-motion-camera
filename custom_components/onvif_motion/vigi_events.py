"""TP-Link VIGI push-event stream, used when a camera's ONVIF feed is silent."""
from __future__ import annotations

import asyncio
import json
import logging
from typing import TYPE_CHECKING

import aiohttp

from .const import EVENT_LABELS
from .parsers import ParsedEvent
from .vigi_api import PUSH_EVENT_KINDS, VigiError, VigiPushAPI

if TYPE_CHECKING:
    from .hub import OnvifHub

_LOGGER = logging.getLogger(__name__)
_HEARTBEAT_TIMEOUT = 45  # camera sends a heartbeat every 15 s


def push_event(event_type: str, area: str | None) -> ParsedEvent:
    """A pulse-style detection from the push stream."""
    kind = PUSH_EVENT_KINDS.get(event_type, "other")
    name = EVENT_LABELS.get(kind, event_type)
    if kind == "other":
        name = "Object left / taken" if event_type == "DropAndTakeDetection" else event_type
    return ParsedEvent(
        uid=f"vigi_push|{event_type}",
        kind=kind,
        name=name,
        topic=f"VIGI/{event_type}",
        source=area,
        active=True,
        momentary=True,
        operation="Changed",
        data={"event_type": event_type, **({"area": area} if area else {})},
    )


class VigiPushListener:
    """Keeps the push stream open and feeds detections into the hub."""

    def __init__(self, hub: OnvifHub, api: VigiPushAPI) -> None:
        self._hub = hub
        self._api = api
        self.connected = False

    async def run(self) -> None:
        backoff = 5
        while True:
            try:
                await self._stream()
                backoff = 5
            except asyncio.CancelledError:
                raise
            except (VigiError, aiohttp.ClientError, TimeoutError, OSError) as err:
                _LOGGER.debug("%s: push stream dropped (%s), retry in %ss", self._hub.name, err, backoff)
            self.connected = False
            self._hub.push_connected(False)
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 120)

    async def _stream(self) -> None:
        url = await self._api.stream_url()
        body = {"method": "subscribeMsg", "params": {"event_type": ["all"], "heartbeat": 15}}
        timeout = aiohttp.ClientTimeout(total=None, connect=10, sock_read=None)
        async with aiohttp.ClientSession(
            connector=aiohttp.TCPConnector(ssl=self._api.ssl), timeout=timeout
        ) as session, session.post(url, json=body) as resp:
            if resp.status != 200:
                raise VigiError(f"push stream HTTP {resp.status}")
            self.connected = True
            self._hub.push_connected(True)
            _LOGGER.debug("%s: push stream connected", self._hub.name)
            while True:
                line = await asyncio.wait_for(resp.content.readline(), _HEARTBEAT_TIMEOUT)
                if not line:
                    raise VigiError("stream closed by camera")
                line = line.strip()
                if not line or line.startswith(b"--") or line.lower().startswith(b"content-"):
                    continue
                try:
                    data = json.loads(line)
                except (ValueError, UnicodeDecodeError):
                    continue
                if isinstance(data, dict) and "event_type" in data:
                    area = (
                        data.get("detection_area") or data.get("area_name")
                        or data.get("rule_name") or data.get("region_name")
                    )
                    _LOGGER.debug("%s: push event %s", self._hub.name, data)
                    self._hub.process_push_event(push_event(str(data["event_type"]), area))
