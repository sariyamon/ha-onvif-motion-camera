"""Config and options flow: credentials, IP, protocol, alerts."""
from __future__ import annotations

from collections.abc import Mapping
import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import (
    CONF_HOST,
    CONF_NAME,
    CONF_PASSWORD,
    CONF_PORT,
    CONF_USERNAME,
)
from homeassistant.core import callback
from homeassistant.helpers.device_registry import format_mac
from homeassistant.helpers.selector import (
    EntitySelector,
    EntitySelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
    TextSelector,
    TextSelectorConfig,
    TextSelectorType,
)

from .const import (
    CONF_ALERT_COOLDOWN,
    CONF_ALERT_EVENTS,
    CONF_ALERT_MESSAGE,
    CONF_EVENT_OFF_DELAY,
    CONF_PROFILE_TOKEN,
    CONF_PROTOCOL,
    CONF_RTSP_TRANSPORT,
    CONF_SNAPSHOT_COOLDOWN,
    CONF_SNAPSHOT_EVENTS,
    CONF_SNAPSHOT_KEEP,
    CONF_TELEGRAM_CHAT_IDS,
    CONF_TELEGRAM_NOTIFY,
    CONF_TELEGRAM_TOKEN,
    CONF_WHATSAPP_APIKEY,
    CONF_WHATSAPP_NOTIFY_ACTION,
    CONF_WHATSAPP_PHONE_ID,
    CONF_WHATSAPP_PROVIDER,
    CONF_WHATSAPP_RECIPIENTS,
    CONF_WHATSAPP_TOKEN,
    DEFAULT_ALERT_COOLDOWN,
    DEFAULT_ALERT_EVENTS,
    DEFAULT_ALERT_MESSAGE,
    DEFAULT_EVENT_OFF_DELAY,
    DEFAULT_PORT,
    DEFAULT_SNAPSHOT_COOLDOWN,
    DEFAULT_SNAPSHOT_EVENTS,
    DEFAULT_SNAPSHOT_KEEP,
    DEFAULT_USERNAME,
    DETECTION_KINDS,
    DOMAIN,
    EVENT_LABELS,
    PROTOCOL_HTTP,
    PROTOCOLS,
    RTSP_TRANSPORTS,
    WA_NONE,
    WHATSAPP_PROVIDERS,
)
from .hub import CannotConnect, InvalidAuth, async_probe

_LOGGER = logging.getLogger(__name__)

PASSWORD = TextSelector(TextSelectorConfig(type=TextSelectorType.PASSWORD))


def _connection_schema(defaults: Mapping[str, Any], with_name: bool) -> vol.Schema:
    fields: dict[Any, Any] = {}
    if with_name:
        fields[vol.Required(CONF_NAME, default=defaults.get(CONF_NAME, ""))] = str
    fields.update(
        {
            vol.Required(CONF_HOST, default=defaults.get(CONF_HOST, "")): str,
            vol.Required(CONF_PORT, default=defaults.get(CONF_PORT, DEFAULT_PORT)): vol.All(
                vol.Coerce(int), vol.Range(min=1, max=65535)
            ),
            vol.Required(
                CONF_PROTOCOL, default=defaults.get(CONF_PROTOCOL, PROTOCOL_HTTP)
            ): SelectSelector(
                SelectSelectorConfig(
                    options=PROTOCOLS,
                    mode=SelectSelectorMode.LIST,
                    translation_key="protocol",
                )
            ),
            vol.Required(
                CONF_USERNAME, default=defaults.get(CONF_USERNAME, DEFAULT_USERNAME)
            ): str,
            vol.Required(CONF_PASSWORD, default=defaults.get(CONF_PASSWORD, "")): PASSWORD,
        }
    )
    return vol.Schema(fields)


def _event_selector() -> SelectSelector:
    return SelectSelector(
        SelectSelectorConfig(
            options=[
                SelectOptionDict(value=kind, label=EVENT_LABELS[kind])
                for kind in DETECTION_KINDS
            ],
            multiple=True,
            mode=SelectSelectorMode.LIST,
        )
    )


def _seconds(maximum: int) -> NumberSelector:
    return NumberSelector(
        NumberSelectorConfig(
            min=0, max=maximum, step=1, mode=NumberSelectorMode.BOX, unit_of_measurement="s"
        )
    )


