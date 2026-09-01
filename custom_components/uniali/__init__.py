"""uniali — UniFi Alias Sync für Home Assistant."""
from __future__ import annotations

import logging
from pathlib import Path

import voluptuous as vol

from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import Platform
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv
from homeassistant.loader import async_get_integration

from .const import (
    ATTR_HOSTNAME,
    ATTR_MAC,
    CARD_URL,
    DOMAIN,
    SERVICE_FORGET_UNIFI,
    SERVICE_REFRESH,
    SERVICE_SYNC_DEVICE,
    SERVICE_SYNC_HOSTNAME,
    SERVICE_SYNC_UNIFI,
)
from .coordinator import UnialiCoordinator
from .herold import async_topics_registrieren

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.SENSOR]

SERVICE_SYNC_SCHEMA = vol.Schema({vol.Required(ATTR_MAC): cv.string})
# sync_hostname kennt zusätzlich einen freien Zielwert — für UniFi-Clients ohne
# HA-Gerät, die keinen HA-Namen als Quelle haben.
SERVICE_HOSTNAME_SCHEMA = vol.Schema(
    {vol.Required(ATTR_MAC): cv.string, vol.Optional(ATTR_HOSTNAME): cv.string}
)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up uniali via Config Entry."""
    coordinator = UnialiCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()

    hass.data.setdefault(DOMAIN, {})[entry.entry_id] = coordinator

    await _async_register_card(hass)
    _async_register_services(hass, coordinator)
    # Meldungs-Topics bei Herold anmelden (optional — no-op ohne Herold).
    async_topics_registrieren(hass)

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload Config Entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        hass.data[DOMAIN].pop(entry.entry_id, None)
    return unload_ok


async def _async_register_card(hass: HomeAssistant) -> None:
    """Stellt die Custom Card als statische Datei bereit und registriert sie als
    Lovelace-Resource (Module). Idempotent — überspringt wenn schon eingetragen.

    `add_extra_js_url` wäre der nahe liegende Weg, ist im Browser aber unzuverlässig
    (Race / Cache / Modul-Loading); explizite Resource ist robust.
    """
    if hass.data[DOMAIN].get("_card_registered"):
        return

    card_path = Path(__file__).parent / "lovelace" / "uniali-card.js"
    await hass.http.async_register_static_paths(
        [StaticPathConfig(CARD_URL, str(card_path), cache_headers=False)]
    )

    # Resource-URL trägt die Integrations-Version als Query. Grund: der Browser
    # cacht ein einmal geladenes ES-Modul pro URL hartnäckig — ohne den
    # Parameter sieht der User nach einem uniali-Update weiter die alte Card
    # und muss von Hand hart neu laden. Die Query interessiert den
    # Static-Handler nicht, sie ist reines Cache-Busting.
    integration = await async_get_integration(hass, DOMAIN)
    version = integration.manifest.get("version") or "0"
    versioned_url = f"{CARD_URL}?v={version}"

    # Lovelace-Resource registrieren (nur in Storage-Mode möglich; YAML-Mode-User
    # müssen den Eintrag manuell in lovelace.yaml ergänzen).
    try:
        from homeassistant.components.lovelace import (
            DOMAIN as LL_DOMAIN,
            LOVELACE_DATA,
        )
        from homeassistant.components.lovelace.resources import (
            ResourceStorageCollection,
        )
    except ImportError:
        LL_DOMAIN = "lovelace"  # noqa: N806
        LOVELACE_DATA = "lovelace"  # noqa: N806
        ResourceStorageCollection = None  # type: ignore[assignment, misc]

    lovelace = hass.data.get(LOVELACE_DATA)
    resources = getattr(lovelace, "resources", None) if lovelace else None

    if (
        resources is not None
        and ResourceStorageCollection is not None
        and isinstance(resources, ResourceStorageCollection)
    ):
        if not getattr(resources, "loaded", True):
            await resources.async_load()
            resources.loaded = True
        # Bestehenden Eintrag über den Pfad finden — die Version dahinter
        # ändert sich ja gerade, ein Vergleich auf die volle URL würde bei
        # jedem Update einen zweiten Eintrag anlegen.
        vorhanden = next(
            (
                item
                for item in resources.async_items()
                if (item.get("url") or "").split("?", 1)[0] == CARD_URL
            ),
            None,
        )
        if vorhanden is None:
            await resources.async_create_item(
                {"res_type": "module", "url": versioned_url}
            )
            _LOGGER.info(
                "Lovelace-Resource registriert: %s (Browser-Reload nötig)",
                versioned_url,
            )
        elif vorhanden.get("url") != versioned_url:
            await resources.async_update_item(
                vorhanden["id"], {"res_type": "module", "url": versioned_url}
            )
            _LOGGER.info(
                "Lovelace-Resource aktualisiert: %s → %s",
                vorhanden.get("url"),
                versioned_url,
            )
    else:
        _LOGGER.warning(
            "Lovelace im YAML-Mode oder nicht verfügbar — bitte manuell als "
            "Resource eintragen: url=%s, type=module",
            versioned_url,
        )

    hass.data[DOMAIN]["_card_registered"] = True


def _async_register_services(
    hass: HomeAssistant, coordinator: UnialiCoordinator
) -> None:
    """Registriert die uniali-Services."""
    if hass.services.has_service(DOMAIN, SERVICE_REFRESH):
        return

    async def _refresh(call: ServiceCall) -> None:
        for coord in hass.data[DOMAIN].values():
            if isinstance(coord, UnialiCoordinator):
                await coord.async_request_refresh()

    async def _sync_unifi(call: ServiceCall) -> None:
        mac = call.data[ATTR_MAC]
        for coord in hass.data[DOMAIN].values():
            if isinstance(coord, UnialiCoordinator):
                await coord.async_sync_unifi(mac)

    async def _sync_device(call: ServiceCall) -> None:
        mac = call.data[ATTR_MAC]
        for coord in hass.data[DOMAIN].values():
            if isinstance(coord, UnialiCoordinator):
                await coord.async_sync_device(mac)

    async def _sync_hostname(call: ServiceCall) -> None:
        mac = call.data[ATTR_MAC]
        hostname = call.data.get(ATTR_HOSTNAME)
        for coord in hass.data[DOMAIN].values():
            if isinstance(coord, UnialiCoordinator):
                await coord.async_sync_hostname(mac, hostname)

    async def _forget_unifi(call: ServiceCall) -> None:
        mac = call.data[ATTR_MAC]
        for coord in hass.data[DOMAIN].values():
            if isinstance(coord, UnialiCoordinator):
                await coord.async_forget_unifi(mac)

    hass.services.async_register(DOMAIN, SERVICE_REFRESH, _refresh)
    hass.services.async_register(
        DOMAIN, SERVICE_SYNC_UNIFI, _sync_unifi, schema=SERVICE_SYNC_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, SERVICE_SYNC_DEVICE, _sync_device, schema=SERVICE_SYNC_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, SERVICE_SYNC_HOSTNAME, _sync_hostname, schema=SERVICE_HOSTNAME_SCHEMA
    )
    hass.services.async_register(
        DOMAIN, SERVICE_FORGET_UNIFI, _forget_unifi, schema=SERVICE_SYNC_SCHEMA
    )
