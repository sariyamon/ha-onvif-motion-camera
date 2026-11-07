"""Built-in Telegram and WhatsApp alerts (no Node-RED needed)."""
from __future__ import annotations

import logging
from typing import Any

import aiohttp

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    CONF_TELEGRAM_CHAT_IDS,
    CONF_TELEGRAM_TOKEN,
    CONF_WHATSAPP_APIKEY,
    CONF_WHATSAPP_NOTIFY_ACTION,
    CONF_WHATSAPP_PHONE_ID,
    CONF_WHATSAPP_PROVIDER,
    CONF_WHATSAPP_RECIPIENTS,
    CONF_WHATSAPP_TOKEN,
    WA_CALLMEBOT,
    WA_CLOUD_API,
    WA_HA_NOTIFY,
    WA_NONE,
)

_LOGGER = logging.getLogger(__name__)

TELEGRAM_API = "https://api.telegram.org/bot{token}/{method}"
WHATSAPP_GRAPH = "https://graph.facebook.com/v21.0/{phone_id}/{path}"
CALLMEBOT_API = "https://api.callmebot.com/whatsapp.php"
TIMEOUT = aiohttp.ClientTimeout(total=30)

CHANNEL_TELEGRAM = "telegram"
CHANNEL_WHATSAPP = "whatsapp"


def split_list(value: str | None) -> list[str]:
    """Split a comma / newline separated list of ids or numbers."""
    if not value:
        return []
    parts = value.replace("\n", ",").replace(";", ",").split(",")
    return [p.strip() for p in parts if p.strip()]


def telegram_configured(options: dict[str, Any]) -> bool:
    return bool(options.get(CONF_TELEGRAM_TOKEN)) and bool(
        split_list(options.get(CONF_TELEGRAM_CHAT_IDS))
    )


def whatsapp_configured(options: dict[str, Any]) -> bool:
    provider = options.get(CONF_WHATSAPP_PROVIDER, WA_NONE)
    if provider == WA_CLOUD_API:
        return bool(
            options.get(CONF_WHATSAPP_TOKEN)
            and options.get(CONF_WHATSAPP_PHONE_ID)
            and split_list(options.get(CONF_WHATSAPP_RECIPIENTS))
        )
    if provider == WA_CALLMEBOT:
        return bool(
            options.get(CONF_WHATSAPP_APIKEY)
            and split_list(options.get(CONF_WHATSAPP_RECIPIENTS))
        )
    if provider == WA_HA_NOTIFY:
        return bool(options.get(CONF_WHATSAPP_NOTIFY_ACTION))
    return False


async def send_telegram(
    hass: HomeAssistant,
    options: dict[str, Any],
    message: str,
    image: bytes | None,
) -> None:
    """Send a photo (or text) to every configured Telegram chat."""
    token = options[CONF_TELEGRAM_TOKEN].strip()
    session = async_get_clientsession(hass)
    errors: list[str] = []
    for chat_id in split_list(options.get(CONF_TELEGRAM_CHAT_IDS)):
        try:
            if image:
                form = aiohttp.FormData()
                form.add_field("chat_id", chat_id)
                form.add_field("caption", message[:1024])
                form.add_field(
                    "photo", image, filename="snapshot.jpg", content_type="image/jpeg"
                )
                url = TELEGRAM_API.format(token=token, method="sendPhoto")
                async with session.post(url, data=form, timeout=TIMEOUT) as resp:
                    body = await resp.json(content_type=None)
            else:
                url = TELEGRAM_API.format(token=token, method="sendMessage")
                async with session.post(
                    url, json={"chat_id": chat_id, "text": message}, timeout=TIMEOUT
                ) as resp:
                    body = await resp.json(content_type=None)
            if not body.get("ok"):
                errors.append(f"{chat_id}: {body.get('description', 'unknown error')}")
        except (aiohttp.ClientError, TimeoutError, ValueError) as err:
            errors.append(f"{chat_id}: {err}")
    if errors:
        raise HomeAssistantError("Telegram: " + "; ".join(errors))


