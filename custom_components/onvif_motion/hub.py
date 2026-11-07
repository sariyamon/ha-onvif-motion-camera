"""Connection to one ONVIF camera: info, events, snapshots and alerts."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime
import logging
import os
from pathlib import Path
from typing import Any
from urllib.parse import quote, urlsplit, urlunsplit

import onvif
from onvif import ONVIFCamera
from onvif.exceptions import ONVIFError
from zeep.exceptions import Fault, TransportError

from homeassistant.components import ffmpeg
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONF_HOST,
    CONF_NAME,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_USERNAME,
)
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.storage import Store
from homeassistant.util import dt as dt_util

from .alerts import (
    CHANNEL_TELEGRAM,
    CHANNEL_WHATSAPP,
    send_telegram,
    send_whatsapp,
    telegram_configured,
    whatsapp_configured,
)
from .const import (
    BUS_EVENT,
    BUS_EVENT_SNAPSHOT,
    CONF_ALERT_COOLDOWN,
    CONF_ALERT_EVENTS,
    CONF_ALERT_MESSAGE,
    CONF_EVENT_OFF_DELAY,
    CONF_PROFILE_TOKEN,
    CONF_PROTOCOL,
    CONF_STREAM_URL,
    CONF_SNAPSHOT_COOLDOWN,
    CONF_SNAPSHOT_EVENTS,
    CONF_SNAPSHOT_KEEP,
    DEFAULT_ALERT_COOLDOWN,
    DEFAULT_ALERT_EVENTS,
    DEFAULT_ALERT_MESSAGE,
    DEFAULT_EVENT_OFF_DELAY,
    DEFAULT_SNAPSHOT_COOLDOWN,
    DEFAULT_SNAPSHOT_EVENTS,
    DEFAULT_SNAPSHOT_KEEP,
    DOMAIN,
    EVENT_LABELS,
    MANUFACTURER_FALLBACK,
    PROTOCOL_HTTPS,
    PULLPOINT_TIMEOUT,
    RETRY_DELAY,
    SIGNAL_NEW_EVENT,
    SIGNAL_UPDATE,
    SNAPSHOT_DIR,
    STORAGE_VERSION,
    SUBSCRIPTION_INTERVAL,
)
from .parsers import ParsedEvent, parse_messages
from .ptz import OnvifPTZ

_LOGGER = logging.getLogger(__name__)
MOMENTARY_RESET = 5  # seconds a pulse-style event (e.g. line crossed) stays on
WSDL_DIR = f"{os.path.dirname(onvif.__file__)}/wsdl/"
CONNECT_ERRORS = (ONVIFError, Fault, TransportError, OSError, TimeoutError)


class CannotConnect(HomeAssistantError):
    """Camera did not answer."""


class InvalidAuth(HomeAssistantError):
    """Camera rejected the credentials."""


@dataclass
class DeviceInfo:
    """Static information about the camera."""

    manufacturer: str = MANUFACTURER_FALLBACK
    model: str = "Camera"
    firmware: str | None = None
    serial: str | None = None
    mac: str | None = None


@dataclass
class EventState:
    """Current state of one event sensor."""

    event: ParsedEvent
    active: bool
    last_changed: datetime
    last_triggered: datetime | None = None
    count: int = 0


@dataclass
class SnapshotInfo:
    """The latest saved snapshot."""

    path: str | None = None
    time: datetime | None = None
    kind: str | None = None
    history: list[str] = field(default_factory=list)


def build_host(host: str, protocol: str) -> str:
    """onvif-zeep-async uses a scheme in the host to talk HTTPS."""
    host = host.strip().removeprefix("http://").removeprefix("https://").rstrip("/")
    return f"https://{host}" if protocol == PROTOCOL_HTTPS else host


def make_camera(data: dict[str, Any]) -> ONVIFCamera:
    """Create the ONVIF client from config entry data."""
    return ONVIFCamera(
        build_host(data[CONF_HOST], data.get(CONF_PROTOCOL, "http")),
        data[CONF_PORT],
        data[CONF_USERNAME],
        data[CONF_PASSWORD],
        WSDL_DIR,
        no_cache=True,
        adjust_time=True,
    )


def _is_auth_error(err: Exception) -> bool:
    text = str(err).lower()
    return any(
        word in text
        for word in ("notauthorized", "not authorized", "unauthorized", "401", "auth")
    )


async def async_probe(data: dict[str, Any]) -> tuple[DeviceInfo, list[dict[str, Any]]]:
    """Connect, read device info and media profiles. Used by the config flow."""
    camera = make_camera(data)
    try:
        await camera.update_xaddrs()
        info = await _read_device_info(camera)
        profiles = await _read_profiles(camera)
    except Fault as err:
        if _is_auth_error(err):
            raise InvalidAuth(str(err)) from err
        raise CannotConnect(str(err)) from err
    except CONNECT_ERRORS as err:
        if _is_auth_error(err):
            raise InvalidAuth(str(err)) from err
        raise CannotConnect(str(err)) from err
    finally:
        await camera.close()
    if not profiles:
        raise CannotConnect("Camera reported no video profiles")
    return info, profiles


async def _read_device_info(camera: ONVIFCamera) -> DeviceInfo:
    devicemgmt = await camera.create_devicemgmt_service()
    info = DeviceInfo()
    result = await devicemgmt.GetDeviceInformation()
    info.manufacturer = getattr(result, "Manufacturer", None) or MANUFACTURER_FALLBACK
    info.model = getattr(result, "Model", None) or "Camera"
    info.firmware = getattr(result, "FirmwareVersion", None)
    info.serial = getattr(result, "SerialNumber", None)
    try:
        interfaces = await devicemgmt.GetNetworkInterfaces()
        for interface in interfaces or []:
            if getattr(interface, "Enabled", False):
                info.mac = interface.Info.HwAddress
                break
    except (Fault, AttributeError) as err:
        _LOGGER.debug("Could not read network interfaces: %s", err)
    return info


async def _read_profiles(camera: ONVIFCamera) -> list[dict[str, Any]]:
    media = await camera.create_media_service()
    profiles = []
    for profile in await media.GetProfiles() or []:
        encoder = getattr(profile, "VideoEncoderConfiguration", None)
        if encoder is None:
            continue
        resolution = getattr(encoder, "Resolution", None)
        profiles.append(
            {
                "token": profile.token,
                "name": profile.Name,
                "encoding": getattr(encoder, "Encoding", ""),
                "width": getattr(resolution, "Width", 0),
                "height": getattr(resolution, "Height", 0),
                "ptz": getattr(profile, "PTZConfiguration", None) is not None,
            }
        )
    return profiles


def _with_credentials(uri: str, username: str, password: str) -> str:
    parts = urlsplit(uri)
    if parts.username or not username:
        return uri
    netloc = f"{quote(username, safe='')}:{quote(password, safe='')}@{parts.netloc}"
    return urlunsplit(parts._replace(netloc=netloc))


class OnvifHub:
    """Everything this integration does for one camera."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.name: str = entry.data.get(CONF_NAME) or entry.title
        self.camera: ONVIFCamera | None = None
        self.info = DeviceInfo()
        self.profile_token: str | None = entry.data.get(CONF_PROFILE_TOKEN)
        self.stream_uri: str | None = None
        self.supports_events = False
        self.subscribed = False
        self.events: dict[str, EventState] = {}
        self.last_event: EventState | None = None
        self.trigger_count = 0  # detections since start, for counters
        self.snapshot = SnapshotInfo()
        self.snapshots_enabled = True
        self.telegram_enabled = True
        self.whatsapp_enabled = True
        self._manager: Any = None
        self._event_task: asyncio.Task | None = None
        self._stop = asyncio.Event()
        self._off_timers: dict[str, CALLBACK_TYPE] = {}
        self._last_snapshot_at: float = 0.0
        self._last_alert_at: float = 0.0
        self._snapshot_lock = asyncio.Lock()
        self._onvif_snapshot: bool | None = None  # None = not tried yet
        # Cameras report current states as "Initialized" right after we
        # subscribe; some (TP-Link VIGI) keep using that tag for live events.
        # Only treat it as startup state inside this short window.
        self._initial_until: float = 0.0
        self._store: Store[dict[str, Any]] = Store(
            hass, STORAGE_VERSION, f"{DOMAIN}.{entry.entry_id}"
        )
        # Snapshots live in the media folder: browsable in Media, not served
        # publicly, and on the allowlist Home Assistant's Telegram bot can send from.
        media_root = hass.config.media_dirs.get("local") or hass.config.path("media")
        self.snapshot_dir = Path(media_root, SNAPSHOT_DIR, entry.entry_id)
        self.ptz: OnvifPTZ | None = None
        self.vigi: Any = None  # VigiCoordinator when the camera has VIGI controls
        self.push_active = False  # VIGI push-event stream connected
        self._push_task: asyncio.Task | None = None

    # ------------------------------------------------------------------ setup
    @property
    def options(self) -> dict[str, Any]:
        return dict(self.entry.options)

    @property
    def unique_id(self) -> str:
        return self.entry.unique_id or self.entry.entry_id

    async def async_setup(self) -> None:
        """Connect to the camera. Raises CannotConnect / InvalidAuth."""
        await self._load_store()
        self.camera = make_camera(dict(self.entry.data))
        try:
            await self.camera.update_xaddrs()
            self.info = await _read_device_info(self.camera)
            profiles = await _read_profiles(self.camera)
            tokens = [p["token"] for p in profiles]
            if self.profile_token not in tokens and tokens:
                self.profile_token = tokens[0]
            custom = (self.entry.data.get(CONF_STREAM_URL) or "").strip()
            self.stream_uri = (
                _with_credentials(custom, self.entry.data[CONF_USERNAME], self.entry.data[CONF_PASSWORD])
                if custom
                else await self._read_stream_uri()
            )
            if any(p["ptz"] for p in profiles if p["token"] == self.profile_token):
                ptz = OnvifPTZ(self.camera, self.profile_token)
                if await ptz.setup():
                    self.ptz = ptz
        except CONNECT_ERRORS as err:
            await self.camera.close()
            self.camera = None
            if _is_auth_error(err):
                raise InvalidAuth(str(err)) from err
            raise CannotConnect(str(err)) from err

        self._event_task = self.entry.async_create_background_task(
            self.hass, self._event_loop(), f"{DOMAIN} events {self.name}"
        )

    async def async_shutdown(self) -> None:
        """Stop the event loop and close sessions."""
        self._stop.set()
        for cancel in self._off_timers.values():
            cancel()
        self._off_timers.clear()
        if self._event_task:
            self._event_task.cancel()
        await self._stop_manager()
        if self._push_task:
            self._push_task.cancel()
        if self.vigi:
            await self.vigi.api.close()
        if self.camera:
            await self.camera.close()
            self.camera = None

    async def _read_stream_uri(self) -> str | None:
        if not self.camera or not self.profile_token:
            return None
        media = await self.camera.create_media_service()
        req = media.create_type("GetStreamUri")
        req.ProfileToken = self.profile_token
        req.StreamSetup = {
            "Stream": "RTP-Unicast",
            "Transport": {"Protocol": "RTSP"},
        }
        try:
            result = await media.GetStreamUri(req)
        except Fault as err:
            _LOGGER.warning("%s: could not get stream URI: %s", self.name, err)
            return None
        return _with_credentials(
            result.Uri, self.entry.data[CONF_USERNAME], self.entry.data[CONF_PASSWORD]
        )

    # --------------------------------------------------------------- storage
    async def _load_store(self) -> None:
        data = await self._store.async_load() or {}
        snap = data.get("snapshot") or {}
        self.snapshot = SnapshotInfo(
            path=snap.get("path"),
            time=dt_util.parse_datetime(snap["time"]) if snap.get("time") else None,
            kind=snap.get("kind"),
            history=list(snap.get("history") or []),
        )
        if self.snapshot.path and not await self.hass.async_add_executor_job(
            os.path.isfile, self.snapshot.path
        ):
            self.snapshot.path = None
        last = data.get("last_event") or {}
        self._restored_last_event = last

    @property
    def restored_last_event(self) -> dict[str, Any]:
        return getattr(self, "_restored_last_event", {}) or {}

    def _save_store(self) -> None:
        last = self.last_event
        self._store.async_delay_save(
            lambda: {
                "snapshot": {
                    "path": self.snapshot.path,
                    "time": self.snapshot.time.isoformat() if self.snapshot.time else None,
                    "kind": self.snapshot.kind,
                    "history": self.snapshot.history,
                },
                "last_event": {
                    "kind": last.event.kind,
                    "name": last.event.name,
                    "time": last.last_changed.isoformat(),
                }
                if last
                else self.restored_last_event,
            },
            2,
        )

    # ---------------------------------------------------------------- events
    async def _stop_manager(self) -> None:
        manager, self._manager = self._manager, None
        if manager is not None:
            try:
                await manager.shutdown()
            except CONNECT_ERRORS as err:
                _LOGGER.debug("%s: error closing subscription: %s", self.name, err)

    @callback
    def _subscription_lost(self) -> None:
        _LOGGER.debug("%s: event subscription lost", self.name)
        self.subscribed = False
        self._signal_update()

    async def _event_loop(self) -> None:
        """Keep a PullPoint subscription alive and process its messages."""
        while not self._stop.is_set():
            try:
                assert self.camera is not None
                self._manager = await self.camera.create_pullpoint_manager(
                    SUBSCRIPTION_INTERVAL, self._subscription_lost
                )
                self.supports_events = True
                self._initial_until = self.hass.loop.time() + 10
                try:
                    await self._manager.set_synchronization_point()
                except CONNECT_ERRORS:
                    pass
                service = self._manager.get_service()
                self.subscribed = True
                self._signal_update()
                _LOGGER.debug("%s: PullPoint subscription started", self.name)
                while not self._stop.is_set() and not self._manager.closed:
                    result = await service.PullMessages(
                        {"MessageLimit": 100, "Timeout": PULLPOINT_TIMEOUT}
                    )
                    messages = getattr(result, "NotificationMessage", None)
                    if messages:
                        self._handle_events(parse_messages(messages))
            except asyncio.CancelledError:
                raise
            except CONNECT_ERRORS as err:
                _LOGGER.warning(
                    "%s: event subscription failed (%s), retrying in %ss",
                    self.name,
                    err,
                    RETRY_DELAY,
                )
            except Exception:  # noqa: BLE001 - keep the loop alive
                _LOGGER.exception("%s: unexpected error in event loop", self.name)
            self.subscribed = False
            self._signal_update()
            await self._stop_manager()
            try:
                await asyncio.wait_for(self._stop.wait(), RETRY_DELAY)
            except TimeoutError:
                pass

    # ------------------------------------------------------- VIGI push events
    def start_push_fallback(self, delay: float = 90) -> None:
        """Use the VIGI push stream if the ONVIF feed stays silent.

        Most VIGI cameras answer an ONVIF subscription with their current
        states at once; some (C540V PTZ) never send anything on it and only
        report detections on TP-Link's own push channel.
        """

        async def _watch() -> None:
            from .vigi_api import VigiPushAPI  # noqa: PLC0415
            from .vigi_events import VigiPushListener  # noqa: PLC0415

            await asyncio.sleep(delay)
            if any(not uid.startswith("vigi_push|") for uid in self.events):
                return  # ONVIF works for this camera
            _LOGGER.info("%s: no ONVIF events, using VIGI push events", self.name)
            host = self.entry.data[CONF_HOST].removeprefix("https://").removeprefix("http://")
            api = VigiPushAPI(host, self.entry.data[CONF_USERNAME], self.entry.data[CONF_PASSWORD])
            await VigiPushListener(self, api).run()

        self._push_task = self.entry.async_create_background_task(
            self.hass, _watch(), f"{DOMAIN} push {self.name}"
        )

    @callback
    def push_connected(self, connected: bool) -> None:
        self.push_active = connected
        self._signal_update()

    @callback
    def process_push_event(self, event: ParsedEvent) -> None:
        self.process_event(event)
        self._signal_update()

    @callback
    def _handle_events(self, events: list[ParsedEvent]) -> None:
        for event in events:
            self.process_event(event)
        self._signal_update()

    @callback
    def process_event(self, event: ParsedEvent) -> None:
        """Apply one parsed event (public so tests and services can inject)."""
        now = dt_util.utcnow()
        state = self.events.get(event.uid)
        is_new = state is None
        previous = state.active if state else False

        if not event.active and previous:
            delay = int(self.options.get(CONF_EVENT_OFF_DELAY, DEFAULT_EVENT_OFF_DELAY))
            if delay > 0:
                self._schedule_off(event.uid, delay)
                return

        if state is None:
            state = EventState(event=event, active=event.active, last_changed=now)
            self.events[event.uid] = state
        else:
            state.event = event
            if state.active != event.active:
                state.active = event.active
                state.last_changed = now

        if is_new:
            async_dispatcher_send(
                self.hass, SIGNAL_NEW_EVENT.format(self.entry.entry_id), event.uid
            )

        if event.active:
            self._cancel_off(event.uid)
            if event.momentary:
                self._schedule_off(event.uid, MOMENTARY_RESET)

        initial = event.is_initial and self.hass.loop.time() < self._initial_until
        _LOGGER.debug(
            "%s: %s %s -> %s (%s)",
            self.name, event.kind, event.uid, event.active, event.operation,
        )
        rising = event.active and (not previous or event.momentary)
        if rising and not initial:
            state.last_triggered = now
            state.count += 1
            self.trigger_count += 1
            self.last_event = state
            self._save_store()
            self._fire_bus_event(state)
            self.entry.async_create_task(
                self.hass, self._on_trigger(event), f"{DOMAIN} trigger {self.name}"
            )
        elif previous != event.active and not initial:
            self._fire_bus_event(state)

    def _schedule_off(self, uid: str, delay: float) -> None:
        self._cancel_off(uid)

        @callback
        def _turn_off(_now: datetime) -> None:
            self._off_timers.pop(uid, None)
            state = self.events.get(uid)
            if state and state.active:
                state.active = False
                state.last_changed = dt_util.utcnow()
                self._fire_bus_event(state)
                self._signal_update()

        self._off_timers[uid] = async_call_later(self.hass, delay, _turn_off)

    def _cancel_off(self, uid: str) -> None:
        if cancel := self._off_timers.pop(uid, None):
            cancel()

    def _fire_bus_event(self, state: EventState) -> None:
        self.hass.bus.async_fire(
            BUS_EVENT,
            {
                "entry_id": self.entry.entry_id,
                "camera": self.name,
                "event": state.event.kind,
                "name": state.event.name,
                "active": state.active,
                "topic": state.event.topic,
                "source": state.event.source,
            },
        )

    @callback
    def _signal_update(self) -> None:
        async_dispatcher_send(self.hass, SIGNAL_UPDATE.format(self.entry.entry_id))

    async def _on_trigger(self, event: ParsedEvent) -> None:
        loop_time = self.hass.loop.time()
        options = self.options
        snap_kinds = options.get(CONF_SNAPSHOT_EVENTS, DEFAULT_SNAPSHOT_EVENTS)
        alert_kinds = options.get(CONF_ALERT_EVENTS, DEFAULT_ALERT_EVENTS)
        snap_cooldown = float(options.get(CONF_SNAPSHOT_COOLDOWN, DEFAULT_SNAPSHOT_COOLDOWN))
        alert_cooldown = float(options.get(CONF_ALERT_COOLDOWN, DEFAULT_ALERT_COOLDOWN))

        image: bytes | None = None
        if (
            self.snapshots_enabled
            and event.kind in snap_kinds
            and loop_time - self._last_snapshot_at >= snap_cooldown
        ):
            self._last_snapshot_at = loop_time
            try:
                image = await self.async_take_snapshot(event.kind)
            except HomeAssistantError as err:
                _LOGGER.warning("%s: snapshot failed: %s", self.name, err)

        if event.kind in alert_kinds and loop_time - self._last_alert_at >= alert_cooldown:
            channels = []
            if self.telegram_enabled and telegram_configured(options):
                channels.append(CHANNEL_TELEGRAM)
            if self.whatsapp_enabled and whatsapp_configured(options):
                channels.append(CHANNEL_WHATSAPP)
            if channels:
                self._last_alert_at = loop_time
                if image is None and self.snapshot.time and (
                    dt_util.utcnow() - self.snapshot.time
                ).total_seconds() < 5:
                    image = await self.async_read_snapshot()
                message = self.format_message(event.kind)
                try:
                    await self.async_send_alert(message, image, channels)
                except HomeAssistantError as err:
                    _LOGGER.warning("%s: alert failed: %s", self.name, err)

    def format_message(self, kind: str) -> str:
        template = self.options.get(CONF_ALERT_MESSAGE) or DEFAULT_ALERT_MESSAGE
        now = dt_util.now()
        values = {
            "camera": self.name,
            "event": EVENT_LABELS.get(kind, kind),
            "time": now.strftime("%d %b %Y, %I:%M:%S %p"),
            "date": now.strftime("%d %b %Y"),
        }
        try:
            return template.format(**values)
        except (KeyError, IndexError, ValueError):
            return DEFAULT_ALERT_MESSAGE.format(**values)

    # ------------------------------------------------------------- snapshots
    async def async_get_image(self) -> bytes | None:
        """Fetch a fresh still from the camera.

        Uses the camera's ONVIF snapshot URL when it has one. Many cameras
        (e.g. TP-Link VIGI) do not, so fall back to grabbing one frame from
        the RTSP stream with Home Assistant's ffmpeg.
        """
        if not self.camera or not self.profile_token:
            return None
        image: bytes | None = None
        if self._onvif_snapshot is not False:
            try:
                uri = await self.camera.get_snapshot_uri(self.profile_token)
                if uri is None:
                    self._onvif_snapshot = False
                    _LOGGER.debug("%s: no ONVIF snapshot URL, using the stream", self.name)
                else:
                    image = await self.camera.get_snapshot(self.profile_token)
                    if image is None:
                        image = await self.camera.get_snapshot(
                            self.profile_token, basic_auth=True
                        )
                    if image:
                        self._onvif_snapshot = True
            except CONNECT_ERRORS as err:
                _LOGGER.debug("%s: ONVIF snapshot failed: %s", self.name, err)
        if not image and self.stream_uri:
            image = await ffmpeg.async_get_image(self.hass, self.stream_uri)
        if not image:
            raise HomeAssistantError("Camera returned no snapshot image")
        return image

    async def async_take_snapshot(self, kind: str | None = "manual") -> bytes:
        """Grab a still, save it as the latest snapshot and return it."""
        async with self._snapshot_lock:
            image = await self.async_get_image()
            if not image:
                raise HomeAssistantError("Camera returned no snapshot image")
            now = dt_util.now()
            filename = f"{now:%Y%m%d_%H%M%S}_{kind or 'manual'}.jpg"
            path = self.snapshot_dir / filename
            keep = int(self.options.get(CONF_SNAPSHOT_KEEP, DEFAULT_SNAPSHOT_KEEP))
            history = [*self.snapshot.history, str(path)]
            removed = history[:-keep] if keep > 0 and len(history) > keep else []
            history = history[len(removed):]
            await self.hass.async_add_executor_job(
                _write_snapshot, self.snapshot_dir, path, image, removed
            )
            self.snapshot = SnapshotInfo(
                path=str(path), time=dt_util.utcnow(), kind=kind, history=history
            )
            self._save_store()
            self.hass.bus.async_fire(
                BUS_EVENT_SNAPSHOT,
                {
                    "entry_id": self.entry.entry_id,
                    "camera": self.name,
                    "event": kind,
                    "path": str(path),
                },
            )
            self._signal_update()
            return image

    async def async_read_snapshot(self) -> bytes | None:
        """Bytes of the latest saved snapshot."""
        if not self.snapshot.path:
            return None
        return await self.hass.async_add_executor_job(_read_file, self.snapshot.path)

    # ---------------------------------------------------------------- alerts
    async def async_send_alert(
        self,
        message: str,
        image: bytes | None,
        channels: list[str] | None = None,
    ) -> None:
        options = self.options
        channels = channels or [CHANNEL_TELEGRAM, CHANNEL_WHATSAPP]
        errors: list[str] = []
        sent = False
        if CHANNEL_TELEGRAM in channels and telegram_configured(options):
            try:
                await send_telegram(
                    self.hass, options, message, image, self.snapshot.path
                )
                sent = True
            except HomeAssistantError as err:
                errors.append(str(err))
        if CHANNEL_WHATSAPP in channels and whatsapp_configured(options):
            try:
                await send_whatsapp(
                    self.hass, options, message, image, self.snapshot.path
                )
                sent = True
            except HomeAssistantError as err:
                errors.append(str(err))
        if errors:
            raise HomeAssistantError("; ".join(errors))
        if not sent:
            raise HomeAssistantError(
                "No alert channel is set up. Add Telegram or WhatsApp in the "
                "integration's Configure options."
            )

    # ------------------------------------------------------------------ misc
    async def async_reboot(self) -> None:
        if not self.camera:
            raise HomeAssistantError("Camera not connected")
        devicemgmt = await self.camera.create_devicemgmt_service()
        await devicemgmt.SystemReboot()


def _write_snapshot(folder: Path, path: Path, image: bytes, removed: list[str]) -> None:
    folder.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_bytes(image)
    tmp.replace(path)
    for old in removed:
        try:
            Path(old).unlink(missing_ok=True)
        except OSError:
            pass


def _read_file(path: str) -> bytes | None:
    try:
        return Path(path).read_bytes()
    except OSError:
        return None