async def _validate(data: dict[str, Any]) -> tuple[dict[str, str], Any, list[dict[str, Any]]]:
    errors: dict[str, str] = {}
    info = None
    profiles: list[dict[str, Any]] = []
    try:
        info, profiles = await async_probe(data)
    except InvalidAuth:
        errors["base"] = "invalid_auth"
    except CannotConnect as err:
        _LOGGER.debug("Cannot connect to %s: %s", data.get(CONF_HOST), err)
        errors["base"] = "cannot_connect"
    except Exception:  # noqa: BLE001
        _LOGGER.exception("Unexpected error probing camera")
        errors["base"] = "unknown"
    return errors, info, profiles


class OnvifMotionConfigFlow(ConfigFlow, domain=DOMAIN):
    """Add a camera: IP, protocol, port, username, password."""

    VERSION = 1

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}
        self._profiles: list[dict[str, Any]] = []

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OnvifMotionOptionsFlow:
        return OnvifMotionOptionsFlow()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            errors, info, profiles = await _validate(user_input)
            if not errors:
                unique = format_mac(info.mac) if info.mac else (info.serial or user_input[CONF_HOST])
                await self.async_set_unique_id(unique)
                self._abort_if_unique_id_configured(
                    updates={k: user_input[k] for k in (CONF_HOST, CONF_PORT, CONF_PROTOCOL)}
                )
                self._data = dict(user_input)
                if not self._data.get(CONF_NAME):
                    self._data[CONF_NAME] = info.model
                self._profiles = profiles
                return await self.async_step_stream()
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(
                _connection_schema({}, with_name=True), user_input or {}
            ),
            errors=errors,
        )

    async def async_step_stream(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Pick the video profile (main / sub stream) and RTSP transport."""
        if user_input is not None:
            self._data.update(user_input)
            return self.async_create_entry(title=self._data[CONF_NAME], data=self._data)

        options = [
            SelectOptionDict(
                value=p["token"],
                label=f"{p['name']} – {p['width']}×{p['height']} {p['encoding']}".strip(),
            )
            for p in self._profiles
        ]
        schema = vol.Schema(
            {
                vol.Required(CONF_PROFILE_TOKEN, default=self._profiles[0]["token"]): SelectSelector(
                    SelectSelectorConfig(options=options, mode=SelectSelectorMode.LIST)
                ),
                vol.Required(CONF_RTSP_TRANSPORT, default="tcp"): SelectSelector(
                    SelectSelectorConfig(
                        options=RTSP_TRANSPORTS,
                        mode=SelectSelectorMode.LIST,
                        translation_key="rtsp_transport",
                    )
                ),
            }
        )
        return self.async_show_form(step_id="stream", data_schema=schema)

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Change IP, port, protocol or credentials of an existing camera."""
        entry = self._get_reconfigure_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            data = {**entry.data, **user_input}
            errors, info, _ = await _validate(data)
            if not errors:
                return self.async_update_reload_and_abort(entry, data=data)
        return self.async_show_form(
            step_id="reconfigure",
            data_schema=_connection_schema(user_input or entry.data, with_name=False),
            errors=errors,
        )

    async def async_step_reauth(
        self, entry_data: Mapping[str, Any]
    ) -> ConfigFlowResult:
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        entry = self._get_reauth_entry()
        errors: dict[str, str] = {}
        if user_input is not None:
            data = {**entry.data, **user_input}
            errors, _, _ = await _validate(data)
            if not errors:
                return self.async_update_reload_and_abort(entry, data=data)
        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_USERNAME, default=entry.data[CONF_USERNAME]): str,
                    vol.Required(CONF_PASSWORD): PASSWORD,
                }
            ),
            errors=errors,
            description_placeholders={"name": entry.title},
        )


