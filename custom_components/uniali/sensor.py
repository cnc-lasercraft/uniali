"""Sensor: sensor.uniali_aliases."""
from __future__ import annotations

import logging

from homeassistant.components.sensor import SensorEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import UnialiCoordinator

_LOGGER = logging.getLogger(__name__)

DESIRED_ENTITY_ID = "sensor.uniali_aliases"


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: UnialiCoordinator = hass.data[DOMAIN][entry.entry_id]
    _migrate_legacy_entity_id(hass, entry)
    async_add_entities([UnialiSensor(coordinator, entry)])


def _migrate_legacy_entity_id(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Älterer Code legte das Entity unter sensor.aliases an. Wenn ein Entity
    mit unserer unique_id existiert aber unter dem Alt-Slug, sanft umbenennen."""
    ent_reg = er.async_get(hass)
    unique_id = f"{entry.entry_id}_aliases"
    existing = ent_reg.async_get_entity_id("sensor", DOMAIN, unique_id)
    if not existing or existing == DESIRED_ENTITY_ID:
        return
    if ent_reg.async_get(DESIRED_ENTITY_ID):
        _LOGGER.warning(
            "Migration übersprungen: %s existiert bereits", DESIRED_ENTITY_ID
        )
        return
    ent_reg.async_update_entity(existing, new_entity_id=DESIRED_ENTITY_ID)
    _LOGGER.info("Entity migriert: %s → %s", existing, DESIRED_ENTITY_ID)


class UnialiSensor(CoordinatorEntity[UnialiCoordinator], SensorEntity):
    _attr_has_entity_name = False
    _attr_icon = "mdi:tag-sync-outline"
    # entries-Liste ist gross (~100KB bei vielen Geräten) und für History irrelevant
    # — Recorder soll sie nicht persistieren (verhindert DB-Bloat + Log-Warning)
    _unrecorded_attributes = frozenset({"entries"})

    def __init__(self, coordinator: UnialiCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator)
        self._attr_unique_id = f"{entry.entry_id}_aliases"
        self._attr_name = "uniali Aliases"
        self._attr_suggested_object_id = "uniali_aliases"

    @property
    def native_value(self) -> int:
        # `mismatch` kommt fertig aus dem Coordinator (Alias, Gerätename,
        # DNS-Record, Alias-Konflikt — abzüglich stummgeschalteter Zeilen).
        # Bewusst dort zentral, damit Sensor-Zahl und Card-Filter nicht
        # auseinanderlaufen.
        entries = self.coordinator.data or []
        return sum(1 for e in entries if e["mismatch"])

    @property
    def extra_state_attributes(self) -> dict:
        return {"entries": self.coordinator.data or []}