async def _wa_cloud(
    hass: HomeAssistant, options: dict[str, Any], message: str, image: bytes | None
) -> None:
    session = async_get_clientsession(hass)
    phone_id = options[CONF_WHATSAPP_PHONE_ID].strip()
    headers = {"Authorization": f"Bearer {options[CONF_WHATSAPP_TOKEN].strip()}"}
    media_id: str | None = None
    if image:
        form = aiohttp.FormData()
        form.add_field("messaging_product", "whatsapp")
        form.add_field("type", "image/jpeg")
        form.add_field("file", image, filename="snapshot.jpg", content_type="image/jpeg")
        url = WHATSAPP_GRAPH.format(phone_id=phone_id, path="media")
        async with session.post(url, data=form, headers=headers, timeout=TIMEOUT) as resp:
            body = await resp.json(content_type=None)
        media_id = body.get("id")
        if not media_id:
            _LOGGER.warning("WhatsApp media upload failed, sending text only: %s", body)

    errors: list[str] = []
    url = WHATSAPP_GRAPH.format(phone_id=phone_id, path="messages")
    for number in split_list(options.get(CONF_WHATSAPP_RECIPIENTS)):
        to = number.lstrip("+").replace(" ", "")
        if media_id:
            payload = {
                "messaging_product": "whatsapp",
                "to": to,
                "type": "image",
                "image": {"id": media_id, "caption": message[:1024]},
            }
        else:
            payload = {
                "messaging_product": "whatsapp",
                "to": to,
                "type": "text",
                "text": {"body": message},
            }
        async with session.post(url, json=payload, headers=headers, timeout=TIMEOUT) as resp:
            body = await resp.json(content_type=None)
        if "error" in body:
            errors.append(f"{number}: {body['error'].get('message', body['error'])}")
    if errors:
        raise HomeAssistantError("WhatsApp: " + "; ".join(errors))


async def _wa_callmebot(
    hass: HomeAssistant, options: dict[str, Any], message: str
) -> None:
    session = async_get_clientsession(hass)
    errors: list[str] = []
    for number in split_list(options.get(CONF_WHATSAPP_RECIPIENTS)):
        params = {
            "phone": number.replace(" ", ""),
            "text": message,
            "apikey": options[CONF_WHATSAPP_APIKEY].strip(),
        }
        async with session.get(CALLMEBOT_API, params=params, timeout=TIMEOUT) as resp:
            text = await resp.text()
        if resp.status >= 300 or "error" in text.lower()[:200]:
            errors.append(f"{number}: HTTP {resp.status}")
    if errors:
        raise HomeAssistantError("WhatsApp (CallMeBot): " + "; ".join(errors))


async def _wa_ha_notify(
    hass: HomeAssistant,
    options: dict[str, Any],
    message: str,
    snapshot_path: str | None,
) -> None:
    action = options[CONF_WHATSAPP_NOTIFY_ACTION].strip()
    domain, _, service = action.partition(".")
    if not service:
        domain, service = "notify", action
    data: dict[str, Any] = {"message": message}
    if snapshot_path:
        data["data"] = {"media_url": snapshot_path, "file": snapshot_path}
    await hass.services.async_call(domain, service, data, blocking=True)


async def send_whatsapp(
    hass: HomeAssistant,
    options: dict[str, Any],
    message: str,
    image: bytes | None,
    snapshot_path: str | None,
) -> None:
    """Send a WhatsApp alert through the configured provider."""
    provider = options.get(CONF_WHATSAPP_PROVIDER, WA_NONE)
    try:
        if provider == WA_CLOUD_API:
            await _wa_cloud(hass, options, message, image)
        elif provider == WA_CALLMEBOT:
            await _wa_callmebot(hass, options, message)
        elif provider == WA_HA_NOTIFY:
            await _wa_ha_notify(hass, options, message, snapshot_path)
    except (aiohttp.ClientError, TimeoutError, ValueError) as err:
        raise HomeAssistantError(f"WhatsApp: {err}") from err
