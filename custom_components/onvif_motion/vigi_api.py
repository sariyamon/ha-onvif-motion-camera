"""Client for the local HTTPS API of TP-Link VIGI / InSight cameras.

Used for the camera controls ONVIF does not cover: spotlight, siren, status
LED, detection on/off, sensitivity, speaker and microphone, target tracking
and the camera's own PTZ presets.

Adapted from VIGICam by Steve Bratt (https://github.com/steveAbratt/VIGICam,
MIT licence), whose login flow is in turn based on pytapo
(https://github.com/JurajNyiri/pytapo, MIT licence).

Login:
  1. POST / {"user_management": {"get_encrypt_info": null}} -> nonce + RSA key
  2. password = base64(RSA_PKCS1v15(MD5("TPCQ75NF2Y:" + pass).upper() + ":" + nonce))
  3. POST / login -> stok
  4. Every call: POST /stok=<stok>/ds
"""
from __future__ import annotations

import base64
import hashlib
import ssl
from typing import Any
import urllib.parse

import aiohttp
from cryptography.hazmat.primitives.asymmetric import padding
from cryptography.hazmat.primitives.serialization import load_pem_public_key

_PASSWORD_PREFIX = "TPCQ75NF2Y:"
_TIMEOUT = aiohttp.ClientTimeout(total=10)

# Result key -> (module, section) for the combined poll read.
POLL_READS: dict[str, tuple[str, str]] = {
    "device_info": ("device_info", "basic_info"),
    "motion": ("motion_detection", "motion_det"),
    "image_switch": ("image", "switch"),
    "alarm": ("msg_alarm", "chn1_msg_alarm_info"),
    "led": ("led", "config"),
    "speaker": ("audio_config", "speaker"),
    "microphone": ("audio_config", "microphone"),
    "tamper": ("tamper_detection", "tamper_det"),
    "target_track": ("target_track", "target_track_info"),
    "presets": ("preset", "preset"),
}

# Night vision: older firmware writes night_vision_mode, newer writes
# pre_night_vision_mode (night_vision_mode becomes a read-only status).
NIGHT_VISION_MODES = {
    "md_night_vision": "Auto (motion-triggered)",
    "inf_night_vision": "IR always on",
    "wtl_night_vision": "Spotlight always on",
    "human_triggered_color": "Colour when motion",
    "auto_switch_night_vision": "Auto switch",
}
PRE_NIGHT_VISION_MODES = {
    "human_triggered_color": "Colour on person/vehicle",
    "auto_color": "Auto colour",
    "auto_ir": "Auto IR",
    "white_led_always_on": "White LED always on",
    "ir_always_on": "IR always on",
    "off": "Off",
    "custom": "Custom",
}
WHITE_LED_MODES = {"human_triggered_color", "auto_color", "white_led_always_on"}
SPOTLIGHT_ON = ("wtl_night_vision", "white_led_always_on")
SPOTLIGHT_OFF = ("inf_night_vision", "auto_ir")


class VigiError(Exception):
    """Camera unreachable or answered with an error."""


class VigiAuthError(VigiError):
    """Login refused."""


def _ssl_context() -> ssl.SSLContext:
    # Cameras use a TP-Link internal CA. SSLContext() avoids the blocking
    # load_default_certs() of ssl.create_default_context().
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    ctx.set_ciphers("DEFAULT:AES256-GCM-SHA384:AES128-GCM-SHA256:@SECLEVEL=2")
    return ctx


def _parse_presets(data: dict) -> list[dict[str, str]]:
    ids = data.get("id", [])
    names = data.get("name", [])
    ids = [ids] if isinstance(ids, str) else ids
    names = [names] if isinstance(names, str) else names
    return [
        {"id": str(ids[i]), "name": urllib.parse.unquote(str(names[i]))}
        for i in range(min(len(ids), len(names)))
    ]


