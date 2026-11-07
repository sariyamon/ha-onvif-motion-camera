"""Binary sensors: one per ONVIF event the camera reports, plus connectivity."""
from __future__ import annotations

from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from . import OnvifMotionConfigEntry
from .const import (
    EV_AUDIO,
    EV_DIGITAL_INPUT,
    EV_FACE,
    EV_INTRUSION,
    EV_LINE,
    EV_LOITERING,
    EV_MOTION,
    EV_PERSON,
    EV_PET,
    EV_REGION_ENTER,
    EV_REGION_EXIT,
    EV_SCENE_CHANGE,
    EV_STORAGE,
    EV_TAMPER,
    EV_TOO_BLURRY,
    EV_TOO_BRIGHT,
    EV_TOO_DARK,
    EV_VEHICLE,
    SIGNAL_NEW_EVENT,
)
from .entity import OnvifMotionEntity
from .hub import OnvifHub

DEVICE_CLASSES: dict[str, BinarySensorDeviceClass] = {
    EV_MOTION: BinarySensorDeviceClass.MOTION,
    EV_PERSON: BinarySensorDeviceClass.OCCUPANCY,
    EV_VEHICLE: BinarySensorDeviceClass.MOTION,
    EV_PET: BinarySensorDeviceClass.MOTION,
    EV_FACE: BinarySensorDeviceClass.OCCUPANCY,
    EV_LINE: BinarySensorDeviceClass.MOTION,
    EV_INTRUSION: BinarySensorDeviceClass.MOTION,
    EV_REGION_ENTER: BinarySensorDeviceClass.MOTION,
    EV_REGION_EXIT: BinarySensorDeviceClass.MOTION,
    EV_LOITERING: BinarySensorDeviceClass.OCCUPANCY,
    EV_TAMPER: BinarySensorDeviceClass.TAMPER,
    EV_TOO_DARK: BinarySensorDeviceClass.PROBLEM,
    EV_TOO_BRIGHT: BinarySensorDeviceClass.PROBLEM,
    EV_TOO_BLURRY: BinarySensorDeviceClass.PROBLEM,
    EV_SCENE_CHANGE: BinarySensorDeviceClass.PROBLEM,
    EV_AUDIO: BinarySensorDeviceClass.SOUND,
    EV_DIGITAL_INPUT: BinarySensorDeviceClass.OPENING,
    EV_STORAGE: BinarySensorDeviceClass.PROBLEM,
}
ICONS: dict[str, str] = {
    EV_PERSON: "mdi:human",
    EV_VEHICLE: "mdi:car",
    EV_PET: "mdi:paw",
    EV_FACE: "mdi:face-recognition",
    EV_LINE: "mdi:ray-start-arrow",
    EV_INTRUSION: "mdi:shield-alert",
    EV_REGION_ENTER: "mdi:location-enter",
    EV_REGION_EXIT: "mdi:location-exit",
    EV_LOITERING: "mdi:account-clock",
}
DIAGNOSTIC_KINDS = {EV_TOO_DARK, EV_TOO_BRIGHT, EV_TOO_BLURRY, EV_SCENE_CHANGE, EV_STORAGE}


async def async_setup_entry(
    hass: HomeAssistant,
    entry: OnvifMotionConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    hub = entry.runtime_data
    known: set[str] = set()

    # Re-create sensors seen before a restart so automations never lose them,
    # even if the camera only reports an event when it first happens.
    restored: list[BinarySensorEntity] = (
        [EventSubscriptionSensor(hub)] if hub.is_onvif or hub.vigi else []
    )
    registry = er.async_get(hass)
    prefix = f"{hub.unique_id}_event_"
    for reg in er.async_entries_for_config_entry(registry, entry.entry_id):
        if (
            reg.domain == "binary_sensor"
            and reg.unique_id.startswith(prefix)
            and reg.unique_id != f"{hub.unique_id}_event_subscription"
        ):
            uid = reg.unique_id[len(prefix):]
            known.add(uid)
            restored.append(OnvifEventSensor(hub, uid, reg.original_name, None))
    async_add_entities(restored)

    @callback
    def _new_event(uid: str) -> None:
        if uid in known:
            return
        known.add(uid)
        state = hub.events[uid]
        async_add_entities(
            [OnvifEventSensor(hub, uid, state.event.name, state.event.kind)]
        )

    entry.async_on_unload(
        async_dispatcher_connect(hass, SIGNAL_NEW_EVENT.format(entry.entry_id), _new_event)
    )
    for uid in list(hub.events):
        _new_event(uid)


class OnvifEventSensor(OnvifMotionEntity, BinarySensorEntity, RestoreEntity):
    """On while the camera reports the event as active."""

    def __init__(self, hub: OnvifHub, uid: str, name: str | None, kind: str | None) -> None:
        super().__init__(hub, f"event_{uid}")
        self._uid = uid
        self._attr_name = name or "Event"
        self._kind = kind
        self._restored_on: bool | None = None
        self._apply_kind(kind)

    def _apply_kind(self, kind: str | None) -> None:
        if kind is None:
            return
        self._kind = kind
        self._attr_device_class = DEVICE_CLASSES.get(kind)
        self._attr_icon = ICONS.get(kind)
        self._attr_entity_category = (
            EntityCategory.DIAGNOSTIC if kind in DIAGNOSTIC_KINDS else None
        )

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if self._kind is None and (last := await self.async_get_last_state()):
            kind = last.attributes.get("event_type")
            if kind:
                self._apply_kind(kind)

    @property
    def available(self) -> bool:
        return self.hub.subscribed or self.hub.push_active or self._uid in self.hub.events

    @property
    def is_on(self) -> bool | None:
        state = self.hub.events.get(self._uid)
        return state.active if state else False

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        state = self.hub.events.get(self._uid)
        attrs: dict[str, Any] = {"event_type": self._kind}
        if state:
            if self._kind is None:
                self._apply_kind(state.event.kind)
                attrs["event_type"] = state.event.kind
            attrs.update(
                {
                    "topic": state.event.topic,
                    "source": state.event.source,
                    "last_triggered": state.last_triggered,
                    "trigger_count": state.count,
                    "data": state.event.data,
                }
            )
        return attrs


class EventSubscriptionSensor(OnvifMotionEntity, BinarySensorEntity):
    """On while the ONVIF event subscription is running."""

    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_translation_key = "event_subscription"

    def __init__(self, hub: OnvifHub) -> None:
        super().__init__(hub, "event_subscription")

    @property
    def is_on(self) -> bool:
        return self.hub.subscribed or self.hub.push_active

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"onvif_events": self.hub.subscribed, "vigi_push_events": self.hub.push_active}