class OnvifMotionOptionsFlow(OptionsFlow):
    """Snapshot rules, Telegram and WhatsApp alerts."""

    def __init__(self) -> None:
        self._options: dict[str, Any] = {}

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if not self._options:
            self._options = dict(self.config_entry.options)
        return self.async_show_menu(
            step_id="init",
            menu_options=["snapshots", "alerts", "telegram", "whatsapp", "save"],
        )

    async def async_step_save(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        return self.async_create_entry(data=self._options)

    async def async_step_snapshots(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            self._options.update(user_input)
            return await self.async_step_init()
        o = self._options
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_SNAPSHOT_EVENTS, default=o.get(CONF_SNAPSHOT_EVENTS, DEFAULT_SNAPSHOT_EVENTS)
                ): _event_selector(),
                vol.Required(
                    CONF_SNAPSHOT_COOLDOWN,
                    default=o.get(CONF_SNAPSHOT_COOLDOWN, DEFAULT_SNAPSHOT_COOLDOWN),
                ): _seconds(3600),
                vol.Required(
                    CONF_SNAPSHOT_KEEP, default=o.get(CONF_SNAPSHOT_KEEP, DEFAULT_SNAPSHOT_KEEP)
                ): NumberSelector(
                    NumberSelectorConfig(min=1, max=5000, step=1, mode=NumberSelectorMode.BOX)
                ),
                vol.Required(
                    CONF_EVENT_OFF_DELAY,
                    default=o.get(CONF_EVENT_OFF_DELAY, DEFAULT_EVENT_OFF_DELAY),
                ): _seconds(600),
            }
        )
        return self.async_show_form(step_id="snapshots", data_schema=schema)

    async def async_step_alerts(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            self._options.update(user_input)
            return await self.async_step_init()
        o = self._options
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_ALERT_EVENTS, default=o.get(CONF_ALERT_EVENTS, DEFAULT_ALERT_EVENTS)
                ): _event_selector(),
                vol.Required(
                    CONF_ALERT_COOLDOWN, default=o.get(CONF_ALERT_COOLDOWN, DEFAULT_ALERT_COOLDOWN)
                ): _seconds(86400),
                vol.Required(
                    CONF_ALERT_MESSAGE, default=o.get(CONF_ALERT_MESSAGE, DEFAULT_ALERT_MESSAGE)
                ): str,
            }
        )
        return self.async_show_form(
            step_id="alerts",
            data_schema=schema,
            description_placeholders={
                "camera": "{camera}",
                "event": "{event}",
                "time": "{time}",
                "date": "{date}",
            },
        )

    async def async_step_telegram(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            self._options[CONF_TELEGRAM_NOTIFY] = user_input.get(CONF_TELEGRAM_NOTIFY, [])
            self._options[CONF_TELEGRAM_TOKEN] = user_input.get(CONF_TELEGRAM_TOKEN, "").strip()
            self._options[CONF_TELEGRAM_CHAT_IDS] = user_input.get(CONF_TELEGRAM_CHAT_IDS, "").strip()
            return await self.async_step_init()
        o = self._options
        schema = vol.Schema(
            {
                vol.Optional(
                    CONF_TELEGRAM_NOTIFY,
                    description={"suggested_value": o.get(CONF_TELEGRAM_NOTIFY, [])},
                ): EntitySelector(
                    EntitySelectorConfig(
                        domain="notify", integration="telegram_bot", multiple=True
                    )
                ),
                vol.Optional(
                    CONF_TELEGRAM_TOKEN,
                    description={"suggested_value": o.get(CONF_TELEGRAM_TOKEN, "")},
                ): PASSWORD,
                vol.Optional(
                    CONF_TELEGRAM_CHAT_IDS,
                    description={"suggested_value": o.get(CONF_TELEGRAM_CHAT_IDS, "")},
                ): str,
            }
        )
        return self.async_show_form(step_id="telegram", data_schema=schema)

    async def async_step_whatsapp(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        if user_input is not None:
            for key in (
                CONF_WHATSAPP_PROVIDER,
                CONF_WHATSAPP_TOKEN,
                CONF_WHATSAPP_PHONE_ID,
                CONF_WHATSAPP_APIKEY,
                CONF_WHATSAPP_RECIPIENTS,
                CONF_WHATSAPP_NOTIFY_ACTION,
            ):
                value = user_input.get(key, "")
                self._options[key] = value.strip() if isinstance(value, str) else value
            return await self.async_step_init()
        o = self._options

        def suggested(key: str) -> dict[str, Any]:
            return {"suggested_value": o.get(key, "")}

        schema = vol.Schema(
            {
                vol.Required(
                    CONF_WHATSAPP_PROVIDER, default=o.get(CONF_WHATSAPP_PROVIDER, WA_NONE)
                ): SelectSelector(
                    SelectSelectorConfig(
                        options=WHATSAPP_PROVIDERS,
                        mode=SelectSelectorMode.LIST,
                        translation_key="whatsapp_provider",
                    )
                ),
                vol.Optional(CONF_WHATSAPP_RECIPIENTS, description=suggested(CONF_WHATSAPP_RECIPIENTS)): str,
                vol.Optional(CONF_WHATSAPP_TOKEN, description=suggested(CONF_WHATSAPP_TOKEN)): PASSWORD,
                vol.Optional(CONF_WHATSAPP_PHONE_ID, description=suggested(CONF_WHATSAPP_PHONE_ID)): str,
                vol.Optional(CONF_WHATSAPP_APIKEY, description=suggested(CONF_WHATSAPP_APIKEY)): PASSWORD,
                vol.Optional(
                    CONF_WHATSAPP_NOTIFY_ACTION, description=suggested(CONF_WHATSAPP_NOTIFY_ACTION)
                ): str,
            }
        )
        return self.async_show_form(step_id="whatsapp", data_schema=schema)