class VigiCamera:
    """Async client; one instance per camera."""

    def __init__(self, host: str, username: str, password: str) -> None:
        self.host = host
        self._username = username
        self._password = password
        self._base = f"https://{host}"
        self._stok: str | None = None
        self._session: aiohttp.ClientSession | None = None

    def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession(
                connector=aiohttp.TCPConnector(ssl=_ssl_context()), timeout=_TIMEOUT
            )
        return self._session

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    async def _post(self, url: str, body: dict) -> dict:
        try:
            async with self._get_session().post(url, json=body) as resp:
                return await resp.json(content_type=None)
        except (aiohttp.ClientError, TimeoutError, ValueError) as err:
            raise VigiError(f"{self.host}: {err}") from err

    def _encrypt(self, nonce: str, key_b64: str) -> str:
        pems = [key_b64] if "BEGIN" in key_b64 else [
            f"-----BEGIN {kind}-----\n{key_b64}\n-----END {kind}-----"
            for kind in ("PUBLIC KEY", "RSA PUBLIC KEY")
        ]
        for pem in pems:
            try:
                key = load_pem_public_key(pem.encode())
                break
            except ValueError:
                continue
        else:
            raise VigiError(f"{self.host}: unreadable login key")
        digest = hashlib.md5((_PASSWORD_PREFIX + self._password).encode()).hexdigest().upper()
        return base64.b64encode(
            key.encrypt(f"{digest}:{nonce}".encode(), padding.PKCS1v15())  # type: ignore[union-attr]
        ).decode()

    async def login(self) -> None:
        info = await self._post(
            self._base + "/",
            {"user_management": {"get_encrypt_info": None}, "method": "do"},
        )
        try:
            nonce = info["data"]["nonce"]
            key = urllib.parse.unquote(info["data"]["key"])
        except (KeyError, TypeError) as err:
            raise VigiAuthError(f"{self.host}: not a VIGI camera API") from err
        login = await self._post(
            self._base + "/",
            {
                "method": "do",
                "login": {
                    "username": self._username,
                    "password": self._encrypt(nonce, key),
                    "passwdType": "md5",
                    "encrypt_type": "2",
                },
            },
        )
        stok = login.get("stok") or (login.get("result") or {}).get("stok")
        if not stok:
            raise VigiAuthError(f"{self.host}: login refused ({login.get('error_code')})")
        self._stok = stok

    async def request(self, body: dict) -> dict:
        if not self._stok:
            await self.login()
        resp = await self._post(f"{self._base}/stok={self._stok}/ds", body)
        if resp.get("error_code") in (-40401, -40415):  # session expired
            await self.login()
            resp = await self._post(f"{self._base}/stok={self._stok}/ds", body)
        code = resp.get("error_code", 0)
        if code not in (0, None):
            raise VigiError(f"{self.host}: camera refused ({code})")
        return resp

    async def get_many(self, keys: list[str]) -> dict[str, Any]:
        """Read several POLL_READS keys in one request (missing = unsupported)."""
        body: dict[str, Any] = {"method": "get"}
        sections: dict[str, list[str]] = {}
        for key in keys:
            module, section = POLL_READS[key]
            sections.setdefault(module, []).append(section)
        for module, names in sections.items():
            body[module] = {"name": names[0] if len(names) == 1 else names}
        resp = await self.request(body)
        out: dict[str, Any] = {}
        for key in keys:
            module, section = POLL_READS[key]
            data = (resp.get(module) or {}).get(section)
            if key == "presets":
                if isinstance(data, dict) and "id" in data:
                    out[key] = _parse_presets(data)
            elif isinstance(data, dict):
                out[key] = data
        return out

    async def set(self, module: str, section: str, fields: dict[str, Any]) -> None:
        await self.request({"method": "set", module: {section: fields}})

    async def do(self, module: str, action: dict[str, Any]) -> None:
        await self.request({"method": "do", module: action})

    async def goto_preset(self, preset_id: str) -> None:
        await self.do("preset", {"goto_preset": {"channel": 0, "id": preset_id}})

    async def alarm(self, start: bool) -> None:
        await self.do("msg_alarm", {"manual_msg_alarm": {"action": "start" if start else "stop"}})
